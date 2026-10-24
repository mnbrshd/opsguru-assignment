CREATE TABLE IF NOT EXISTS invoices (
    invoice_id VARCHAR PRIMARY KEY,
    account_id VARCHAR,
    account_name VARCHAR,
    contact_email VARCHAR,
    region VARCHAR,
    industry VARCHAR,
    plan VARCHAR,
    billing_cycle VARCHAR,
    seats INTEGER,
    currency VARCHAR,
    amount DOUBLE,
    amount_usd DOUBLE,
    discount_pct DOUBLE,
    status VARCHAR,
    payment_method VARCHAR,
    signup_date DATE,
    invoice_date DATE,
    invoice_date_month_first DATE,
    invoice_date_ambiguous BOOLEAN,
    churned BOOLEAN,
    csat_score DOUBLE,
    support_tickets INTEGER,
    list_price_usd DOUBLE,
    mrr_usd DOUBLE,
    is_recognized_revenue BOOLEAN,
    raw_plan VARCHAR,
    raw_status VARCHAR
);

-- Near-duplicate losers (same invoice_id, lower status priority)
CREATE TABLE IF NOT EXISTS invoice_dedup_dropped (
    invoice_id VARCHAR,
    account_id VARCHAR,
    status VARCHAR,
    amount_usd DOUBLE,
    invoice_date DATE,
    survivor_status VARCHAR,
    drop_reason VARCHAR
);
