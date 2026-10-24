"""Property tests for amount and date parsers (specs/cleaned_schema.md)."""

from __future__ import annotations

from datetime import date

import pytest
from hypothesis import assume, given, settings, strategies as st

from app.pipeline import parse_amount, parse_date_pair


@given(st.floats(min_value=-1e7, max_value=1e7, allow_nan=False, allow_infinity=False))
@settings(max_examples=80)
def test_parse_amount_roundtrip_plain_float(value: float) -> None:
    text = f"{value:.2f}"
    parsed = parse_amount(text)
    assert parsed is not None
    assert abs(parsed - float(text)) < 1e-6


@given(st.floats(min_value=0.01, max_value=1e6, allow_nan=False, allow_infinity=False))
@settings(max_examples=60)
def test_parse_amount_currency_decorations(value: float) -> None:
    plain = float(f"{value:.2f}")
    base = f"{plain:,.2f}"
    for text in (f"${base}", f"{base} USD", f"{base} EUR", f"${base} GBP"):
        parsed = parse_amount(text)
        assert parsed is not None
        assert parsed == pytest.approx(plain, rel=1e-6, abs=1e-4)


def test_parse_amount_negatives_and_junk() -> None:
    assert parse_amount("$-4,900.00") == pytest.approx(-4900.0)
    assert parse_amount("not-a-number") is None
    assert parse_amount("") is None
    assert parse_amount(None) is None


@given(
    st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31)).filter(
        lambda d: d.day > 12
    )
)
@settings(max_examples=60)
def test_parse_date_iso_unambiguous(d: date) -> None:
    iso = d.isoformat()
    day_first, month_first, ambiguous = parse_date_pair(iso)
    assert not ambiguous
    assert day_first is not None and month_first is not None
    assert day_first.date() == d
    assert month_first.date() == d


@given(
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=1, max_value=12),
    st.integers(min_value=2020, max_value=2026),
)
@settings(max_examples=80)
def test_parse_date_ambiguous_dash_prefers_day_first(a: int, b: int, y: int) -> None:
    raw = f"{a:02d}-{b:02d}-{y}"
    day_first, month_first, ambiguous = parse_date_pair(raw)
    assert ambiguous is True
    if day_first is not None:
        assert day_first.day == a and day_first.month == b
    if month_first is not None:
        assert month_first.day == b and month_first.month == a
    # At least one interpretation should be a valid calendar date for most inputs
    assume(day_first is not None or month_first is not None)


def test_parse_date_unambiguous_day_gt_12() -> None:
    day_first, month_first, ambiguous = parse_date_pair("22-11-2025")
    assert not ambiguous
    assert day_first is not None
    assert day_first.day == 22 and day_first.month == 11
    assert month_first == day_first
