"""Remotive adapter — Tier 1, public JSON API (https://remotive.com/api/remote-jobs).

Salary field is annual USD, often k-notation with European decimal commas
("31,2k- $52k") — handled by normalize.parse_pay with default_period=yearly.
"""

from __future__ import annotations

import json
from datetime import datetime

from .. import models, normalize
from .base import SourceAdapter, SourceMeta

FETCH_URL = "https://remotive.com/api/remote-jobs?limit=50"


def _safe_json(payload: str | bytes) -> dict:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return {}


class RemotiveAdapter(SourceAdapter):
    meta = SourceMeta(
        id="remotive", tier=1, cadence_hours=6, default_currency="USD", default_period="yearly"
    )
    fetch_url = FETCH_URL

    def parse(
        self, payload: str | bytes, fetched_at: datetime | None = None
    ) -> list[models.RawListing]:
        now = fetched_at or self.now()
        data = _safe_json(payload)
        listings: list[models.RawListing] = []
        for job in data.get("jobs", []):
            title = normalize.clean(job.get("title"))
            if not title or not job.get("url"):
                continue  # log-and-skip: one bad listing never fails a batch
            tags = ", ".join(job.get("tags") or [])
            body = normalize.strip_html(job.get("description"))
            if tags:
                body = f"{body}\nTags: {tags}"
            # (e): the API's job_type is now structured, not body prose (ADR-0015).
            # Body text is unchanged (the type prose stays as provenance for FTS and
            # requirements); only the structured field is newly populated.
            listings.append(
                models.RawListing(
                    source_id=self.meta.id,
                    url=job["url"],
                    title=title,
                    body=body,
                    company=normalize.clean(job.get("company_name")),
                    posted_at_raw=job.get("publication_date"),
                    pay_raw=normalize.clean(job.get("salary")) or None,
                    location_raw=normalize.clean(job.get("candidate_required_location")),
                    employment_type_raw=normalize.clean(job.get("job_type")),
                    fetched_at=now,
                )
            )
        return listings
