# CloudNova — Invoice Q&A (Track B)

Finance handed us a dirty invoice export. This repo turns it into a **cleaned DuckDB model** and a **plain-English ask CLI** (plus thin HTTP API) that shows the SQL it ran — so answers about revenue, MRR, refunds, and churn are inspectable.

**Track:** Spec-driven data pipeline + NL→SQL (not RAG).  
**Repo:** [github.com/mnbrshd/opsguru-assignment](https://github.com/mnbrshd/opsguru-assignment) · CI runs property tests + `python -m evals.run_eval` on every push to `main`.

### Reviewer map (3 minutes)

| Look here | Why |
|-----------|-----|
| [`/specs`](specs/) | Written **before** code — schema, CLI, eval contracts |
| [`docs/architecture.md`](docs/architecture.md) | Raw CSV → clean → DuckDB → router / ask / API / evals |
| [`.cursor/rules/`](.cursor/rules/) + [`docs/ai-session-notes.md`](docs/ai-session-notes.md) | How Cursor was steered |
| [`evals/`](evals/) + [`tests/`](tests/) | Business evals + parser/router/API tests |

## How to run

Needs **Python 3.11+**. First ask rebuilds DuckDB from the CSV (~few seconds).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# One demo command
python -m app --question "What was our total recognized revenue in USD for paid invoices in 2024?"

# Interactive REPL (keeps multi-turn history; /clear to reset)
python -m app

# Thin API (optional auth via CLOUDNOVA_API_KEY)
python -m app.api
# curl -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
#   -d "{\"question\":\"How much have we given back in refunds?\",\"use_llm\":false}"

# Eval harness + unit/property tests (no API key required)
python -m evals.run_eval
python -m pytest tests/ -q
```

You should see **6 PASS + 1 XFAIL** from the eval harness (the XFAIL is intentional — see limits below).

With `OPENAI_API_KEY` set (copy `.env.example` → `.env`), ask defaults to **embedding router (disk-cached centroids, threshold + margin) → LLM SQL (multi-turn aware) → template/overlap fallback**. Offline / CI use scored templates + exemplar token overlap (`--no-llm` or empty key).

## What it does

1. Cleans `data/cloudnova_invoices.csv` (normalize plan/status/billing, parse messy amounts & dates, FX→USD, MRR, dedupe).
2. Loads `data/processed/invoices.duckdb` (gitignored; rebuilt locally / in CI).
3. Routes NL questions and returns **answer + SQL + result rows**.
4. Optional `POST /ask` with API-key auth, sessions (`start_session` / `session_id`), and history.

## Spec (wrote this first)

| Spec | Purpose |
|------|---------|
| [specs/cleaned_schema.md](specs/cleaned_schema.md) | Canonical schema, maps, FX, MRR, dedup, dates |
| [specs/api_cli.md](specs/api_cli.md) | CLI + HTTP contract & response shape |
| [specs/eval_spec.md](specs/eval_spec.md) | Eval harness rules |

## Design decisions

- **DuckDB + pandas** — local, fast, SQL-native.
- **Embedding/LLM default when keyed** — cosine route to trusted template SQL first (with margin guard); LLM on miss; templates/overlap keep CI offline.
- **On-disk embed cache** — `data/processed/embed_centroids.json` keyed by exemplar fingerprint (avoids re-embedding exemplars every process start).
- **Dedup priority** `paid > refunded > pending > failed > void`; losers in `invoice_dedup_dropped`.
- **Ambiguous dates** → day-first canonical + month-first alt; revenue asks emit sensitivity warnings.
- **Recognized revenue** = `paid` + `refunded` (refunds net out).

## Known limits / failure modes

- Offline routing is still heuristic (keywords + exemplar overlap), not full NLU — very odd paraphrases can miss without an API key.
- Embedding **threshold/margin** may defer to LLM near ambiguous intents (by design); LLM SQL is SELECT-only guarded but not perfect.
- Day-first remains the canonical date choice; month-first is for sensitivity, not a second source of truth.
- Near-dup survivor priority is a product rule — changing it changes revenue.
- Churn uses latest-invoice plan per account.
- Eval case `naive_paid_only_ignores_refunds` is an **intentional XFAIL** (~\$28.1M vs ~\$26.3M).
- API sessions are **in-memory** (process-local); set `CLOUDNOVA_API_KEY` before any networked use.

## License / data

Fictional CloudNova dataset for the OpsGuru FDE take-home. Not production customer data.
