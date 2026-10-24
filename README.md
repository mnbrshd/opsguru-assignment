# CloudNova — Invoice Q&A (Track B)

Finance handed us a dirty invoice export. This repo turns it into a **cleaned DuckDB model** and a **plain-English ask CLI** that shows the SQL it ran — so answers about revenue, MRR, refunds, and churn are inspectable.

**Track:** Spec-driven data pipeline + NL→SQL (not RAG).

## How to run

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt

# One demo command (builds DB if needed, answers a stakeholder question)
python -m app --question "What was our total recognized revenue in USD for paid invoices in 2024?"

# Interactive REPL
python -m app

# Eval harness (no API key required)
python -m evals.run_eval
```

Optional LLM NL→SQL for off-template questions: copy `.env.example` → `.env` and set `OPENAI_API_KEY`.

## What it does

1. Cleans `data/cloudnova_invoices.csv` (normalize plan/status/billing, parse messy amounts & dates, FX→USD, MRR, dedupe).
2. Loads `data/processed/invoices.duckdb`.
3. Maps natural-language questions to SQL (deterministic templates for the briefing’s six questions; optional OpenAI fallback).
4. Returns **answer + SQL + result rows**.

Architecture: [docs/architecture.md](docs/architecture.md).

## Spec (wrote this first)

| Spec | Purpose |
|------|---------|
| [specs/cleaned_schema.md](specs/cleaned_schema.md) | Canonical schema, maps, FX, MRR, dedup, dates |
| [specs/api_cli.md](specs/api_cli.md) | CLI contract & response shape |
| [specs/eval_spec.md](specs/eval_spec.md) | Eval harness rules |

AI steering artifacts: [`.cursor/rules/`](.cursor/rules/), [docs/ai-session-notes.md](docs/ai-session-notes.md).

## Design decisions

- **DuckDB + pandas** — local, fast, SQL-native; no infra to babysit in a 1-hour build.
- **Templates first** — stakeholder questions are aggregations; regex templates are honest and CI-friendly. LLM is a bonus path, not a dependency.
- **Dedup priority** `paid > refunded > pending > failed > void` — when source systems disagree on the same `invoice_id`, prefer rows that reflect money movement.
- **Ambiguous dates** (`05-01-2024`) → **day-first**; disclosed below.
- **Recognized revenue** = `paid` + `refunded` (refunds are negative and net out).

## Known limits / failure modes

- Template matcher is keyword-based; paraphrases may miss unless `OPENAI_API_KEY` is set.
- Day-first date choice can mis-bucket ambiguous rows; on this extract, 2024 totals matched a month-first alternate, but that is **not** a guarantee.
- Near-dup survivors depend on status priority — a different rule changes revenue.
- Account-level churn treats each (account, plan) pair; multi-plan history is simplified.
- Eval case `naive_paid_only_ignores_refunds` is an **expected fail**: counting only `status='paid'` overstates 2024 revenue by ignoring refund nets (~\$28.1M vs ~\$26.3M).

## Another day

- Better intent routing; parser property tests; near-dup lineage table; thin `POST /ask` API; public repo / reviewer invites for submission.

## License / data

Fictional CloudNova dataset for the OpsGuru FDE take-home. Not production customer data.
