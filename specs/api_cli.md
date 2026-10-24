# Spec: CLI / Ask Contract

## Entry points

```bash
python -m app                  # ensure DB built, then interactive REPL
python -m app --rebuild        # force re-run pipeline from CSV
python -m app --question "..." # one-shot ask, then exit
python -m app --pipeline-only  # clean + load DuckDB, no ask
python -m app --no-llm         # force offline scored templates (no embed/LLM)

# Thin HTTP API
python -m app.api              # POST http://127.0.0.1:8000/ask
```

## Environment

| Var | Required | Purpose |
|-----|----------|---------|
| `OPENAI_API_KEY` | No | Default path: embedding router → LLM SQL → template fallback |
| `OPENAI_MODEL` | No | Chat model (default `gpt-4o-mini`) |
| `OPENAI_EMBED_MODEL` | No | Embedding model (default `text-embedding-3-small`) |
| `OPENAI_EMBED_THRESHOLD` | No | Cosine cutoff (default `0.72`) |
| `OPENAI_BASE_URL` | No | Optional OpenAI-compatible base URL |
| `CLOUDNOVA_DB` | No | DuckDB path (default `data/processed/invoices.duckdb`) |
| `CLOUDNOVA_CSV` | No | Raw CSV path (default `data/cloudnova_invoices.csv`) |
| `API_HOST` / `API_PORT` | No | Bind for `python -m app.api` |

Secrets live in `.env` (gitignored). Ship `.env.example` only.

## Ask response shape

```json
{
  "answer": "Human-readable summary string",
  "sql": "SELECT ...",
  "rows": [ { "...": "..." } ],
  "rows_cited": 12,
  "warnings": ["optional notes"],
  "mode": "embedding" | "llm" | "template" | "error"
}
```

## Query modes (default order with API key)

1. **Embedding router** — cosine similarity of the question to exemplar utterances per stakeholder intent; on hit, run that template’s trusted SQL (`mode=embedding`).
2. **LLM NL→SQL** — if embedding confidence is low; `SELECT`/`WITH` only, safety guardrails.
3. **Scored templates** — offline keyword/synonym scorer (also the only path without an API key / with `--no-llm`).

Evals and CI use fixed SQL in `evals/cases.yaml` — they do not call the live router.

## HTTP: `POST /ask`

Request:

```json
{ "question": "...", "use_llm": true }
```

Response: same ask shape. `422` when routing fails with empty SQL. `GET /health` → `{"status":"ok"}`.

## Safety

- Never log or commit API keys.
- Read-only SQL against the local DuckDB file.
- Request `question` max length 2000.
