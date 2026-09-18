"""Jobicy adapter — Tier 1, free JSON API (https://jobicy.com/api/v2/remote-jobs).

Structured salary fields (salaryMin/Max/Currency/Period); we re-serialize into a raw
pay string so the shared pay parser stays the single normalizer.
"""

from __future__ import annotations

import json
from datetime import datetime

from .. import models, normalize
from .base import SourceAdapter, SourceMeta

FETCH_URL = "https://jobicy.com/api/v2/remote-jobs?count=50"


def _salary_raw(job: dict) -> str | None:
    low, high = job.get("salaryMin"), job.get("salaryMax")
    currency = job.get("salaryCurrency") or "USD"
    period = {
        "yearly": "year",
        "monthly": "month",
        "weekly": "week",
        "hourly": "hour",
        "daily": "day",
    }.get(job.get("salaryPeriod") or "", "year")
    if not low and not high:
        return None
    if low and high:
        return f"{currency} {low}-{high} per {period}"
    return f"{currency} {low or high} per {period}"


def _safe_json(payload: str | bytes) -> dict:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return {}


class JobicyAdapter(SourceAdapter):
    meta = SourceMeta(
        id="jobicy", tier=1, cadence_hours=6, default_currency="USD", default_period="yearly"
    )
    fetch_url = FETCH_URL

    def parse(
        self, payload: str | bytes, fetched_at: datetime | None = None
    ) -> list[models.RawListing]:
        now = fetched_at or self.now()
        data = _safe_json(payload)
        listings: list[models.RawListing] = []
        for job in data.get("jobs", []):
            title = normalize.clean(job.get("jobTitle"))
            if not title or not job.get("url"):
                continue
            # The API's jobType is structured (promoted to employment_type_raw per
            # ADR-0015); it stays in the body too as provenance for FTS/rules.
            body = normalize.strip_html(job.get("jobDescription") or job.get("jobExcerpt"))
            job_types = ", ".join(job.get("jobType") or [])
            if job_types:
                body = f"[Type: {job_types}]\n{body}"
            listings.append(
                models.RawListing(
                    source_id=self.meta.id,
                    url=job["url"],
                    title=title,
                    body=body,
                    company=normalize.clean(job.get("companyName")),
                    posted_at_raw=job.get("pubDate"),
                    pay_raw=_salary_raw(job),
                    location_raw=normalize.clean(job.get("jobGeo")),
                    employment_type_raw=job_types,
                    fetched_at=now,
                )
            )
        return listings
