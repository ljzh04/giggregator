"""Source registry. Adding a source = one adapter module + a line here
(docs/SOURCES.md status table must be updated in the same task)."""

from __future__ import annotations

from .arbeitnow import ArbeitnowAdapter
from .base import SourceAdapter, SourceMeta
from .careerjet_ph import CareerjetPhAdapter
from .jobicy import JobicyAdapter
from .jooble_ph import JooblePhAdapter
from .onlinejobs_ph import OnlineJobsAdapter
from .remotive import RemotiveAdapter

ADAPTERS: list[SourceAdapter] = [
    OnlineJobsAdapter(),
    RemotiveAdapter(),
    JobicyAdapter(),
    ArbeitnowAdapter(),
    CareerjetPhAdapter(),
    JooblePhAdapter(),
]

__all__ = [
    "ADAPTERS",
    "ArbeitnowAdapter",
    "CareerjetPhAdapter",
    "JobicyAdapter",
    "JooblePhAdapter",
    "OnlineJobsAdapter",
    "RemotiveAdapter",
    "SourceAdapter",
    "SourceMeta",
]
