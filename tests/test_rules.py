"""Unit tests for requirement extraction, categorization, tags, payout, scam rules."""

from __future__ import annotations

from giggregator import models, normalize


def test_device_pc_and_stable_internet():
    req = normalize.extract_requirements(
        "Must have own laptop and a stable internet connection of at least 25 mbps"
    )
    assert req.device == models.DEVICE_PC
    assert req.internet == models.INTERNET_STABLE


def test_device_mobile_only():
    req = normalize.extract_requirements("work using your smartphone, mobile only tasks")
    assert req.device == models.DEVICE_MOBILE


def test_fixed_shift_vs_flexible():
    assert normalize.extract_requirements("night shift, US hours schedule").hours == models.HOURS_FIXED
    assert normalize.extract_requirements("flexible hours, set your own schedule").hours == models.HOURS_FLEX


def test_min_hours_and_fulltime():
    assert normalize.extract_requirements("commit 20 hours per week").min_hours_per_week == 20
    assert normalize.extract_requirements("This is a full-time position").min_hours_per_week == 40


def test_live_comms():
    assert normalize.extract_requirements("must be comfortable on camera for video calls").comms == models.COMMS_LIVE
    assert normalize.extract_requirements("async work, no calls needed").comms == models.COMMS_ASYNC


def test_categories():
    assert normalize.categorize("Part time Data Entry / Encoding") == "data_entry"
    assert normalize.categorize("Online English Tutor for Korean students") == "online_tutoring"
    assert normalize.categorize("Senior Python Developer") == "dev"
    assert normalize.categorize("Virtual Assistant for busy CEO") == "va_admin"
    assert normalize.categorize("AI training tasks", "data annotation and labeling") == "ai_training"
    assert normalize.categorize("Graphic designer needed", "Canva and Photoshop") == "design"
    assert normalize.categorize("We need help with something") == "other"


def test_title_beats_body():
    # 'editor' (content_writing) in body vs 'video editor' (design) in title
    assert normalize.categorize("Video Editor", "we will review each editor application") == "design"


def test_tags():
    tags = normalize.extract_tags("Use Canva, Photoshop, and SEO. English required.")
    assert {"canva", "photoshop", "seo", "english"} <= set(tags)


def test_no_experience():
    assert normalize.is_no_experience_friendly("No experience required, fresh grads welcome")
    assert not normalize.is_no_experience_friendly("5 years experience required")


def test_payout_cadence():
    text = "paid daily via GCash"
    assert normalize.payout_cadence(text, models.PAY_HOURLY) == models.PAYOUT_INSTANT
    assert normalize.payout_cadence("weekly payout every Friday", models.PAY_HOURLY) == models.PAYOUT_WEEKLY
    assert normalize.payout_cadence("per project basis", models.PAY_PER_TASK) == models.PAYOUT_PER_TASK
    assert normalize.payout_cadence("salary paid monthly", models.PAY_MONTHLY) == models.PAYOUT_MONTHLY


def test_scam_fee_required_hard_signal():
    assert "fee_required" in normalize.scam_flags("Pay the training fee of ₱500 to start")
    assert "fee_required" in normalize.scam_flags("Registration fee required before applying")
    assert normalize.scam_flags("Great opportunity, apply now") == []
