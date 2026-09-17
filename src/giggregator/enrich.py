"""Enrichment orchestration: RawListing -> canonical Gig via phase-0 rules.

Pure with respect to the network: takes already-fetched RawListings only.
"""

from __future__ import annotations

from . import config, models, normalize, pay_utils


def enrich(raw: models.RawListing, *, fx: float = config.USD_PHP_FALLBACK) -> models.Gig:
    """Run the full rules pass over one raw listing."""
    now = raw.fetched_at or normalize.utcnow()
    posted = normalize.parse_dt(raw.posted_at_raw) or raw.fetched_at or now

    gig = models.Gig(
        source_id=raw.source_id,
        url=raw.url,
        title=normalize.clean(raw.title),
        body=normalize.clean(raw.body),
        company=normalize.clean(raw.company),
        posted_at=posted,
        first_seen_at=now,
        last_verified_at=now,
        location_raw=normalize.clean(raw.location_raw),
    )

    text = f"{gig.title} {gig.body}"
    gig.pay = pay_utils.pay_from_listing(raw, fx=fx)
    gig.requirements = normalize.extract_requirements(text)
    gig.category = normalize.categorize(gig.title, gig.body)
    gig.tags = normalize.extract_tags(text)
    gig.no_experience_friendly = normalize.is_no_experience_friendly(text)
    gig.employment_type = normalize.employment_type(raw.employment_type_raw)
    gig.payout_cadence = normalize.payout_cadence(text, gig.pay.kind)

    # Scam signals: hard (fee_required) auto-excludes; soft (no_company) only downranks
    # via score.trust_factor. company is passed so "no company + text-only contact" can
    # be detected as a conjunction (AGENTS.md scam layer).
    gig.trust_flags = normalize.scam_flags(
        f"{gig.title} {gig.body} {raw.pay_raw or ''}", company=raw.company
    )
    if "fee_required" in gig.trust_flags:
        gig.status = models.STATUS_FLAGGED

    return gig
