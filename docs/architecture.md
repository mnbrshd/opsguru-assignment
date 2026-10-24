# Architecture

```mermaid
flowchart LR
  rawCsv["data/cloudnova_invoices.csv"] --> clean["app/pipeline.py"]
  spec["specs/cleaned_schema.md"] --> clean
  clean --> duck["data/processed/invoices.duckdb"]
  duck --> ask["app/query_agent.py"]
  router["app/router.py embed + disk cache"] --> ask
  ask --> out["answer + SQL + rows"]
  ask --> api["POST /ask + API key + sessions"]
  evals["evals/cases.yaml"] --> harness["evals/run_eval.py"]
  duck --> harness
  tests["tests/"] --> pytest["pytest"]
```

## Ask routing

1. **Embedding** (if keyed) — cosine vs cached template centroids; require threshold + margin.
2. **LLM SQL** — optional multi-turn history from REPL / API session.
3. **Offline** — keyword scores + exemplar token overlap.

## Trust boundaries

- Cleaned DuckDB is the only query surface.
- HTTP auth optional via `CLOUDNOVA_API_KEY`.
- Sessions are process-local memory (demo-grade).
