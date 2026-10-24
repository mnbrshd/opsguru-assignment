"""Clean + model CloudNova invoices into DuckDB per specs/cleaned_schema.md."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

LIST_PRICE = {"starter": 49.0, "pro": 99.0, "enterprise": 299.0}
FX = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27}

STATUS_PRIORITY = {
    "paid": 5,
    "refunded": 4,
    "pending": 3,
    "failed": 2,
    "void": 1,
    "unknown": 0,
}

PLAN_MAP = {
    "starter": "starter",
    "start": "starter",
    "tier 1": "starter",
    "tier1": "starter",
    "pro": "pro",
    "professional": "pro",
    "tier 2": "pro",
    "tier2": "pro",
    "enterprise": "enterprise",
    "ent": "enterprise",
    "tier 3": "enterprise",
    "tier3": "enterprise",
}

STATUS_MAP = {
    "paid": "paid",
    "complete": "paid",
    "completed": "paid",
    "success": "paid",
    "pending": "pending",
    "in_review": "pending",
    "awaiting": "pending",
    "failed": "failed",
    "declined": "failed",
    "error": "failed",
    "refunded": "refunded",
    "refund": "refunded",
    "charged_back": "refunded",
    "void": "void",
    "cancelled": "void",
    "canceled": "void",
}

BILLING_MAP = {
    "monthly": "monthly",
    "month": "monthly",
    "annual": "annual",
    "annually": "annual",
    "yearly": "annual",
    "year": "annual",
}

DEFAULT_CSV = Path("data/cloudnova_invoices.csv")
DEFAULT_DB = Path("data/processed/invoices.duckdb")
SCHEMA_SQL = Path(__file__).with_name("schema.sql")


def _norm_key(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip().casefold())


def normalize_plan(raw: Any) -> str:
    key = _norm_key(raw)
    return PLAN_MAP.get(key, "unknown")


def normalize_status(raw: Any) -> str:
    key = _norm_key(raw)
    return STATUS_MAP.get(key, "unknown")


def normalize_billing(raw: Any) -> str:
    key = _norm_key(raw)
    return BILLING_MAP.get(key, "unknown")


def normalize_churned(raw: Any) -> bool:
    key = _norm_key(raw)
    if key in {"true", "t", "yes", "y", "1"}:
        return True
    return False


def normalize_email(raw: Any) -> str | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s:
        return None
    return s.replace("_at_", "@")


def normalize_payment_method(raw: Any) -> str | None:
    key = _norm_key(raw)
    if not key:
        return None
    aliases = {
        "credit card": "credit_card",
        "credit_card": "credit_card",
        "ach": "ach",
        "wire": "wire",
        "wire transfer": "wire",
        "invoice": "invoice",
    }
    if key in aliases:
        return aliases[key]
    return key.replace(" ", "_")


def parse_amount(raw: Any) -> float | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip().strip('"').strip("'")
    if not s:
        return None
    s = s.replace("$", "").replace(",", "")
    s = re.sub(r"\s*(USD|EUR|GBP)\s*$", "", s, flags=re.IGNORECASE).strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(raw: Any, warnings: list[str] | None = None) -> pd.Timestamp | None:
    """Parse mixed date formats; ambiguous both<=12 prefers day-first."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    s = str(raw).strip()
    if not s:
        return None

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d", "%b %d %Y", "%B %d %Y", "%d/%m/%Y"):
        try:
            return pd.to_datetime(s, format=fmt)
        except (ValueError, TypeError):
            pass

    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{4})", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if a > 12 and b <= 12:
            try:
                return pd.Timestamp(year=y, month=b, day=a)
            except ValueError:
                return None
        if b > 12 and a <= 12:
            try:
                return pd.Timestamp(year=y, month=a, day=b)
            except ValueError:
                return None
        # Ambiguous: prefer day-first per spec
        if warnings is not None:
            warnings.append(f"ambiguous_date_day_first:{s}")
        try:
            return pd.Timestamp(year=y, month=b, day=a)
        except ValueError:
            return None

    try:
        return pd.to_datetime(s, dayfirst=True)
    except (ValueError, TypeError):
        return None


def clean_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    warnings: list[str] = []
    stats: dict[str, Any] = {"input_rows": len(df)}

    work = df.copy()
    work = work.drop_duplicates()
    stats["after_exact_dedup"] = len(work)

    work["raw_plan"] = work["plan"].astype(str)
    work["raw_status"] = work["status"].astype(str)
    work["plan"] = work["plan"].map(normalize_plan)
    work["status"] = work["status"].map(normalize_status)
    work["billing_cycle"] = work["billing_cycle"].map(normalize_billing)
    work["churned"] = work["churned"].map(normalize_churned)
    work["contact_email"] = work["contact_email"].map(normalize_email)
    work["payment_method"] = work["payment_method"].map(normalize_payment_method)

    work["region"] = work["region"].map(lambda x: _norm_key(x).upper() if _norm_key(x) else None)
    work["industry"] = work["industry"].map(
        lambda x: None if not _norm_key(x) else str(x).strip()
    )
    work["currency"] = work["currency"].map(lambda x: _norm_key(x).upper() if _norm_key(x) else "USD")

    work["amount"] = work["amount"].map(parse_amount)
    work["discount_pct"] = pd.to_numeric(work["discount_pct"], errors="coerce").fillna(0.0)
    work.loc[work["discount_pct"] < 0, "discount_pct"] = 0.0
    work.loc[work["discount_pct"] > 100, "discount_pct"] = 100.0

    work["seats"] = pd.to_numeric(work["seats"], errors="coerce").fillna(0).astype(int)
    work.loc[work["seats"] < 0, "seats"] = 0

    work["csat_score"] = pd.to_numeric(work["csat_score"], errors="coerce")
    work["support_tickets"] = (
        pd.to_numeric(work["support_tickets"], errors="coerce").fillna(0).astype(int)
    )

    amb_warn: list[str] = []
    work["invoice_date"] = work["invoice_date"].map(lambda v: parse_date(v, amb_warn))
    work["signup_date"] = work["signup_date"].map(lambda v: parse_date(v, amb_warn))
    stats["ambiguous_dates"] = len(amb_warn)
    warnings.extend(amb_warn[:20])

    work["amount_usd"] = work.apply(
        lambda r: None
        if r["amount"] is None or pd.isna(r["amount"])
        else float(r["amount"]) * FX.get(r["currency"], 1.0),
        axis=1,
    )

    work["list_price_usd"] = work["plan"].map(lambda p: LIST_PRICE.get(p))
    work["mrr_usd"] = work.apply(
        lambda r: None
        if r["list_price_usd"] is None
        else float(r["list_price_usd"])
        * int(r["seats"])
        * (1.0 - float(r["discount_pct"]) / 100.0),
        axis=1,
    )
    work["is_recognized_revenue"] = work["status"].isin(["paid", "refunded"])

    work["_status_rank"] = work["status"].map(lambda s: STATUS_PRIORITY.get(s, 0))
    work = work.sort_values(
        by=["invoice_id", "_status_rank", "invoice_date"],
        ascending=[True, False, False],
        na_position="last",
    )
    work = work.drop_duplicates(subset=["invoice_id"], keep="first")
    work = work.drop(columns=["_status_rank"])

    stats["output_rows"] = len(work)
    stats["unknown_plan"] = int((work["plan"] == "unknown").sum())
    stats["unknown_status"] = int((work["status"] == "unknown").sum())
    stats["warnings_sample"] = warnings[:10]

    cols = [
        "invoice_id",
        "account_id",
        "account_name",
        "contact_email",
        "region",
        "industry",
        "plan",
        "billing_cycle",
        "seats",
        "currency",
        "amount",
        "amount_usd",
        "discount_pct",
        "status",
        "payment_method",
        "signup_date",
        "invoice_date",
        "churned",
        "csat_score",
        "support_tickets",
        "list_price_usd",
        "mrr_usd",
        "is_recognized_revenue",
        "raw_plan",
        "raw_status",
    ]
    return work[cols].reset_index(drop=True), stats


def load_raw_csv(csv_path: Path) -> pd.DataFrame:
    return pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])


def write_duckdb(df: pd.DataFrame, db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))
    try:
        schema = SCHEMA_SQL.read_text(encoding="utf-8")
        con.execute(schema)
        con.register("_clean", df)
        con.execute("INSERT INTO invoices SELECT * FROM _clean")
    finally:
        con.close()


def run_pipeline(
    csv_path: Path | str = DEFAULT_CSV,
    db_path: Path | str = DEFAULT_DB,
) -> dict[str, Any]:
    csv_path = Path(csv_path)
    db_path = Path(db_path)
    raw = load_raw_csv(csv_path)
    cleaned, stats = clean_dataframe(raw)
    write_duckdb(cleaned, db_path)
    stats["db_path"] = str(db_path)
    stats["csv_path"] = str(csv_path)
    return stats


if __name__ == "__main__":
    result = run_pipeline()
    print(result)
