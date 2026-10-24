"""NL → SQL over cleaned invoices (scored templates + optional LLM)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

DEFAULT_DB = Path("data/processed/invoices.duckdb")

# Stakeholder SQL + keyword weights for paraphrase-tolerant matching
TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "revenue_2024",
        "sql": """
SELECT ROUND(COALESCE(SUM(amount_usd), 0), 2) AS total_revenue_usd
FROM invoices
WHERE is_recognized_revenue
  AND invoice_date >= DATE '2024-01-01'
  AND invoice_date < DATE '2025-01-01'
""".strip(),
        "blurb": "Total recognized revenue (paid + refund nets) for invoices dated in 2024 (day-first dates).",
        "positive": [
            ("recognized revenue", 5),
            ("total revenue", 4),
            ("revenue", 3),
            ("2024", 3),
            ("how much did we make", 4),
            ("bookings", 2),
        ],
        "negative": [("refund", 4), ("churn", 4), ("mrr", 3), ("top 5", 4), ("pending", 3), ("failed", 3)],
    },
    {
        "name": "region_avg_mrr",
        "sql": """
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
        "blurb": "Region with the highest average MRR per account.",
        "positive": [
            ("mrr", 4),
            ("region", 3),
            ("highest average", 3),
            ("avg mrr", 4),
            ("which region", 3),
        ],
        "negative": [("revenue", 2), ("refund", 3), ("churn", 3), ("pending", 2)],
    },
    {
        "name": "refunds",
        "sql": """
SELECT ROUND(COALESCE(SUM(ABS(amount_usd)), 0), 2) AS refunds_usd
FROM invoices
WHERE status = 'refunded'
""".strip(),
        "blurb": "Total absolute USD given back in refunds.",
        "positive": [("refund", 5), ("given back", 3), ("chargeback", 4), ("money back", 3)],
        "negative": [("recognized revenue", 3), ("churn", 2), ("pending", 2)],
    },
    {
        "name": "churn_by_plan",
        "sql": """
WITH latest AS (
  SELECT
    account_id,
    plan,
    churned,
    ROW_NUMBER() OVER (
      PARTITION BY account_id
      ORDER BY invoice_date DESC NULLS LAST, invoice_id
    ) AS rn
  FROM invoices
)
SELECT
  plan,
  COUNT(*) AS accounts,
  SUM(CASE WHEN churned THEN 1 ELSE 0 END) AS churned_accounts,
  ROUND(100.0 * SUM(CASE WHEN churned THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS churn_rate_pct
FROM latest
WHERE rn = 1 AND plan IN ('enterprise', 'starter')
GROUP BY plan
ORDER BY plan
""".strip(),
        "blurb": "Churn rate among Enterprise vs Starter (one row per account; plan = latest invoice).",
        "positive": [("churn", 5), ("enterprise", 2), ("starter", 2), ("churn rate", 5)],
        "negative": [("revenue", 2), ("refund", 2), ("mrr", 2)],
    },
    {
        "name": "top5_revenue_csat",
        "sql": """
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
        "blurb": "Top 5 accounts by recognized revenue, with CSAT ≤ 2 flag.",
        "positive": [
            ("top 5", 5),
            ("top five", 5),
            ("highest revenue", 4),
            ("csat", 3),
            ("accounts by revenue", 4),
        ],
        "negative": [("region", 2), ("churn", 3), ("refund", 2)],
    },
    {
        "name": "pending_failed_exposure",
        "sql": """
SELECT
  COUNT(*) AS invoice_count,
  ROUND(COALESCE(SUM(amount_usd), 0), 2) AS exposed_usd
FROM invoices
WHERE status IN ('pending', 'failed')
""".strip(),
        "blurb": "Count and exposed USD of pending/failed invoices.",
        "positive": [
            ("pending", 4),
            ("failed", 4),
            ("stuck", 3),
            ("exposed", 3),
            ("at risk", 3),
        ],
        "negative": [("refund", 2), ("churn", 2), ("mrr", 2)],
    },
]

MIN_TEMPLATE_SCORE = 3


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


def _score_template(question: str, tmpl: dict[str, Any]) -> int:
    q = question.casefold()
    score = 0
    for phrase, weight in tmpl["positive"]:
        if phrase.casefold() in q:
            score += weight
    for phrase, weight in tmpl["negative"]:
        if phrase.casefold() in q:
            score -= weight
    return score


def _match_template(question: str) -> tuple[str, str, str, int] | None:
    scored = [(_score_template(question, t), t) for t in TEMPLATES]
    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best = scored[0]
    if best_score < MIN_TEMPLATE_SCORE:
        return None
    # Require clear winner unless only one candidate clears the bar
    second = scored[1][0] if len(scored) > 1 else -999
    if best_score == second:
        # tie-break: prefer more specific names by fixed priority
        priority = {
            "refunds": 6,
            "churn_by_plan": 5,
            "pending_failed_exposure": 4,
            "top5_revenue_csat": 3,
            "region_avg_mrr": 2,
            "revenue_2024": 1,
        }
        best = max(
            (t for s, t in scored if s == best_score),
            key=lambda t: priority.get(t["name"], 0),
        )
    return best["name"], best["sql"], best["blurb"], best_score


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
    if len(rows) == 1 and len(rows[0]) <= 4:
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
        out: list[dict[str, Any]] = []
        for row in rows[:limit_display]:
            out.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()})
        return out
    finally:
        con.close()


def _enrich_warnings(db_path: Path, template_name: str | None, warnings: list[str]) -> None:
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        dropped = con.execute("SELECT COUNT(*) FROM invoice_dedup_dropped").fetchone()[0]
        if dropped:
            warnings.append(
                f"near_dups_dropped={dropped} (see invoice_dedup_dropped; survivor rule paid>refunded>pending>failed>void)"
            )
        if template_name == "revenue_2024":
            day_first, month_first, amb_touching_2024 = con.execute(
                """
                SELECT
                  ROUND(COALESCE(SUM(CASE
                    WHEN is_recognized_revenue
                     AND invoice_date >= DATE '2024-01-01'
                     AND invoice_date < DATE '2025-01-01'
                    THEN amount_usd END), 0), 2) AS day_first_usd,
                  ROUND(COALESCE(SUM(CASE
                    WHEN is_recognized_revenue
                     AND invoice_date_month_first >= DATE '2024-01-01'
                     AND invoice_date_month_first < DATE '2025-01-01'
                    THEN amount_usd END), 0), 2) AS month_first_usd,
                  SUM(CASE
                    WHEN is_recognized_revenue AND invoice_date_ambiguous
                     AND (
                       (invoice_date >= DATE '2024-01-01' AND invoice_date < DATE '2025-01-01')
                       OR (invoice_date_month_first >= DATE '2024-01-01'
                           AND invoice_date_month_first < DATE '2025-01-01')
                     )
                    THEN 1 ELSE 0 END) AS amb_touching_2024
                FROM invoices
                """
            ).fetchone()
            if day_first != month_first:
                warnings.append(
                    f"date_sensitivity: day_first_2024={day_first} vs month_first_2024={month_first} "
                    f"(ambiguous rows touching 2024={amb_touching_2024})"
                )
            else:
                warnings.append(
                    f"date_sensitivity: day_first and month_first 2024 totals match ({day_first}); "
                    f"ambiguous rows touching 2024={amb_touching_2024}"
                )
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"enrich_warning_failed: {exc}")
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
payment_method, signup_date, invoice_date, invoice_date_month_first,
invoice_date_ambiguous, churned, csat_score, support_tickets,
list_price_usd, mrr_usd, is_recognized_revenue, raw_plan, raw_status.

Also available: invoice_dedup_dropped (near-dup losers).

Rules:
- Recognized revenue: is_recognized_revenue OR status IN ('paid','refunded')
- Prefer invoice_date (day-first). For sensitivity use invoice_date_month_first.
- MRR is mrr_usd; do not divide annual amounts
- Churn by plan: one row per account using latest invoice_date plan
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
    except Exception as exc:  # noqa: BLE001
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
    template_name: str | None = None

    if matched:
        template_name, sql, blurb, score = matched
        warnings.append(f"template={template_name} score={score}")
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

    if mode == "template":
        _enrich_warnings(db_path, template_name, warnings)

    return AskResult(
        answer=_format_answer(blurb, rows),
        sql=sql,
        rows=rows,
        rows_cited=cited,
        warnings=warnings,
        mode=mode,
    )
