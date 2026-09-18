"""OnlineJobs.ph adapter — Tier 1, PH remote-work epicenter (home-based listings page).

Parses the public job-search HTML (fixture: tests/fixtures/sources/onlinejobs_ph/).
Card structure (verified against fixture 2026-09-15):
  <a href="/jobseekers/job/<slug>"> wrapping div.jobpost-cat-box with:
    h4 title (+ badge: Gig / Part Time / Full time)
    p[data-temp-2] -> posted UTC datetime
    dd after the dollar icon -> pay string (unit-ambiguous, see below)
    div.desc -> excerpt body; .job-tag badges -> tags

Pay unit convention (documented heuristic, fixture MANIFEST.md): explicit '$'/USD stays
USD; bare numbers use the site's hourly convention — <20 treated as USD, >=20 as PHP.
Confidence is penalized for inferred currency/period by parse_pay; scoring shrinks
low-confidence pay toward the corpus median, so mis-guesses degrade gracefully.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .. import config, models, normalize
from .base import SourceAdapter, SourceMeta

FETCH_URL = "https://www.onlinejobs.ph/jobseekers/jobsearch"
BASE_URL = "https://www.onlinejobs.ph"

_PAY_DD = re.compile(r"icon-round-dollar[\s\S]{0,220}?<dd[^>]*>([\s\S]{1,80}?)</dd>", re.I)

# Politeness bound: page 1 + up to 2 more (OnlineJobs shows ~30 cards per page).
MAX_PAGES = 3


def next_page_url(html_text: str | bytes) -> str | None:
    """Absolute URL of the next results page, or None on the last page.

    OnlineJobs paginates CodeIgniter-style: <ul class="pagination"> holds the current
    page in li.active and later pages as <a href="/jobseekers/jobsearch/<offset>"
    data-ci-pagination-page="N">. Read the active page number and return the link for
    N+1. Pure function, so multi-page behaviour is fixture-testable offline.
    """
    soup = BeautifulSoup(html_text, "html.parser")
    pager = soup.select_one("ul.pagination")
    if pager is None:
        return None
    active = pager.select_one("li.active")
    current = 1
    if active is not None:
        try:
            current = int(normalize.clean(active.get_text()))
        except ValueError:
            current = 1
    link = pager.select_one(f'a[data-ci-pagination-page="{current + 1}"]')
    href = link.get("href") if link is not None else None
    return urljoin(BASE_URL, href) if href else None


class OnlineJobsAdapter(SourceAdapter):
    meta = SourceMeta(id="onlinejobs_ph", tier=1, cadence_hours=2)
    fetch_url = FETCH_URL

    def fetch(self) -> str | bytes:
        """Fetch up to MAX_PAGES result pages and concatenate their HTML so parse()
        sees every card (parse dedupes by URL). Rate-limited between requests per the
        adapter contract; stops early when next_page_url() reports the last page.
        """
        pages: list[str] = []
        url: str | None = FETCH_URL
        for page_index in range(MAX_PAGES):
            if url is None:
                break
            response = httpx.get(
                url,
                headers={"User-Agent": config.HTTP_USER_AGENT},
                timeout=config.HTTP_TIMEOUT_SECONDS,
                follow_redirects=True,
            )
            response.raise_for_status()
            pages.append(response.text)
            url = next_page_url(response.text)
            if url is not None and page_index < MAX_PAGES - 1:
                time.sleep(config.HTTP_PAGE_DELAY_SECONDS)
        return "\n".join(pages)

    def parse(
        self, payload: str | bytes, fetched_at: datetime | None = None
    ) -> list[models.RawListing]:
        now = fetched_at or self.now()
        soup = BeautifulSoup(payload, "html.parser")
        listings: list[models.RawListing] = []
        seen_urls: set[str] = set()
        for anchor in soup.select('a[href^="/jobseekers/job/"]'):
            href = anchor.get("href", "")
            if href in seen_urls:
                continue
            seen_urls.add(href)
            box = anchor.select_one("div.jobpost-cat-box")
            if box is None:
                continue
            title_tag = box.find("h4")
            if title_tag is None:
                continue
            # (f): strip the employment badge at the DOM level, not via string replace
            # on the already-stripped text — the old replace() matched the serialized
            # <span> HTML against plain text and was a silent no-op, leaving the badge
            # ("... Full Time") duplicated in every title and dedupe key.
            badge_tag = title_tag.select_one("span.badge")
            listing_type = normalize.clean(badge_tag.get_text()) if badge_tag else ""
            if badge_tag is not None:
                badge_tag.decompose()
            title = normalize.clean(title_tag.get_text(" ", strip=True))

            body_parts: list[str] = []
            if listing_type:
                body_parts.append(f"[Type: {listing_type}]")
            for tag_link in box.select(".job-tag a"):
                body_parts.append(f"[Tag: {normalize.clean(tag_link.get_text())}]")
            desc = box.select_one("div.desc")
            if desc:
                body_parts.append(normalize.clean(desc.get_text(" ", strip=True)))

            pay_dd = _PAY_DD.search(str(box))
            pay_raw = normalize.clean(pay_dd.group(1)) if pay_dd else None
            if pay_raw and not re.search(r"[$₱]|usd|php|peso", pay_raw, re.I):
                first_number = re.search(r"\d[\d,.]*", pay_raw)
                if first_number:
                    marker = (
                        "$"
                        if len(first_number.group()) <= 5
                        and float(first_number.group().rstrip(".,").replace(",", "") or 0) < 20
                        else "PHP "
                    )
                    pay_raw = f"{marker}{pay_raw}"

            posted = None
            posted_p = box.select_one("p[data-temp-2]")
            if posted_p is not None:
                posted = normalize.parse_dt(posted_p.get("data-temp-2"))

            listings.append(
                models.RawListing(
                    source_id=self.meta.id,
                    url=urljoin(BASE_URL, href),
                    title=title,
                    body="\n".join(body_parts),
                    company="",  # card view hides employer name; detail crawl comes later
                    posted_at_raw=posted.isoformat() if posted else None,
                    pay_raw=pay_raw,
                    location_raw="PH (home-based)",
                    employment_type_raw=listing_type,
                    fetched_at=now,
                )
            )
        return listings
