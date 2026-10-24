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
| [`evals/`](evals/) + [`tests/`](tests/) | Business evals + parser property tests |

## How to run

Needs **Python 3.11+**. First ask rebuilds DuckDB from the CSV (~few seconds).

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# One demo command (builds DB if needed, answers a stakeholder question)
python -m app --question "What was our total recognized revenue in USD for paid invoices in 2024?"

# Interactive REPL
python -m app

# Thin API
python -m app.api
# curl -s -X POST http://127.0.0.1:8000/ask -H "Content-Type: application/json" \
#   -d "{\"question\":\"How much have we given back in refunds?\",\"use_llm\":false}"

# Eval harness + property tests (no API key required)
python -m evals.run_eval
python -m pytest tests/ -q
```

You should see **6 PASS + 1 XFAIL** from the eval harness (the XFAIL is intentional — see limits below).

With `OPENAI_API_KEY` set (copy `.env.example` → `.env`), ask defaults to **embedding router → LLM SQL → template fallback**. Offline / CI use scored templates (`--no-llm` or empty key).

## What it does

1. Cleans `data/cloudnova_invoices.csv` (normalize plan/status/billing, parse messy amounts & dates, FX→USD, MRR, dedupe).
2. Loads `data/processed/invoices.duckdb` (gitignored; rebuilt locally / in CI).
3. Routes NL questions (embeddings when keyed; else scored templates) and returns **answer + SQL + result rows**.
4. Optional `POST /ask` on a local FastAPI server.

## Spec (wrote this first)

| Spec | Purpose |
|------|---------|
| [specs/cleaned_schema.md](specs/cleaned_schema.md) | Canonical schema, maps, FX, MRR, dedup, dates |
| [specs/api_cli.md](specs/api_cli.md) | CLI + HTTP contract & response shape |
| [specs/eval_spec.md](specs/eval_spec.md) | Eval harness rules |

## Design decisions

- **DuckDB + pandas** — local, fast, SQL-native; no infra to babysit in a 1-hour build.
- **Embedding/LLM default when keyed** — cosine route to trusted template SQL first; LLM only on miss; templates keep CI offline.
- **Dedup priority** `paid > refunded > pending > failed > void` — when source systems disagree on the same `invoice_id`, prefer rows that reflect money movement.
- **Ambiguous dates** (`05-01-2024`) → **day-first** canonical + month-first alt column.
- **Recognized revenue** = `paid` + `refunded` (refunds are negative and net out).

## Known limits / failure modes

- Without an API key, routing is scored keywords only — odd paraphrases can still miss.
- Embedding threshold (`OPENAI_EMBED_THRESHOLD`, default 0.72) can mis-route near the boundary; LLM then tries free-form SQL under SELECT-only guardrails.
- **Ambiguous dates** emit `date_sensitivity` warnings on revenue asks; day-first remains canonical.
- **Near-dups** use status priority; losers in `invoice_dedup_dropped`. A different priority would change revenue.
- **Churn** is one account → plan on the latest `invoice_date`.
- Eval case `naive_paid_only_ignores_refunds` is an **intentional XFAIL**: paid-only SQL overstates 2024 revenue (~\$28.1M vs ~\$26.3M).

## Another day

- Auth on the API; caching for embedding centroids on disk; richer multi-turn agent.

## License / data

Fictional CloudNova dataset for the OpsGuru FDE take-home. Not production customer data.
