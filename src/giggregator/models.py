"""Canonical data models for Giggregator.

The pipeline contract: RawListing (what adapters emit) -> Gig (canonical record).
Parse/normalize/enrich/score are pure functions over these dataclasses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# --- enums (kept as str constants: simple, JSON-serializable, greppable) ---

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_FLAGGED = "flagged"

PAY_HOURLY = "hourly"
PAY_DAILY = "daily"
PAY_WEEKLY = "weekly"
PAY_MONTHLY = "monthly"
PAY_YEARLY = "yearly"
PAY_PER_TASK = "per_task"
PAY_UNKNOWN = "unknown"

DEVICE_ANY = "any_device"
DEVICE_PC = "pc_required"
DEVICE_MOBILE = "mobile_only"

INTERNET_ANY = "any"
INTERNET_STABLE = "stable_high"

HOURS_FLEX = "flexible"
HOURS_FIXED = "fixed_shift"

COMMS_ASYNC = "async"
COMMS_LIVE = "live"

# payout cadence values, ordered slow->fast for scoring
PAYOUT_UNKNOWN = "unknown"
PAYOUT_MONTHLY = "monthly"
PAYOUT_PER_TASK = "per_task"
PAYOUT_WEEKLY = "weekly"
PAYOUT_DAILY = "daily"
PAYOUT_INSTANT = "instant_gcash"

# employment / engagement type (surfaced from listing badges + source jobType fields)
EMPLOYMENT_GIG = "gig"
EMPLOYMENT_INTERNSHIP = "internship"
EMPLOYMENT_CONTRACT = "contract"
EMPLOYMENT_PART_TIME = "part_time"
EMPLOYMENT_FULL_TIME = "full_time"
EMPLOYMENT_UNKNOWN = "unknown"


@dataclass
class RawListing:
    """Uniform output of every source adapter (the only impure boundary)."""

    source_id: str
    url: str
    title: str
    body: str = ""
    company: str = ""
    posted_at_raw: str | None = None  # ISO-ish string; parser may fall back to first_seen
    pay_raw: str | None = None
    location_raw: str = ""
    employment_type_raw: str = ""  # raw badge / jobType text; normalize maps it
    fetched_at: datetime | None = None


@dataclass
class PayInfo:
    """Normalized pay. Iron rule 1: never fabricate — `raw_text` is always kept."""

    kind: str = PAY_UNKNOWN
    raw_text: str = ""
    hourly_equiv_php: float | None = None
    currency: str | None = None  # "USD" | "PHP" | None when unknown
    confidence: float = 0.0


@dataclass
class Requirements:
    """Device/internet/hours/comms profile — the entry ticket for this audience."""

    device: str = DEVICE_ANY
    internet: str = INTERNET_ANY
    hours: str = HOURS_FLEX
    min_hours_per_week: int | None = None
    comms: str = COMMS_ASYNC


@dataclass
class Gig:
    """Canonical gig record (mirrors docs/ARCHITECTURE.md §2)."""

    source_id: str
    url: str
    title: str
    body: str
    company: str = ""
    posted_at: datetime | None = None
    first_seen_at: datetime | None = None
    last_verified_at: datetime | None = None
    status: str = STATUS_ACTIVE
    pay: PayInfo = field(default_factory=PayInfo)
    requirements: Requirements = field(default_factory=Requirements)
    payout_cadence: str = PAYOUT_UNKNOWN
    tags: list[str] = field(default_factory=list)
    category: str = "other"
    employment_type: str = EMPLOYMENT_UNKNOWN
    no_experience_friendly: bool = False
    trust_flags: list[str] = field(default_factory=list)
    location_raw: str = ""
    dedupe_key: str = ""
    # computed at score time; stored on the row as JSON
    scores: dict = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    id: int | None = None  # DB row id; set by db.gig_from_row

    def __post_init__(self) -> None:
        if self.source_id and self.source_id not in self.source_ids:
            self.source_ids.insert(0, self.source_id)
