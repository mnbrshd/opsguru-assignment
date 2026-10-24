# Spec: CLI / Ask Contract

## Entry points

```bash
python -m app                  # REPL with multi-turn history (/clear resets)
python -m app --rebuild
python -m app --question "..."
python -m app --pipeline-only
python -m app --no-llm         # offline templates + exemplar overlap only

python -m app.api              # POST http://127.0.0.1:8000/ask
```

## Environment

| Var | Required | Purpose |
|-----|----------|---------|
| `OPENAI_API_KEY` | No | Embedding router → LLM → fallback |
| `OPENAI_MODEL` | No | Default `gpt-4o-mini` |
| `OPENAI_EMBED_MODEL` | No | Default `text-embedding-3-small` |
| `OPENAI_EMBED_THRESHOLD` | No | Default `0.72` |
| `OPENAI_EMBED_MARGIN` | No | Min cosine gap vs 2nd intent (default `0.03`) |
| `CLOUDNOVA_EMBED_CACHE` | No | Centroid cache path |
| `CLOUDNOVA_API_KEY` | No | When set, HTTP requires `X-API-Key` or `Authorization: Bearer` |
| `CLOUDNOVA_DB` / `CLOUDNOVA_CSV` | No | Paths |
| `API_HOST` / `API_PORT` | No | Bind for API |

## Ask response shape

```json
{
  "answer": "...",
  "sql": "SELECT ...",
  "rows": [],
  "rows_cited": 0,
  "warnings": [],
  "mode": "embedding" | "llm" | "template" | "error",
  "session_id": "optional"
}
```

## Routing order (with API key)

1. Embedding router (disk-cached centroids; threshold **and** margin over 2nd-best)
2. LLM NL→SQL with optional multi-turn history
3. Offline keyword score + exemplar token overlap

## HTTP `POST /ask`

```json
{
  "question": "...",
  "use_llm": true,
  "history": [{"role":"user","content":"..."},{"role":"assistant","content":"..."}],
  "session_id": "abc",
  "start_session": true
}
```

- Auth: if `CLOUDNOVA_API_KEY` set → `401` without matching key.
- `start_session: true` allocates a `session_id`; subsequent calls with that id reuse server-side history (in-memory).
- `GET /health` is unauthenticated.

## Safety

- Never commit secrets.
- Read-only SQL; LLM path SELECT/WITH only.
- Question max length 2000.
