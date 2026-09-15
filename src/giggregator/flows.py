"""Flows: filter/reweight permutations over one scored table (ARCHITECTURE.md §6).

A flow = optional hard filters + optional weight overrides. All flows share the same
stored factor values, so reweighting is cheap (no re-scoring of raw data).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config, models


@dataclass
class Flow:
    id: str
    label: str
    description: str
    categories: set[str] | None = None
    no_experience_only: bool = False
    device: str | None = None
    hours: str | None = None
    max_age_hours: float | None = None
    weights: dict[str, float] = field(default_factory=dict)

    def matches(self, gig: models.Gig, now) -> bool:
        if gig.status != models.STATUS_ACTIVE:
            return False
        if self.categories is not None and gig.category not in self.categories:
            return False
        if self.no_experience_only and not gig.no_experience_friendly:
            return False
        if self.device and gig.requirements.device != self.device:
            return False
        if self.hours and gig.requirements.hours != self.hours:
            return False
        if self.max_age_hours is not None:
            if gig.posted_at is None:
                return False
            age_hours = (now - gig.posted_at).total_seconds() / 3600.0
            if age_hours > self.max_age_hours:
                return False
        return True


FLOWS: dict[str, Flow] = {
    "quick_bucks": Flow(
        id="quick_bucks",
        label="Quick Bucks",
        description="Low-barrier online tasks with the fastest time-to-first-peso",
        categories={"microtasks", "data_entry", "transcription", "ai_training"},
        weights={"pay": 0.35, "fresh": 0.20, "effort": 0.25, "match": 0.10, "trust": 0.10},
    ),
    "highest_relevance": Flow(
        id="highest_relevance", label="Highest Relevance",
        description="The default weighted score",
    ),
    "fresh_drops": Flow(
        id="fresh_drops", label="Fresh Drops",
        description="Posted within the last 48 hours",
        max_age_hours=48.0,
        weights={"pay": 0.25, "fresh": 0.40, "effort": 0.15, "match": 0.10, "trust": 0.10},
    ),
    "no_experience": Flow(
        id="no_experience", label="No Experience",
        description="No prior experience required (student default)",
        no_experience_only=True,
        weights={"pay": 0.25, "fresh": 0.25, "effort": 0.25, "match": 0.15, "trust": 0.10},
    ),
    "mobile_only": Flow(
        id="mobile_only", label="Mobile-Only",
        description="Doable on just a smartphone",
        device=models.DEVICE_MOBILE,
    ),
    "flexible_hours": Flow(
        id="flexible_hours", label="Flexible Hours",
        description="Set your own schedule",
        hours=models.HOURS_FLEX,
        weights={"pay": 0.30, "fresh": 0.20, "effort": 0.25, "match": 0.15, "trust": 0.10},
    ),
}

DEFAULT_FLOW = "highest_relevance"


def flow_weights(flow: Flow) -> dict[str, float]:
    return {**config.WEIGHTS, **flow.weights}
