"""Source adapter base: the contract from docs/SOURCES.md.

`parse()` is pure and testable against fixtures (no network); `fetch()` is the only
impure boundary and stays thin.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import httpx

from .. import config, models
from ..normalize import utcnow


@dataclass
class SourceMeta:
    id: str
    tier: int
    cadence_hours: int
    default_currency: str | None = None
    default_period: str | None = None


class SourceAdapter(ABC):
    meta: SourceMeta
    fetch_url: str

    def fetch(self) -> str | bytes:
        """Politeness: single request, browser-ish UA, hard timeout. No retries in MVP."""
        response = httpx.get(
            self.fetch_url,
            headers={"User-Agent": config.HTTP_USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text

    @abstractmethod
    def parse(self, payload: str | bytes, fetched_at: datetime | None = None) -> list[models.RawListing]:
        """Pure: payload (already fetched) -> RawListings. Golden tests run this."""

    def now(self) -> datetime:
        return utcnow()
