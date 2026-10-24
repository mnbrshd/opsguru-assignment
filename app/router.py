"""Embedding intent router (OpenAI) with in-memory cache of template exemplars."""

from __future__ import annotations

import math
import os
from typing import Any

# Exemplar utterances per template name (used for embedding similarity)
TEMPLATE_EXAMPLES: dict[str, list[str]] = {
    "revenue_2024": [
        "What was our total recognized revenue in USD for paid invoices in 2024?",
        "How much recognized revenue did we book in 2024?",
        "Total paid revenue 2024 including refunds",
    ],
    "region_avg_mrr": [
        "Which region has the highest average MRR per account?",
        "Which region has the best average MRR?",
        "Region with highest avg MRR",
    ],
    "refunds": [
        "How much have we given back in refunds?",
        "Total refunds in USD",
        "How much money was refunded?",
    ],
    "churn_by_plan": [
        "What's the churn rate among Enterprise accounts vs Starter?",
        "Compare churn for enterprise and starter",
        "Enterprise vs starter churn rate",
    ],
    "top5_revenue_csat": [
        "List the top 5 accounts by revenue, and flag any with CSAT ≤ 2.",
        "Top five accounts by revenue with low CSAT",
        "Highest revenue accounts and CSAT flags",
    ],
    "pending_failed_exposure": [
        "How many invoices are stuck in pending/failed and what's the exposed $?",
        "Pending and failed invoice exposure",
        "How much is stuck in pending or failed?",
    ],
}

_EMBED_CACHE: dict[str, list[float]] | None = None
DEFAULT_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_THRESHOLD = 0.72


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
    # API returns in input order
    return [item.embedding for item in sorted(resp.data, key=lambda d: d.index)]


def _ensure_template_cache() -> dict[str, list[float]]:
    global _EMBED_CACHE
    if _EMBED_CACHE is not None:
        return _EMBED_CACHE
    flat: list[str] = []
    owners: list[str] = []
    for name, examples in TEMPLATE_EXAMPLES.items():
        for ex in examples:
            flat.append(ex)
            owners.append(name)
    vectors = _embed_texts(flat)
    # centroid per template
    by_name: dict[str, list[list[float]]] = {}
    for name, vec in zip(owners, vectors, strict=True):
        by_name.setdefault(name, []).append(vec)
    cache: dict[str, list[float]] = {}
    for name, vecs in by_name.items():
        dim = len(vecs[0])
        centroid = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
        cache[name] = centroid
    _EMBED_CACHE = cache
    return cache


def route_by_embedding(
    question: str,
    threshold: float | None = None,
) -> tuple[str, float] | None:
    """Return (template_name, score) if best cosine >= threshold."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    thresh = threshold if threshold is not None else float(
        os.getenv("OPENAI_EMBED_THRESHOLD", DEFAULT_THRESHOLD)
    )
    try:
        cache = _ensure_template_cache()
        q_vec = _embed_texts([question])[0]
    except Exception:
        return None
    best_name = ""
    best_score = -1.0
    for name, centroid in cache.items():
        score = _cosine(q_vec, centroid)
        if score > best_score:
            best_score = score
            best_name = name
    if best_score >= thresh:
        return best_name, best_score
    return None


def reset_embed_cache() -> None:
    global _EMBED_CACHE
    _EMBED_CACHE = None
