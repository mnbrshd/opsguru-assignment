"""Embedding intent router with on-disk centroid cache + margin guard."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

# Exemplar utterances per template (embeddings + offline token overlap)
TEMPLATE_EXAMPLES: dict[str, list[str]] = {
    "revenue_2024": [
        "What was our total recognized revenue in USD for paid invoices in 2024?",
        "How much recognized revenue did we book in 2024?",
        "Total paid revenue 2024 including refunds",
        "How much money did we recognize last year 2024?",
        "Sum of recognized revenue for calendar year 2024",
    ],
    "region_avg_mrr": [
        "Which region has the highest average MRR per account?",
        "Which region has the best average MRR?",
        "Region with highest avg MRR",
        "Where is average monthly recurring revenue highest by region?",
    ],
    "refunds": [
        "How much have we given back in refunds?",
        "Total refunds in USD",
        "How much money was refunded?",
        "What's the total of all refunded invoice amounts?",
    ],
    "churn_by_plan": [
        "What's the churn rate among Enterprise accounts vs Starter?",
        "Compare churn for enterprise and starter",
        "Enterprise vs starter churn rate",
        "Do enterprise customers churn more than starter?",
    ],
    "top5_revenue_csat": [
        "List the top 5 accounts by revenue, and flag any with CSAT ≤ 2.",
        "Top five accounts by revenue with low CSAT",
        "Highest revenue accounts and CSAT flags",
        "Who are our top revenue accounts and which have poor CSAT?",
    ],
    "pending_failed_exposure": [
        "How many invoices are stuck in pending/failed and what's the exposed $?",
        "Pending and failed invoice exposure",
        "How much is stuck in pending or failed?",
        "Exposed dollars on invoices awaiting payment or declined",
    ],
}

_EMBED_CACHE: dict[str, list[float]] | None = None
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_THRESHOLD = 0.72
DEFAULT_MARGIN = 0.03
DEFAULT_CACHE_PATH = Path("data/processed/embed_centroids.json")


def _openai_client():
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": os.environ["OPENAI_API_KEY"]}
    base = os.getenv("OPENAI_BASE_URL")
    if base:
        kwargs["base_url"] = base
    return OpenAI(**kwargs)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _embed_texts(texts: list[str]) -> list[list[float]]:
    client = _openai_client()
    model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    resp = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in sorted(resp.data, key=lambda d: d.index)]


def _examples_fingerprint() -> str:
    payload = json.dumps(TEMPLATE_EXAMPLES, sort_keys=True)
    model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    return hashlib.sha256(f"{model}:{payload}".encode()).hexdigest()[:16]


def _cache_path() -> Path:
    return Path(os.getenv("CLOUDNOVA_EMBED_CACHE", DEFAULT_CACHE_PATH))


def _load_disk_cache() -> dict[str, list[float]] | None:
    path = _cache_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("fingerprint") != _examples_fingerprint():
            return None
        centroids = data.get("centroids")
        if not isinstance(centroids, dict):
            return None
        return {k: list(map(float, v)) for k, v in centroids.items()}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _save_disk_cache(centroids: dict[str, list[float]]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fingerprint": _examples_fingerprint(),
        "model": os.getenv("OPENAI_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        "centroids": centroids,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _ensure_template_cache() -> dict[str, list[float]]:
    global _EMBED_CACHE
    if _EMBED_CACHE is not None:
        return _EMBED_CACHE
    disk = _load_disk_cache()
    if disk is not None:
        _EMBED_CACHE = disk
        return _EMBED_CACHE

    flat: list[str] = []
    owners: list[str] = []
    for name, examples in TEMPLATE_EXAMPLES.items():
        for ex in examples:
            flat.append(ex)
            owners.append(name)
    vectors = _embed_texts(flat)
    by_name: dict[str, list[list[float]]] = {}
    for name, vec in zip(owners, vectors, strict=True):
        by_name.setdefault(name, []).append(vec)
    cache: dict[str, list[float]] = {}
    for name, vecs in by_name.items():
        dim = len(vecs[0])
        cache[name] = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
    _EMBED_CACHE = cache
    try:
        _save_disk_cache(cache)
    except OSError:
        pass
    return cache


def route_by_embedding(
    question: str,
    threshold: float | None = None,
) -> tuple[str | None, float, list[str]]:
    """Return (template_name|None, score, warnings).

    Requires best cosine >= threshold and margin over 2nd-best (else defer to LLM).
    """
    warnings: list[str] = []
    if not os.getenv("OPENAI_API_KEY"):
        return None, 0.0, warnings
    thresh = threshold if threshold is not None else float(
        os.getenv("OPENAI_EMBED_THRESHOLD", DEFAULT_THRESHOLD)
    )
    margin = float(os.getenv("OPENAI_EMBED_MARGIN", DEFAULT_MARGIN))
    try:
        cache = _ensure_template_cache()
        if _cache_path().exists():
            warnings.append(f"embed_cache={_cache_path()}")
        q_vec = _embed_texts([question])[0]
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"embed_route_error={exc}")
        return None, 0.0, warnings

    scored = sorted(
        ((name, _cosine(q_vec, centroid)) for name, centroid in cache.items()),
        key=lambda x: x[1],
        reverse=True,
    )
    best_name, best_score = scored[0]
    second_name, second_score = scored[1] if len(scored) > 1 else ("", -1.0)
    if best_score < thresh:
        warnings.append(f"embed_below_threshold best={best_name}:{best_score:.3f}")
        return None, best_score, warnings
    if best_score - second_score < margin:
        warnings.append(
            f"embed_ambiguous top={best_name}:{best_score:.3f} "
            f"second={second_name}:{second_score:.3f} margin<{margin}"
        )
        return None, best_score, warnings
    return best_name, best_score, warnings


def offline_example_overlap(question: str) -> tuple[str, float] | None:
    """Cheap offline router: token overlap vs exemplar utterances."""
    q_tokens = set(re.findall(r"[a-z0-9]+", question.casefold()))
    if not q_tokens:
        return None
    best_name = ""
    best = 0.0
    for name, examples in TEMPLATE_EXAMPLES.items():
        ex_tokens: set[str] = set()
        for ex in examples:
            ex_tokens |= set(re.findall(r"[a-z0-9]+", ex.casefold()))
        inter = len(q_tokens & ex_tokens)
        union = len(q_tokens | ex_tokens) or 1
        score = inter / union
        if score > best:
            best = score
            best_name = name
    if best >= 0.18:
        return best_name, best
    return None


def reset_embed_cache(*, wipe_disk: bool = False) -> None:
    global _EMBED_CACHE
    _EMBED_CACHE = None
    if wipe_disk:
        path = _cache_path()
        if path.exists():
            path.unlink()
