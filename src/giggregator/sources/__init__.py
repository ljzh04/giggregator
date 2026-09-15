"""Source registry. Adding a source = one adapter module + a line here
(docs/SOURCES.md status table must be updated in the same task)."""

from __future__ import annotations

from .arbeitnow import ArbeitnowAdapter
from .base import SourceAdapter, SourceMeta
from .jobicy import JobicyAdapter
from .onlinejobs_ph import OnlineJobsAdapter
from .remotive import RemotiveAdapter

ADAPTERS: list[SourceAdapter] = [
    OnlineJobsAdapter(),
    RemotiveAdapter(),
    JobicyAdapter(),
    ArbeitnowAdapter(),
]

__all__ = [
    "ADAPTERS",
    "ArbeitnowAdapter",
    "JobicyAdapter",
    "OnlineJobsAdapter",
    "RemotiveAdapter",
    "SourceAdapter",
    "SourceMeta",
]
