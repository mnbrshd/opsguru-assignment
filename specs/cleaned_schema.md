# Spec: Cleaned Invoice Schema

Source of truth for the Track B cleaning pipeline. Driven by `data/BUSINESS_CONTEXT.md`.
Implementation must follow this document; do not invent alternate business rules in code.

## Input

- File: `data/cloudnova_invoices.csv`
- Grain: one dirty invoice row (may duplicate `invoice_id`)

## Output

- Store: DuckDB table `invoices` in `data/processed/invoices.duckdb`
- Grain: **one row per `invoice_id`** after deduplication

## Canonical columns

| Column | Type | Notes |
|--------|------|-------|
| `invoice_id` | TEXT PK | Surviving id after dedup |
| `account_id` | TEXT | |
| `account_name` | TEXT | |
| `contact_email` | TEXT NULL | `_at_` → `@`; empty → NULL |
| `region` | TEXT | Uppercased; expected NA/EMEA/APAC/LATAM |
| `industry` | TEXT NULL | Trimmed; empty → NULL |
| `plan` | TEXT | `starter` \| `pro` \| `enterprise` |
| `billing_cycle` | TEXT | `monthly` \| `annual` |
| `seats` | INTEGER | |
| `currency` | TEXT | `USD` \| `EUR` \| `GBP` |
| `amount` | DOUBLE | Parsed local-currency amount (refunds negative) |
| `amount_usd` | DOUBLE | FX-normalized amount |
| `discount_pct` | DOUBLE | 0–100 |
| `status` | TEXT | `paid` \| `pending` \| `failed` \| `refunded` \| `void` |
| `payment_method` | TEXT NULL | Normalized lowercase snake; blank → NULL |
| `signup_date` | DATE NULL | Parsed; NULL if unparseable |
| `invoice_date` | DATE NULL | Parsed; NULL if unparseable |
| `churned` | BOOLEAN | |
| `csat_score` | DOUBLE NULL | |
| `support_tickets` | INTEGER | Coalesce null → 0 |
| `list_price_usd` | DOUBLE | From plan: 49 / 99 / 299 |
| `mrr_usd` | DOUBLE | See MRR formula |
| `is_recognized_revenue` | BOOLEAN | `status IN ('paid','refunded')` |
| `raw_plan` | TEXT | Original dirty value (audit) |
| `raw_status` | TEXT | Original dirty value (audit) |

## Normalization maps

### Plan → `starter` | `pro` | `enterprise`

Match after trim + casefold. Unknown → leave as `unknown` and set a pipeline warning count (do not drop row).

| Canonical | Dirty variants (non-exhaustive) |
|-----------|----------------------------------|
| `starter` | starter, start, tier 1, tier1 |
| `pro` | pro, professional, tier 2, tier2 |
| `enterprise` | enterprise, tier 3, tier3, ent |

### Status → canonical

| Canonical | Dirty variants | Revenue? |
|-----------|----------------|----------|
| `paid` | paid, complete, completed, success | yes |
| `pending` | pending, in_review, awaiting | no |
| `failed` | failed, declined, error | no |
| `refunded` | refunded, refund, charged_back | nets (negative amount) |
| `void` | void, cancelled, canceled | no |

Unmapped → `unknown` (not revenue).

### Billing cycle

| Canonical | Dirty variants |
|-----------|----------------|
| `monthly` | monthly, month |
| `annual` | annual, annually, yearly, year |

### Churned boolean

Truthy: `true`, `t`, `yes`, `y`, `1`  
Falsy: `false`, `f`, `no`, `n`, `0`  
Case-insensitive after trim.

### Payment method

Lowercase, spaces → `_`. Map common aliases: `credit card`/`credit_card` → `credit_card`; `ach` → `ach`; `wire`/`wire transfer` → `wire`; `invoice` → `invoice`.

## Amount parsing

1. Cast to string, trim.
2. Strip surrounding quotes if present.
3. Remove `$` and `,`.
4. Strip trailing currency tokens (`USD`, `EUR`, `GBP`) case-insensitive.
5. Parse float. Failure → NULL amount / amount_usd (row kept; flagged).

## FX → USD

Fixed rates from business context:

- `USD` → × 1.0
- `EUR` → × 1.08
- `GBP` → × 1.27

`amount_usd = amount * fx[currency]` when amount is non-null.

## Recognized revenue

Include rows where `status IN ('paid', 'refunded')`. Refunds already carry negative `amount` / `amount_usd` and net against totals. Do **not** include pending/failed/void/unknown.

## MRR

List prices (USD per seat per month): starter 49, pro 99, enterprise 299.

```
mrr_usd = list_price_usd * seats * (1 - discount_pct/100)
```

- Independent of billing cycle (annual invoices still map to the same underlying monthly MRR).
- Do **not** use `amount / 10` for annual.
- If plan is `unknown`, `list_price_usd` and `mrr_usd` are NULL.

## Date parsing

Try formats in order (per field):

1. `%Y-%m-%d`
2. `%m/%d/%Y`
3. `%Y/%m/%d`
4. `%b %d %Y` / `%B %d %Y`
5. `%d-%m-%Y` (day-first when both parts ≤ 12 **or** day > 12)
6. `%m-%d-%Y` only when the first number is ≤ 12 and second > 12 (US-style unambiguous)

Ambiguous `05-01-2024`-style (both ≤ 12): **prefer day-first (`%d-%m-%Y`)** and record a warning. Document this choice in README.

Unparseable → NULL.

## Deduplication

1. Drop exact duplicate rows (all columns equal) first.
2. Group by `invoice_id`.
3. Rank status priority (higher wins):  
   `paid` (5) > `refunded` (4) > `pending` (3) > `failed` (2) > `void` (1) > `unknown` (0)
4. Tie-break: latest non-null `invoice_date`, then first remaining row order.
5. Emit one survivor row per `invoice_id`.

## Constraints

- `seats` ≥ 0
- `discount_pct` between 0 and 100 when parseable; out-of-range clipped with warning
- Pipeline is idempotent: re-run replaces `invoices` table
