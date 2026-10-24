"""Run eval cases against DuckDB. No LLM required."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import duckdb
import yaml

from app.pipeline import DEFAULT_CSV, DEFAULT_DB, run_pipeline

CASES_PATH = Path(__file__).with_name("cases.yaml")


def _ensure_db(rebuild: bool) -> None:
    if rebuild or not DEFAULT_DB.exists():
        print(f"Building DB → {DEFAULT_DB}", file=sys.stderr)
        run_pipeline(DEFAULT_CSV, DEFAULT_DB)


def _fetch(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _close(a: float, b: float, tol: float) -> bool:
    return abs(float(a) - float(b)) <= tol


def check_case(rows: list[dict[str, Any]], expect: dict[str, Any]) -> tuple[bool, str]:
    etype = expect["type"]
    if not rows and etype != "row_count":
        return False, "no rows returned"

    if etype == "scalar_float":
        col = expect["column"]
        got = rows[0].get(col)
        exp = expect["value"]
        tol = float(expect.get("tolerance_abs", 1.0))
        if got is None:
            return False, f"{col} is null"
        ok = _close(got, exp, tol)
        return ok, f"got {got} expected {exp} ±{tol}"

    if etype == "scalar_str":
        col = expect["column"]
        got = rows[0].get(col)
        exp = expect["value"]
        ok = str(got) == str(exp)
        return ok, f"got {got!r} expected {exp!r}"

    if etype == "keyed_floats":
        key_col = expect["key_column"]
        val_col = expect["value_column"]
        tol = float(expect.get("tolerance_abs", 0.05))
        by_key = {str(r[key_col]): r[val_col] for r in rows}
        for k, exp in expect["values"].items():
            if k not in by_key:
                return False, f"missing key {k}"
            if not _close(by_key[k], exp, tol):
                return False, f"{k}: got {by_key[k]} expected {exp} ±{tol}"
        return True, "keyed floats ok"

    if etype == "top_n_accounts":
        col = expect["column"]
        got = [str(r[col]) for r in rows]
        exp = [str(x) for x in expect["values"]]
        if got != exp:
            return False, f"order got {got} expected {exp}"
        low = expect.get("low_csat_account")
        if low:
            match = next((r for r in rows if str(r[col]) == low), None)
            if not match or not match.get("low_csat_flag"):
                return False, f"expected low_csat_flag on {low}"
        return True, "top_n ok"

    if etype == "multi_scalar":
        tol = float(expect.get("tolerance_abs", 1.0))
        row = rows[0]
        for k, exp in expect["values"].items():
            got = row.get(k)
            if isinstance(exp, float):
                if not _close(got, exp, tol):
                    return False, f"{k}: got {got} expected {exp}"
            elif int(got) != int(exp):
                return False, f"{k}: got {got} expected {exp}"
        return True, "multi_scalar ok"

    return False, f"unknown expect type {etype}"


def run(rebuild: bool = False, cases_path: Path = CASES_PATH) -> int:
    _ensure_db(rebuild)
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    con = duckdb.connect(str(DEFAULT_DB), read_only=True)

    passed = failed = xfailed = xpass = 0
    try:
        for case in cases:
            cid = case["id"]
            rows = _fetch(con, case["sql"])
            ok, detail = check_case(rows, case["expect"])
            expect_fail = bool(case.get("expected_fail"))

            if expect_fail:
                if ok:
                    xpass += 1
                    status = "XPASS"
                else:
                    xfailed += 1
                    status = "XFAIL"
            else:
                if ok:
                    passed += 1
                    status = "PASS"
                else:
                    failed += 1
                    status = "FAIL"

            print(f"{status:5}  {cid}  ({detail})")
            if case.get("notes") and status in {"FAIL", "XFAIL", "XPASS"}:
                print(f"       note: {case['notes'][:120]}")
    finally:
        con.close()

    print(
        f"\nSummary: pass={passed} fail={failed} xfail={xfailed} xpass={xpass}"
    )
    if failed or xpass:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CloudNova eval harness")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args(argv)
    return run(rebuild=args.rebuild)


if __name__ == "__main__":
    raise SystemExit(main())
