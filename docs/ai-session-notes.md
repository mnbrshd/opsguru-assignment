# AI session notes (trimmed)

This file is the assignment’s “how we steered the AI” artifact for Cursor.
It is curated — not a raw transcript dump.

## Tooling

- **Editor / agent:** Cursor (Composer / agent mode)
- **Steering committed in-repo:** `.cursor/rules/cloudnova-track-b.mdc`, `/specs/*`
- **Host:** GitHub `mnbrshd/opsguru-assignment`

## Session arc

1. **Repo bootstrap** — Local git init, identity for commit, GitHub CLI install + device login, private repo create + push.
2. **Track choice** — Agent recommended Track B (aggregation-heavy stakeholder questions). Human confirmed Track B and asked whether Cursor config/prompt history goes to GitHub. Answer: yes for **curated** rules + specs + this notes file; no for secrets / full private agent stores.
3. **Plan then build** — Specs written **before** `app/` code (`cleaned_schema`, `api_cli`, `eval_spec`). Pipeline, query agent, evals, README/CI followed that order.

## Prompts / direction that mattered

- “Implement the plan as specified… mark todos… don’t stop until complete.”
- Spec-first constraint: normalize maps, FX, MRR formula, dedup priority, day-first ambiguous dates — all from `BUSINESS_CONTEXT.md` into `specs/cleaned_schema.md` before pandas code.
- Eval must run **without** an API key (CI); LLM path optional.

## Human overrides / judgment calls

| Topic | Decision | Why |
|-------|----------|-----|
| Track | B over A | Revenue/MRR/churn are SQL aggregations; RAG would fail the bar |
| Dedup | `paid > refunded > pending > failed > void` | Prefer recognizing money movement over void/pending when systems disagree |
| Ambiguous `DD-MM`/`MM-DD` | Day-first | Spec’d explicitly; README discloses risk |
| Recognized revenue | `paid` + `refunded` (negatives net) | Per business briefing |
| NL→SQL | Templates for 6 stakeholder Qs; OpenAI optional | Demo + CI work offline |
| Expected-fail eval | Paid-only SQL vs recognized revenue | Shows refund-netting failure mode clearly (month-first vs day-first 2024 totals happened to match on this file) |

## What we told the model *not* to do

- No RAG/embeddings for this track
- No committing `.env` / keys
- No gold-plated UI or cloud deploy
- Do not silently change list prices / FX / MRR definition

## Follow-up hardening (post-first-pass)

Addressed documented limits without gold-plating:
- Scored synonym template matcher (offline paraphrases)
- `invoice_date_month_first` + revenue `date_sensitivity` warnings
- `invoice_dedup_dropped` lineage table
- Churn = one account / latest-plan grain

## Follow-ups for another day

- Embedding/LLM router as default
- Property tests on amount/date parsers
- Thin `POST /ask` API
