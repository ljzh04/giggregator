"""CareerJet PH adapter — Tier 1, publisher JSON API.

Endpoint: GET https://search.api.careerjet.net/v4/query with HTTP Basic auth
(API key as username, empty password). Locale ``en_PH`` + ``location=Philippines``
scopes results to PH; ``keywords=remote`` keeps the scope contract (WFH/online work).

Required per-request params ``user_ip``/``user_agent`` are the *end-user* values;
a backend ingest has no end user, so ``user_agent`` is our bot UA and ``user_ip``
is the server's own egress IP (``GIGGREGATOR_CAREERJET_USER_IP`` override wins,
else one cached api.ipify.org lookup per process). No key in code: without ``GIGGREGATOR_CAREERJET_KEY``
fetch skips itself with an empty JOBS payload so ingest stays green pre-key.

Structured salary fields (salary_min/max, salary_currency_code, salary_type
Y/M/W/D/H) are re-serialized into a raw pay string so the shared pay parser
stays the single normalizer (same convention as the Jobicy adapter).
"""

from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime
from urllib.parse import urlencode

import httpx

from .. import config, models, normalize
from .base import SourceAdapter, SourceMeta

API_URL = "https://search.api.careerjet.net/v4/query"
LOCALE = "en_PH"
LOCATION = "Philippines"
KEYWORDS = "remote"
PAGE_SIZE = 50

SALARY_PERIOD = {"Y": "year", "M": "month", "W": "week", "D": "day", "H": "hour"}

# CareerJet requires user_ip on every call. A backend ingest has no end user,
# so we send the server's own egress IP: explicit env override wins, else one
# cached best-effort lookup per process.
_server_ip_cache: str | None = None


def _server_ip() -> str:
    global _server_ip_cache
    if _server_ip_cache is not None:
        return _server_ip_cache
    override = os.environ.get("GIGGREGATOR_CAREERJET_USER_IP", "").strip()
    if override:
        _server_ip_cache = override
        return override
    try:
        response = httpx.get("https://api.ipify.org", timeout=5.0)
        _server_ip_cache = response.text.strip() if response.is_success else ""
    except httpx.HTTPError:
        _server_ip_cache = ""
    return _server_ip_cache


def _salary_raw(job: dict) -> str | None:
    low, high = job.get("salary_min"), job.get("salary_max")
    if low or high:
        currency = job.get("salary_currency_code") or "PHP"
        period = SALARY_PERIOD.get(job.get("salary_type") or "", "month")
        if low and high:
            return f"{currency} {low}-{high} per {period}"
        return f"{currency} {low or high} per {period}"
    text = normalize.clean(job.get("salary"))
    return text or None


def _safe_json(payload: str | bytes) -> dict:
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, ValueError):
        return {}


class CareerjetPhAdapter(SourceAdapter):
    meta = SourceMeta(
        id="careerjet_ph", tier=1, cadence_hours=6, default_currency="PHP", default_period="monthly"
    )
    fetch_url = API_URL

    def fetch(self) -> str | bytes:
        if not config.CAREERJET_API_KEY:
            print("[careerjet_ph] SKIP: no GIGGREGATOR_CAREERJET_KEY in env", file=sys.stderr)
            return b'{"type": "JOBS", "hits": 0, "jobs": []}'
        token = base64.b64encode(f"{config.CAREERJET_API_KEY}:".encode()).decode()
        params = {
            "locale_code": LOCALE,
            "keywords": KEYWORDS,
            "location": LOCATION,
            "sort": "relevance",
            "page": 1,
            "pagesize": PAGE_SIZE,
            "user_agent": config.HTTP_USER_AGENT,
        }
        if config.CAREERJET_AFFILIATE_ID:
            params["affid"] = config.CAREERJET_AFFILIATE_ID
        params["user_ip"] = _server_ip()
        response = httpx.get(
            API_URL + "?" + urlencode(params),
            headers={
                "Authorization": f"Basic {token}",
                "User-Agent": config.HTTP_USER_AGENT,
                "Referer": config.CAREERJET_REFERER,
            },
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
        if data.get("type") == "LOCATIONS":
            return []  # location disambiguation response carries no jobs
        listings: list[models.RawListing] = []
        for job in data.get("jobs", []):
            title = normalize.strip_html(job.get("title"))
            if not title or not job.get("url"):
                continue  # log-and-skip: one bad listing never fails a batch
            locations = job.get("locations") or []
            listings.append(
                models.RawListing(
                    source_id=self.meta.id,
                    url=job["url"],
                    title=title,
                    body=normalize.strip_html(job.get("description")),
                    company=normalize.clean(job.get("company")),
                    posted_at_raw=job.get("date"),
                    pay_raw=_salary_raw(job),
                    location_raw=", ".join(locations) if locations else LOCATION,
                    fetched_at=now,
                )
            )
        return listings
