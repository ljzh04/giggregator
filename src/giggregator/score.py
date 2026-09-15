"""Scoring module — the relevance metric from docs/ARCHITECTURE.md §5 (ADR-0007).

All factors return 0.0..1.0; `relevance` maps the weighted sum to 0..100.
Weights live in config.py; changing them requires a docs/DECISIONS.md entry.
"""

from __future__ import annotations

import bisect
from datetime import datetime

from . import config, models


def freshness(
    posted_at: datetime | None, now: datetime, *, last_verified_at: datetime | None = None
) -> float:
    """Exponential decay with a 7-day half-life; small boost for recent re-verification."""
    if posted_at is None:
        return 0.3
    age_days = max(0.0, (now - posted_at).total_seconds() / 86400.0)
    value = 0.5 ** (age_days / config.FRESH_HALF_LIFE_DAYS)
    if last_verified_at is not None and (now - last_verified_at).days <= 2:
        value = min(1.0, value + config.FRESH_REVERIFIED_BONUS)
    return value


def pay_percentile(value: float | None, corpus_pay_sorted: list[float]) -> float | None:
    """Percentile of a listing's ₱/hr within the current active corpus (single pool)."""
    if value is None or not corpus_pay_sorted:
        return None
    if len(corpus_pay_sorted) == 1:
        return 0.5
    idx = bisect.bisect_right(corpus_pay_sorted, value) - 1
    return max(0.0, min(1.0, idx / (len(corpus_pay_sorted) - 1)))


def pay_factor(pay_pct: float | None, confidence: float) -> float:
    """Confidence-shrunk toward the corpus-median proxy (ADR-0007)."""
    if pay_pct is None:
        return 0.4  # unknown-pay baseline, below most real estimates
    c = max(0.0, min(1.0, confidence))
    return pay_pct * c + config.MEDIAN_PAY_PERCENTILE * (1.0 - c)


def effort_factor(
    payout_cadence: str, req: models.Requirements, no_experience_friendly: bool
) -> float:
    """Apply friction + time-to-payout + commitment + device/comms barrier."""
    payout = config.PAYOUT_SCORE.get(payout_cadence, config.PAYOUT_SCORE[models.PAYOUT_UNKNOWN])
    if req.hours == models.HOURS_FLEX:
        hours_score = 1.0
    elif req.min_hours_per_week:
        commitment = 1.0 - min(req.min_hours_per_week / 40.0, 1.0)
        hours_score = (0.6 + commitment) / 2.0
    else:
        hours_score = 0.6
    comms = 1.0 if req.comms == models.COMMS_ASYNC else 0.7
    device = 1.0 if req.device in (models.DEVICE_ANY, models.DEVICE_MOBILE) else 0.8
    effort = 0.40 * payout + 0.25 * hours_score + 0.20 * comms + 0.15 * device
    if no_experience_friendly:
        effort = min(1.0, effort + 0.05)
    return effort


def trust_factor(source_reliability: float, trust_flags: list[str]) -> float:
    """Source health minus soft-flag penalties. Hard-flagged gigs are excluded upstream."""
    soft_flags = [f for f in trust_flags if f != "fee_required"]
    return round(max(0.0, min(1.0, source_reliability - 0.10 * len(soft_flags))), 6)



def relevance(factors: dict[str, float], weights: dict[str, float] | None = None) -> float:
    weights = weights or config.WEIGHTS
    total_weight = sum(weights.values())
    return round(100.0 * sum(weights[k] * factors.get(k, 0.0) for k in weights) / total_weight, 1)


def score_gig(
    gig: models.Gig,
    corpus_pay_sorted: list[float],
    now: datetime,
    *,
    source_reliability: float = config.SOURCE_RELIABILITY_DEFAULT,
    weights: dict[str, float] | None = None,
    match: float = config.DEFAULT_MATCH,
) -> dict:
    """Full factor breakdown + relevance for one gig. Pure; no DB access."""
    factors = {
        "pay": pay_factor(
            pay_percentile(gig.pay.hourly_equiv_php, corpus_pay_sorted), gig.pay.confidence
        ),
        # ARCHITECTURE.md §5: expired gigs score 0 on freshness (belt-and-braces with
        # the active-only serving filter — an expired row can never rank).
        "fresh": 0.0
        if gig.status == models.STATUS_EXPIRED
        else freshness(gig.posted_at, now, last_verified_at=gig.last_verified_at),
        "effort": effort_factor(gig.payout_cadence, gig.requirements, gig.no_experience_friendly),
        "match": match,
        "trust": trust_factor(source_reliability, gig.trust_flags),
    }
    return {"factors": factors, "relevance": relevance(factors, weights)}
