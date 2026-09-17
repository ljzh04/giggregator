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
    assert (
        normalize.extract_requirements("night shift, US hours schedule").hours == models.HOURS_FIXED
    )
    assert (
        normalize.extract_requirements("flexible hours, set your own schedule").hours
        == models.HOURS_FLEX
    )


def test_min_hours_and_fulltime():
    assert normalize.extract_requirements("commit 20 hours per week").min_hours_per_week == 20
    assert normalize.extract_requirements("This is a full-time position").min_hours_per_week == 40


def test_live_comms():
    assert (
        normalize.extract_requirements("must be comfortable on camera for video calls").comms
        == models.COMMS_LIVE
    )
    assert normalize.extract_requirements("async work, no calls needed").comms == models.COMMS_ASYNC


def test_categories():
    assert normalize.categorize("Part time Data Entry / Encoding") == "data_entry"
    assert normalize.categorize("Online English Tutor for Korean students") == "online_tutoring"
    assert normalize.categorize("Senior Python Developer") == "dev"
    assert normalize.categorize("Virtual Assistant for busy CEO") == "va_admin"
    assert (
        normalize.categorize("AI training tasks", "data annotation and labeling") == "ai_training"
    )
    assert normalize.categorize("Graphic designer needed", "Canva and Photoshop") == "design"
    assert normalize.categorize("We need help with something") == "other"


def test_title_beats_body():
    # 'editor' (content_writing) in body vs 'video editor' (design) in title
    assert (
        normalize.categorize("Video Editor", "we will review each editor application") == "design"
    )


def test_tags():
    tags = normalize.extract_tags("Use Canva, Photoshop, and SEO. English required.")
    assert {"canva", "photoshop", "seo", "english"} <= set(tags)


def test_no_experience():
    assert normalize.is_no_experience_friendly("No experience required, fresh grads welcome")
    assert not normalize.is_no_experience_friendly("5 years experience required")


def test_payout_cadence():
    text = "paid daily via GCash"
    assert normalize.payout_cadence(text, models.PAY_HOURLY) == models.PAYOUT_INSTANT
    assert (
        normalize.payout_cadence("weekly payout every Friday", models.PAY_HOURLY)
        == models.PAYOUT_WEEKLY
    )
    assert (
        normalize.payout_cadence("per project basis", models.PAY_PER_TASK) == models.PAYOUT_PER_TASK
    )
    assert (
        normalize.payout_cadence("salary paid monthly", models.PAY_MONTHLY) == models.PAYOUT_MONTHLY
    )


def test_scam_fee_required_hard_signal():
    assert "fee_required" in normalize.scam_flags("Pay the training fee of ₱500 to start")
    assert "fee_required" in normalize.scam_flags("Registration fee required before applying")
    assert normalize.scam_flags("Great opportunity, apply now") == []


def test_scam_no_company_soft_signal_needs_both_conditions():
    # a real employer name -> a listed contact vector is fine (no false positive)
    assert "no_company" not in normalize.scam_flags("Email careers@acme.com", company="Acme Corp")
    assert normalize.scam_flags("WhatsApp wa.me/639171234567", company="Acme Corp") == []
    # withheld company + direct contact -> soft flag
    assert "no_company" in normalize.scam_flags("Email jobs@gmail.com", company="")
    assert "no_company" in normalize.scam_flags("message me on Discord discord.gg/abc", company="")


def test_scam_no_company_placeholder_counts_as_withheld():
    assert "no_company" in normalize.scam_flags("DM t.me/recruiter", company="N/A")
    assert "no_company" in normalize.scam_flags("telegram tg://join", company="Confidential")


def test_scam_soft_signal_does_not_hard_exclude():
    # soft flags downrank; only fee_required flips status in enrich()
    flags = normalize.scam_flags("call/text 09171234567", company="")
    assert "no_company" in flags and "fee_required" not in flags


def test_employment_type_maps_badges_and_jobtypes():
    assert normalize.employment_type("Gig") == models.EMPLOYMENT_GIG
    assert normalize.employment_type("Part Time") == models.EMPLOYMENT_PART_TIME
    assert normalize.employment_type("Full Time") == models.EMPLOYMENT_FULL_TIME
    assert normalize.employment_type("full_time") == models.EMPLOYMENT_FULL_TIME  # remotive style
    assert normalize.employment_type("Contract") == models.EMPLOYMENT_CONTRACT
    assert normalize.employment_type("Freelance") == models.EMPLOYMENT_CONTRACT
    assert normalize.employment_type("Internship") == models.EMPLOYMENT_INTERNSHIP


def test_employment_type_prefers_narrower_form_when_several():
    # jobType arrays arrive joined; the narrower engagement wins
    assert normalize.employment_type("full-time, part-time") == models.EMPLOYMENT_PART_TIME
    assert normalize.employment_type("part-time, gig") == models.EMPLOYMENT_GIG


def test_employment_type_unknown_never_guessed():
    # OnlineJobs' "Any" badge and free text must not invent a value (iron rule 1)
    assert normalize.employment_type("Any") == models.EMPLOYMENT_UNKNOWN
    assert normalize.employment_type("") == models.EMPLOYMENT_UNKNOWN
    assert normalize.employment_type(None) == models.EMPLOYMENT_UNKNOWN
    assert normalize.employment_type("We need someone reliable") == models.EMPLOYMENT_UNKNOWN
