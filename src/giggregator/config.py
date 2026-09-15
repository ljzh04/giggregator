"""Central configuration: scoring weights, decay constants, FX defaults.

These are the MVP values from docs/DECISIONS.md ADR-0007. Changing any weight requires a
new ADR entry (AGENTS.md iron rule 4).
"""

from __future__ import annotations

import os

# --- scoring weights (ADR-0007) ---
WEIGHTS: dict[str, float] = {
    "pay": 0.30,
    "fresh": 0.25,
    "effort": 0.15,
    "match": 0.20,
    "trust": 0.10,
}

# --- freshness ---
FRESH_HALF_LIFE_DAYS = 7.0
FRESH_REVERIFIED_BONUS = 0.10  # added when last_verified_at is recent

# --- expiry / re-crawl (ADR-0009) ---
# Bounded feeds (top-50 recent lists) mean absence != gone, so expiry is staleness-based:
# a gig expires when unseen for VERIFIED_TTL days, or unconditionally at ABSOLUTE_MAX days old.
EXPIRY_VERIFIED_TTL_DAYS = 30
EXPIRY_ABSOLUTE_MAX_DAYS = 90

# --- pay normalization ---
USD_PHP_FALLBACK = 58.0  # used until an fx_rates row exists; always overridable
MONTHLY_TO_HOURS = 173.33  # PH standard: 21.75 working days x 8h
YEARLY_TO_HOURS = 2080.0
DAILY_TO_HOURS = 8.0
WEEKLY_TO_HOURS = 40.0

# A low-confidence pay estimate is shrunk toward this percentile (category-median proxy)
MEDIAN_PAY_PERCENTILE = 0.5

# default match factor when no user profile exists (anonymous baseline)
DEFAULT_MATCH = 0.5

# --- effort sub-scores (docs/ARCHITECTURE.md §5) ---
PAYOUT_SCORE = {
    "instant_gcash": 1.0,
    "daily": 0.9,
    "weekly": 0.7,
    "per_task": 0.65,
    "monthly": 0.5,
    "unknown": 0.55,
}

# --- trust ---
SOURCE_RELIABILITY_DEFAULT = 0.8  # tier-1 sources until health data says otherwise

# --- ingest politeness ---
HTTP_USER_AGENT = "GiggregatorBot/0.1 (+https://github.com/giggregator; respectful crawler)"
HTTP_TIMEOUT_SECONDS = 30.0

# --- publisher-API keys (CareerJet / Jooble) ---
# Keys live in env vars only — never in code, never pasted in chat. Adapters skip
# themselves (log + continue) when their key is absent, so ingest stays green pre-key.
CAREERJET_AFFILIATE_ID = os.environ.get("GIGGREGATOR_CAREERJET_AFFILIATE_ID", "")
CAREERJET_API_KEY = os.environ.get("GIGGREGATOR_CAREERJET_KEY", "")
CAREERJET_REFERER = os.environ.get(
    "GIGGREGATOR_CAREERJET_REFERER", "https://giggregator.vercel.app/"
)
JOOBLE_API_KEY = os.environ.get("GIGGREGATOR_JOOBLE_KEY", "")
