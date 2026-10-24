# Spec: Eval Harness

## Purpose

Prove the cleaned model + query path answers stakeholder questions correctly, and document one intentional failure mode.

## Runner

```bash
python -m evals.run_eval
```

- Builds/loads DuckDB via the same pipeline as the app (unless DB already fresh).
- Uses **template SQL** (or case-embedded SQL) — **no live LLM in CI**.
- Prints one line per case: `PASS` / `FAIL` / `XFAIL` (expected fail).
- Exit code `0` if all required cases pass and expected-fail behaves as documented; non-zero otherwise.

## Case file

`evals/cases.yaml` entries:

```yaml
- id: revenue_2024_paid
  question: "What was our total recognized revenue in USD for paid invoices in 2024?"
  sql: |
    SELECT ...
  expect:
    type: scalar_float
    column: total_revenue_usd
    # filled after first trusted pipeline run; tolerance relative
    value: null  # harness may compute baseline once and lock
    tolerance_abs: 1.0
  expected_fail: false
```

### Expect types

| Type | Check |
|------|-------|
| `scalar_float` | Single-row single-column float within `tolerance_abs` |
| `scalar_int` | Exact int match |
| `row_count` | Result has `min_rows` / `max_rows` |
| `top_n_accounts` | First N `account_id` match ordered list; optional CSAT flag column present |
| `contains_regions` | Result regions ⊆ allowed set |

## Seed questions (from BUSINESS_CONTEXT)

1. Total recognized revenue USD for paid (+ refund nets) with `invoice_date` in 2024
2. Region with highest average MRR per account
3. Total refunds given back (absolute sum of negative recognized refund amounts, or sum of refunded `amount_usd`)
4. Churn rate Enterprise vs Starter (account-level: any churned flag among accounts that have that plan)
5. Top 5 accounts by recognized revenue + CSAT ≤ 2 flag
6. Count + exposed $ of pending/failed invoices

## Expected-fail case

`naive_paid_only_ignores_refunds` — runs SQL with `status = 'paid'` only (omitting refund nets) and asserts against the **correct** recognized-revenue total. The assertion **fails** by design → harness `XFAIL`.

Rationale: on this extract, day-first vs month-first 2024 totals matched, so an ambiguous-date XFAIL would be a false story. Refund-netting is the clearer business-logic failure mode (~\$28.1M paid-only vs ~\$26.3M recognized).

## Honesty requirement

README and case `notes` must state:
- Dedup priority changes near-dup outcomes
- Ambiguous dates
- Unknown plan/status rows excluded from MRR/revenue
