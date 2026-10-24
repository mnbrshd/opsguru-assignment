"""NL → SQL over cleaned invoices (templates + optional LLM)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

DEFAULT_DB = Path("data/processed/invoices.duckdb")

# Stakeholder-aligned deterministic SQL (specs/eval_spec.md)
TEMPLATES: list[tuple[str, re.Pattern[str], str, str]] = [
    (
        "revenue_2024",
        re.compile(
            r"(total|recognized).*(revenue)|revenue.*(2024|paid)",
            re.I,
        ),
        """
SELECT ROUND(COALESCE(SUM(amount_usd), 0), 2) AS total_revenue_usd
FROM invoices
WHERE is_recognized_revenue
  AND invoice_date >= DATE '2024-01-01'
  AND invoice_date < DATE '2025-01-01'
""".strip(),
        "Total recognized revenue (paid + refund nets) for invoices dated in 2024.",
    ),
    (
        "region_avg_mrr",
        re.compile(r"(region).*(mrr|highest)|highest.*(average|avg).*mrr|avg.*mrr.*region", re.I),
        """
WITH account_mrr AS (
  SELECT region, account_id, AVG(mrr_usd) AS account_mrr
  FROM invoices
  WHERE mrr_usd IS NOT NULL AND region IS NOT NULL
  GROUP BY region, account_id
)
SELECT region, ROUND(AVG(account_mrr), 2) AS avg_mrr_per_account
FROM account_mrr
GROUP BY region
ORDER BY avg_mrr_per_account DESC
LIMIT 1
""".strip(),
        "Region with the highest average MRR per account.",
    ),
    (
        "refunds",
        re.compile(r"refund", re.I),
        """
SELECT ROUND(COALESCE(SUM(ABS(amount_usd)), 0), 2) AS refunds_usd
FROM invoices
WHERE status = 'refunded'
""".strip(),
        "Total absolute USD given back in refunds.",
    ),
    (
        "churn_by_plan",
        re.compile(r"churn", re.I),
        """
WITH accounts AS (
  SELECT account_id, plan, MAX(CASE WHEN churned THEN 1 ELSE 0 END) AS is_churned
  FROM invoices
  WHERE plan IN ('enterprise', 'starter')
  GROUP BY account_id, plan
)
SELECT
  plan,
  COUNT(*) AS accounts,
  SUM(is_churned) AS churned_accounts,
  ROUND(100.0 * SUM(is_churned) / NULLIF(COUNT(*), 0), 2) AS churn_rate_pct
FROM accounts
GROUP BY plan
ORDER BY plan
""".strip(),
        "Churn rate among Enterprise vs Starter accounts (account-level).",
    ),
    (
        "top5_revenue_csat",
        re.compile(r"top\s*5|top five|highest.*(account|revenue)", re.I),
        """
WITH rev AS (
  SELECT
    account_id,
    ANY_VALUE(account_name) AS account_name,
    ROUND(SUM(amount_usd), 2) AS revenue_usd,
    MIN(csat_score) AS csat_score
  FROM invoices
  WHERE is_recognized_revenue
  GROUP BY account_id
)
SELECT
  account_id,
  account_name,
  revenue_usd,
  csat_score,
  (csat_score IS NOT NULL AND csat_score <= 2) AS low_csat_flag
FROM rev
ORDER BY revenue_usd DESC
LIMIT 5
""".strip(),
        "Top 5 accounts by recognized revenue, with CSAT ≤ 2 flag.",
    ),
    (
        "pending_failed_exposure",
        re.compile(r"pending|failed|stuck|exposed", re.I),
        """
SELECT
  COUNT(*) AS invoice_count,
  ROUND(COALESCE(SUM(amount_usd), 0), 2) AS exposed_usd
FROM invoices
WHERE status IN ('pending', 'failed')
""".strip(),
        "Count and exposed USD of pending/failed invoices.",
    ),
]


@dataclass
class AskResult:
    answer: str
    sql: str
    rows: list[dict[str, Any]]
    rows_cited: int
    warnings: list[str]
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "sql": self.sql,
            "rows": self.rows,
            "rows_cited": self.rows_cited,
            "warnings": self.warnings,
            "mode": self.mode,
        }


def _match_template(question: str) -> tuple[str, str, str] | None:
    # Prefer more specific templates: score by pattern specificity order as listed,
    # but require refund before revenue if both somehow match — order in TEMPLATES matters.
    for name, pattern, sql, blurb in TEMPLATES:
        if pattern.search(question):
            return name, sql, blurb
    return None


def _is_safe_select(sql: str) -> bool:
    cleaned = sql.strip().rstrip(";")
    if ";" in cleaned:
        return False
    lowered = cleaned.casefold()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False
    banned = [
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "alter ",
        "attach ",
        "copy ",
        "create ",
        "pragma ",
        "install ",
        "load ",
    ]
    return not any(b in lowered for b in banned)


def _format_answer(blurb: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return f"{blurb} No rows returned."
    if len(rows) == 1 and len(rows[0]) <= 3:
        parts = [f"{k}={v}" for k, v in rows[0].items()]
        return f"{blurb} " + ", ".join(parts)
    return f"{blurb} Returned {len(rows)} row(s); see `rows` / SQL."


def execute_sql(db_path: Path, sql: str, limit_display: int = 50) -> list[dict[str, Any]]:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        cur = con.execute(sql)
        cols = [c[0] for c in cur.description]
        raw = cur.fetchall()
        rows = [dict(zip(cols, r)) for r in raw]
        # stringify dates etc.
        out: list[dict[str, Any]] = []
        for row in rows[:limit_display]:
            out.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()})
        return out if len(rows) <= limit_display else out
    finally:
        con.close()


def _llm_sql(question: str) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, ["OPENAI_API_KEY not set; LLM path unavailable"]

    try:
        from openai import OpenAI
    except ImportError:
        return None, ["openai package not installed"]

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    base_url = os.getenv("OPENAI_BASE_URL")
    client_kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    system = """You write DuckDB SQL for table `invoices` with columns:
invoice_id, account_id, account_name, contact_email, region, industry, plan,
billing_cycle, seats, currency, amount, amount_usd, discount_pct, status,
payment_method, signup_date, invoice_date, churned, csat_score, support_tickets,
list_price_usd, mrr_usd, is_recognized_revenue, raw_plan, raw_status.

Rules:
- Recognized revenue: is_recognized_revenue OR status IN ('paid','refunded')
- MRR is mrr_usd (already derived); do not divide annual amounts
- plan in starter|pro|enterprise; status in paid|pending|failed|refunded|void|unknown
- Return ONLY a single SELECT or WITH...SELECT. No markdown fences.
"""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"^```sql\s*|\s*```$", "", text, flags=re.I | re.M).strip()
        if not _is_safe_select(text):
            return None, ["LLM SQL failed safety check"]
        return text, warnings
    except Exception as exc:  # noqa: BLE001 — surface to caller as warning
        return None, [f"LLM error: {exc}"]


def ask(question: str, db_path: Path | str = DEFAULT_DB, use_llm: bool = True) -> AskResult:
    db_path = Path(db_path)
    warnings: list[str] = []

    if not db_path.exists():
        return AskResult(
            answer="Database missing. Run `python -m app --pipeline-only` first.",
            sql="",
            rows=[],
            rows_cited=0,
            warnings=["db_missing"],
            mode="error",
        )

    matched = _match_template(question)
    sql = ""
    mode = "template"
    blurb = "Query result."

    if matched:
        _name, sql, blurb = matched
    elif use_llm:
        llm_sql, w = _llm_sql(question)
        warnings.extend(w)
        if llm_sql:
            sql = llm_sql
            mode = "llm"
            blurb = "LLM-generated SQL result."
        else:
            return AskResult(
                answer="Could not match a known question template and LLM SQL unavailable.",
                sql="",
                rows=[],
                rows_cited=0,
                warnings=warnings or ["no_match"],
                mode="error",
            )
    else:
        return AskResult(
            answer="No template match. Set OPENAI_API_KEY for LLM NL→SQL, or rephrase.",
            sql="",
            rows=[],
            rows_cited=0,
            warnings=["no_template_match"],
            mode="error",
        )

    if not _is_safe_select(sql):
        return AskResult(
            answer="Refusing to run unsafe SQL.",
            sql=sql,
            rows=[],
            rows_cited=0,
            warnings=["unsafe_sql"],
            mode="error",
        )

    try:
        rows = execute_sql(db_path, sql)
        # recount without display cap
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            full = con.execute(sql).fetchall()
            cited = len(full)
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return AskResult(
            answer=f"SQL execution failed: {exc}",
            sql=sql,
            rows=[],
            rows_cited=0,
            warnings=warnings + ["exec_error"],
            mode=mode,
        )

    return AskResult(
        answer=_format_answer(blurb, rows),
        sql=sql,
        rows=rows,
        rows_cited=cited,
        warnings=warnings,
        mode=mode,
    )
