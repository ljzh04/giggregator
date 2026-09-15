"""Golden unit tests for normalize.parse_pay — built from REAL fixture pay strings
(OnlineJobs card dd values, Remotive salary fields; see fixture MANIFESTs).
fx = 58.0 PHP/USD for all assertions."""

from __future__ import annotations

from giggregator import models, normalize

FX = 58.0


def p(text, **kw):
    kw.setdefault("fx", FX)
    return normalize.parse_pay(text, **kw)


def test_explicit_hourly_usd():
    info = p("$7/hour")
    assert info.kind == models.PAY_HOURLY
    assert info.currency == "USD"
    assert info.hourly_equiv_php == 7 * FX


def test_explicit_hourly_php():
    info = p("₱120/hr")
    assert info.kind == models.PAY_HOURLY
    assert info.hourly_equiv_php == 120


def test_knotation_european_decimal_range_remotive():
    # real Remotive fixture value: "$31,2k- $52k", annual USD
    info = p("$31,2k- $52k", default_currency="USD", default_period=models.PAY_YEARLY)
    assert info.kind == models.PAY_YEARLY
    assert abs(info.hourly_equiv_php - ((31200 + 52000) / 2 / 2080 * FX)) < 0.01


def test_per_task_has_no_hourly_equivalent():
    info = p("$3/gig")
    assert info.kind == models.PAY_PER_TASK
    assert info.hourly_equiv_php is None


def test_monthly_php():
    info = p("PHP 25,000 monthly")
    assert info.kind == models.PAY_MONTHLY
    assert abs(info.hourly_equiv_php - 25000 / 173.33) < 0.01


def test_monthly_usd_range_doe():
    info = p("$500-1000/month DOE")
    assert info.kind == models.PAY_MONTHLY
    assert abs(info.hourly_equiv_php - 750 / 173.33 * FX) < 0.01


def test_en_dash_hourly_range():
    info = p("$6–$7 USD/hour depending on experience")
    assert info.kind == models.PAY_HOURLY
    assert abs(info.hourly_equiv_php - 6.5 * FX) < 0.01


def test_word_to_range_monthly():
    info = p("750 to 1200 per month", default_currency="PHP")
    assert info.kind == models.PAY_MONTHLY
    assert abs(info.hourly_equiv_php - 975 / 173.33) < 0.01


def test_negotiable_is_zero_confidence_unknown():
    info = p("Negotiable – based on experience")
    assert info.kind == models.PAY_UNKNOWN
    assert info.hourly_equiv_php is None
    assert info.confidence == 0.0
    assert info.raw_text == "Negotiable – based on experience"  # raw preserved


def test_bare_number_without_defaults_is_unknown():
    info = p("1000")
    assert info.kind == models.PAY_UNKNOWN
    assert info.hourly_equiv_php is None


def test_bare_number_with_default_period_is_penalized():
    info = p("120/hr", default_currency="PHP")
    assert info.kind == models.PAY_HOURLY
    assert info.hourly_equiv_php == 120
    assert info.confidence < 0.8  # currency inferred


def test_usd_monthly():
    info = p("$800 month")
    assert info.kind == models.PAY_MONTHLY
    assert abs(info.hourly_equiv_php - 800 / 173.33 * FX) < 0.01


def test_empty_is_unknown():
    info = p(None)
    assert info.kind == models.PAY_UNKNOWN
    assert info.confidence == 0.0
