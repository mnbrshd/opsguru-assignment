"""CLI: python -m app"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.pipeline import DEFAULT_CSV, DEFAULT_DB, run_pipeline
from app.query_agent import ask


def _ensure_db(csv_path: Path, db_path: Path, rebuild: bool) -> dict | None:
    if rebuild or not db_path.exists():
        print(f"Building DuckDB from {csv_path} → {db_path}", file=sys.stderr)
        stats = run_pipeline(csv_path, db_path)
        keys = (
            "input_rows",
            "after_exact_dedup",
            "output_rows",
            "near_dups_dropped",
            "ambiguous_invoice_dates",
            "unknown_plan",
            "unknown_status",
        )
        print(json.dumps({k: stats[k] for k in keys}, indent=2), file=sys.stderr)
        return stats
    return None


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="CloudNova invoice pipeline + NL ask")
    parser.add_argument("--rebuild", action="store_true", help="Force re-run cleaning pipeline")
    parser.add_argument("--pipeline-only", action="store_true", help="Only build DuckDB")
    parser.add_argument("--question", "-q", type=str, help="One-shot natural language question")
    parser.add_argument("--csv", type=Path, default=Path(os.getenv("CLOUDNOVA_CSV", DEFAULT_CSV)))
    parser.add_argument("--db", type=Path, default=Path(os.getenv("CLOUDNOVA_DB", DEFAULT_DB)))
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM fallback")
    args = parser.parse_args(argv)

    _ensure_db(args.csv, args.db, args.rebuild)
    if args.pipeline_only:
        return 0

    if args.question:
        result = ask(args.question, db_path=args.db, use_llm=not args.no_llm)
        print(json.dumps(result.to_dict(), indent=2, default=str))
        return 0 if result.mode != "error" else 1

    print("CloudNova ask (empty line or 'quit' to exit). Templates cover stakeholder questions.", file=sys.stderr)
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(file=sys.stderr)
            break
        if not q or q.casefold() in {"quit", "exit", "q"}:
            break
        result = ask(q, db_path=args.db, use_llm=not args.no_llm)
        print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
