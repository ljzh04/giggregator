"""Jooble PH adapter — Tier 1, publisher JSON API.

Endpoint: POST https://jooble.org/api/{KEY} with a JSON body
(``keywords`` + ``location`` required). ``location="Philippines"`` scopes to PH;
``keywords="remote"`` keeps the scope contract (WFH/online work).

Quota: the free key is limited to 500 lifetime requests, so Jooble ingest is
DEFERRED by default (``GIGGREGATOR_JOOBLE_ENABLED=1`` re-enables one small page
of ``resultOnPage=20`` per cycle). Fixtures are committed so tests never touch
the quota. No key in code: without ``GIGGREGATOR_JOOBLE_KEY`` fetch skips itself
with an empty payload so ingest stays green pre-key.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

import httpx

from .. import config, models, normalize
from .base import SourceAdapter, SourceMeta

API_URL = "https://jooble.org/api/{key}"
LOCATION = "Philippines"
KEYWORDS = "remote"
RESULT_ON_PAGE = 20


def _safe_json(payload: str | bytes) -> dict:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return {}


class JooblePhAdapter(SourceAdapter):
    meta = SourceMeta(
        id="jooble_ph", tier=1, cadence_hours=24, default_currency="PHP", default_period="monthly"
    )
    fetch_url = API_URL.format(key="{key}")

    def fetch(self) -> str | bytes:
        if not config.JOOBLE_ENABLED:
            print(
                "[jooble_ph] SKIP: deferred (set GIGGREGATOR_JOOBLE_ENABLED=1 to re-enable)",
                file=sys.stderr,
            )
            return b'{"totalCount": 0, "jobs": []}'
        if not config.JOOBLE_API_KEY:
            print("[jooble_ph] SKIP: no GIGGREGATOR_JOOBLE_KEY in env", file=sys.stderr)
            return b'{"totalCount": 0, "jobs": []}'
        # One small page per cycle: the free key allows 500 lifetime requests.
        body = {
            "keywords": KEYWORDS,
            "location": LOCATION,
            "resultOnPage": RESULT_ON_PAGE,
            "page": 1,
        }
        response = httpx.post(
            API_URL.format(key=config.JOOBLE_API_KEY),
            json=body,
            headers={"Content-Type": "application/json", "User-Agent": config.HTTP_USER_AGENT},
            timeout=config.HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text

    def parse(
        self, payload: str | bytes, fetched_at: datetime | None = None
    ) -> list[models.RawListing]:
        now = fetched_at or self.now()
        data = _safe_json(payload)
        listings: list[models.RawListing] = []
        for job in data.get("jobs", []):
            title = normalize.strip_html(job.get("title"))
            if not title or not job.get("link"):
                continue  # log-and-skip: one bad listing never fails a batch
            pay = normalize.clean(job.get("salary"))
            job_type = normalize.clean(job.get("type"))
            listings.append(
                models.RawListing(
                    source_id=self.meta.id,
                    url=job["link"],
                    title=title,
                    body=normalize.strip_html(job.get("snippet")),
                    company=normalize.clean(job.get("company")),
                    posted_at_raw=job.get("updated"),
                    pay_raw=pay or None,
                    location_raw=normalize.clean(job.get("location")) or LOCATION,
                    employment_type_raw=job_type,
                    fetched_at=now,
                )
            )
        return listings
