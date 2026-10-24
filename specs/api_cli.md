# Spec: CLI / Ask Contract

## Entry point

```bash
python -m app                  # ensure DB built, then interactive REPL
python -m app --rebuild        # force re-run pipeline from CSV
python -m app --question "..." # one-shot ask, then exit
python -m app --pipeline-only  # clean + load DuckDB, no ask
```

## Environment

| Var | Required | Purpose |
|-----|----------|---------|
| `OPENAI_API_KEY` | No | Enables LLM NL→SQL; without it, template matcher only |
| `OPENAI_MODEL` | No | Default `gpt-4o-mini` |
| `OPENAI_BASE_URL` | No | Optional OpenAI-compatible base URL |
| `CLOUDNOVA_DB` | No | DuckDB path (default `data/processed/invoices.duckdb`) |
| `CLOUDNOVA_CSV` | No | Raw CSV path (default `data/cloudnova_invoices.csv`) |

Secrets live in `.env` (gitignored). Ship `.env.example` only.

## Ask response shape

Every ask returns a JSON-serializable dict (pretty-printed to stdout):

```json
{
  "answer": "Human-readable summary string",
  "sql": "SELECT ...",
  "rows": [ { "...": "..." } ],
  "rows_cited": 12,
  "warnings": ["optional notes"],
  "mode": "template" | "llm"
}
```

- `sql` is always shown (assignment: generated query visible).
- `rows` is the result set (capped at 50 rows in CLI display; full count in `rows_cited`).
- On failure: non-zero exit, `answer` explains error, `sql` may be empty.

## Query modes

1. **Template** — keyword/intent match against the six stakeholder questions in `BUSINESS_CONTEXT.md`. Deterministic SQL. Used by evals and when no API key.
2. **LLM** — when `OPENAI_API_KEY` is set and template confidence is low: model returns SQL only against table `invoices` with the cleaned schema. Guardrails:
   - Allow `SELECT` / `WITH` only
   - Reject `;` multi-statement, `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ATTACH`/`COPY`
   - Timeout / empty result → clear warning

## Safety

- Never log or commit API keys.
- Read-only SQL against the local DuckDB file.
