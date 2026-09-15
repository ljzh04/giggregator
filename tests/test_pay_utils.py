"""Regression tests for pay extraction across whole listings (source conventions)."""

from __future__ import annotations

from giggregator import models, pay_utils
from giggregator.models import RawListing

FX = 58.0


def _oj(pay_raw):
    return RawListing(
        source_id="onlinejobs_ph", url="https://www.onlinejobs.ph/jobseekers/job/x",
        title="Job", body="body", pay_raw=pay_raw,
    )


def test_onlinejobs_php_monthly_salary():
    # real fixture string: PH monthly salary, currency-repeated range
    info = pay_utils.pay_from_listing(_oj("Php 45,000 - Php 63,000"), fx=FX)
    assert info.kind == models.PAY_MONTHLY
    assert info.currency == "PHP"
    assert abs(info.hourly_equiv_php - 54000 / 173.33) < 0.5


def test_onlinejobs_usd_monthly_salary():
    info = pay_utils.pay_from_listing(_oj("$650 - ( Per Email Bonus )"), fx=FX)
    assert info.kind == models.PAY_MONTHLY
    assert abs(info.hourly_equiv_php - 650 / 173.33 * FX) < 0.5


def test_onlinejobs_usd_hourly():
    info = pay_utils.pay_from_listing(_oj("$7/hour"), fx=FX)
    assert info.kind == models.PAY_HOURLY
    assert info.hourly_equiv_php == 7 * FX


def test_onlinejobs_php_hourly_explicit():
    info = pay_utils.pay_from_listing(_oj("120/hr"), fx=FX)
    assert info.kind == models.PAY_HOURLY
    assert info.currency == "PHP"
    assert info.hourly_equiv_php == 120


def test_onlinejobs_bare_small_number_is_usd_hourly():
    info = pay_utils.pay_from_listing(_oj("6"), fx=FX)
    assert info.currency == "USD"
    assert info.kind == models.PAY_HOURLY
    assert info.hourly_equiv_php == 6 * FX


def test_remotive_knotation_salary():
    raw = RawListing(
        source_id="remotive", url="https://remotive.com/x", title="Job",
        body="body", pay_raw="$31,2k- $52k",
    )
    info = pay_utils.pay_from_listing(raw, fx=FX)
    assert info.kind == models.PAY_YEARLY
    assert abs(info.hourly_equiv_php - 41600 / 2080 * FX) < 0.5


def test_body_scan_fallback():
    raw = RawListing(
        source_id="remotive", url="https://remotive.com/x", title="Job",
        body="We pay $10 per hour depending on experience. Apply now.",
    )
    info = pay_utils.pay_from_listing(raw, fx=FX)
    assert info.hourly_equiv_php == 10 * FX
