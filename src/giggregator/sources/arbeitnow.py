"""Arbeitnow adapter — Tier 1, free JSON API (https://www.arbeitnow.com/api/job-board-api).

Note: `published_at` is often null in practice; we fall back to `created_at` then
fetched_at (freshness treats unknown age conservatively — see score.freshness).
"""

from __future__ import annotations

import json
from datetime import datetime

from .. import models, normalize
from .base import SourceAdapter, SourceMeta

FETCH_URL = "https://www.arbeitnow.com/api/job-board-api"


def _safe_json(payload: str | bytes) -> dict:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return {}


class ArbeitnowAdapter(SourceAdapter):
    meta = SourceMeta(id="arbeitnow", tier=1, cadence_hours=12, default_currency="USD",
                      default_period="yearly")
    fetch_url = FETCH_URL

    def parse(self, payload: str | bytes, fetched_at: datetime | None = None) -> list[models.RawListing]:
        now = fetched_at or self.now()
        data = _safe_json(payload)
        listings: list[models.RawListing] = []
        for job in data.get("data", []):
            title = normalize.clean(job.get("title"))
            if not title or not job.get("url"):
                continue
            if not job.get("remote"):
                continue  # scope contract: remote-only enters the pipeline
            body = normalize.strip_html(job.get("description"))
            job_types = ", ".join(job.get("job_types") or [])
            if job_types:
                body = f"[Type: {job_types}]\n{body}"
            listings.append(
                models.RawListing(
                    source_id=self.meta.id,
                    url=job["url"],
                    title=title,
                    body=body,
                    company=normalize.clean(job.get("company_name")),
                    posted_at_raw=job.get("published_at") or job.get("created_at"),
                    pay_raw=normalize.clean(job.get("salary")) or None,
                    location_raw=normalize.clean(job.get("location")),
                    fetched_at=now,
                )
            )
        return listings
