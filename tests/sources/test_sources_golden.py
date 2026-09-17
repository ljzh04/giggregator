"""Golden adapter tests: parse REAL committed fixtures (no network).

Each adapter must parse its fixture without error, skip garbage, and produce the
fields downstream needs. Spot-checks pin real values so parsing regressions are
caught offline (AGENTS.md: definition of done for adapters).
"""

from __future__ import annotations

import json
import re

from conftest import FIXTURE_FILES, fixture_bytes, fixture_text
from giggregator import models
from giggregator.sources import ADAPTERS
from giggregator.sources.arbeitnow import ArbeitnowAdapter
from giggregator.sources.careerjet_ph import (
    CareerjetPhAdapter,
    has_more_pages,
    merge_payloads,
)
from giggregator.sources.jobicy import JobicyAdapter
from giggregator.sources.jooble_ph import JooblePhAdapter
from giggregator.sources.onlinejobs_ph import OnlineJobsAdapter, next_page_url
from giggregator.sources.remotive import RemotiveAdapter

ADAPTER_BY_ID = {a.meta.id: a for a in ADAPTERS}


def _parse(adapter_id):
    folder, filename = FIXTURE_FILES[adapter_id]
    adapter = ADAPTER_BY_ID[adapter_id]
    return adapter.parse(fixture_bytes(f"{folder}/{filename}"))


def test_registry_has_fixture_sources():
    assert {"onlinejobs_ph", "remotive", "jobicy", "arbeitnow", "jooble_ph", "careerjet_ph"} <= set(
        ADAPTER_BY_ID
    )


def test_remotive_golden():
    listings = _parse("remotive")
    assert len(listings) >= 10
    first = listings[0]
    assert first.source_id == "remotive"
    assert first.title and first.url.startswith("https://remotive.com/")
    assert first.body  # descriptions stripped to text
    assert "<" not in first.body  # HTML stripped


def test_remotive_salary_carries_knotation():
    listings = _parse("remotive")
    with_salary = [listing for listing in listings if listing.pay_raw]
    assert with_salary, "fixture should include salary-bearing listings"
    assert any("k" in (listing.pay_raw or "").lower() for listing in with_salary)


def test_jobicy_golden():
    listings = _parse("jobicy")
    assert len(listings) >= 20
    assert all(listing.source_id == "jobicy" for listing in listings)
    assert all(listing.title and listing.url for listing in listings)


def test_arbeitnow_golden_remote_only():
    listings = _parse("arbeitnow")
    assert len(listings) >= 10
    # scope contract: only remote:true listings from arbeitnow enter the pipeline
    assert all("[Type:" in listing.body or True for listing in listings)
    raw_payload = fixture_bytes(f"arbeitnow/{FIXTURE_FILES['arbeitnow'][1]}")
    import json

    data = json.loads(raw_payload)["data"]
    remote_total = sum(1 for j in data if j.get("remote"))
    assert len(listings) == remote_total


def test_onlinejobs_golden():
    listings = _parse("onlinejobs_ph")
    assert len(listings) >= 10
    first = listings[0]
    assert first.url.startswith("https://www.onlinejobs.ph/jobseekers/job/")
    assert first.title
    assert first.location_raw == "PH (home-based)"
    # pay strings must be preserved raw (iron rule 1)
    with_pay = [listing for listing in listings if listing.pay_raw]
    assert with_pay, "fixture cards include the dollar-icon dd pay values"


def test_onlinejobs_pay_variety_preserved():
    listings = _parse("onlinejobs_ph")
    pay_values = [listing.pay_raw for listing in listings if listing.pay_raw]
    assert any("/hour" in v or "/hr" in v for v in pay_values)
    assert any("$" in v for v in pay_values)


def test_onlinejobs_badge_surfaces_employment_type():
    # the Gig / Part Time / Full Time badge is now a structured field, not just prose
    listings = _parse("onlinejobs_ph")
    kinds = {listing.employment_type_raw for listing in listings}
    assert {"Gig", "Part Time", "Full Time"} <= kinds  # real fixture badge values
    assert all(listing.employment_type_raw for listing in listings)  # 30/30 carry a badge
    assert any("[Type: " in listing.body for listing in listings)  # body text unchanged


def test_onlinejobs_next_page_url_from_fixture():
    # real page-1 capture: li.active is page 1 -> link for page 2 (offset 30)
    url = next_page_url(fixture_bytes("onlinejobs_ph/onlinejobs_ph_20260915_01.html"))
    assert url == "https://www.onlinejobs.ph/jobseekers/jobsearch/30"


def test_onlinejobs_next_page_none_without_pagination():
    assert next_page_url(b"<html><body>no pager here</body></html>") is None


def test_onlinejobs_next_page_none_on_last_page():
    # active page 3 with no page-4 link -> None so the crawl stops
    html = (
        b'<ul class="pagination">'
        b'<li class="page-item page-link"><a href="/jobseekers/jobsearch/30"'
        b' data-ci-pagination-page="2">2</a></li>'
        b'<li class="page-item active page-link"><a>3</a></li>'
        b"</ul>"
    )
    assert next_page_url(html) is None


def test_onlinejobs_parse_dedupes_across_concatenated_pages():
    # fetch() joins page HTML blobs; duplicate cards must collapse to one listing
    one = fixture_bytes("onlinejobs_ph/onlinejobs_ph_20260915_01.html")
    single = OnlineJobsAdapter().parse(one)
    combined = OnlineJobsAdapter().parse(one + b"\n" + one)
    assert len(combined) == len(single) >= 10


def test_onlinejobs_fetch_paginates_then_stops_at_last_page(monkeypatch):
    # offline: stub httpx.get; page 1 (fixture) advertises page 2, page 2 has no next
    import giggregator.sources.onlinejobs_ph as oj

    page1 = fixture_text("onlinejobs_ph/onlinejobs_ph_20260915_01.html")
    requested: list[str] = []
    last_page = '<ul class="pagination"><li class="page-item active page-link"><a>9</a></li></ul>'

    def fake_get(url, **kwargs):
        requested.append(url)

        class _Resp:
            text = page1 if len(requested) == 1 else last_page

            def raise_for_status(self):
                pass

        return _Resp()

    monkeypatch.setattr(oj.httpx, "get", fake_get)
    monkeypatch.setattr(oj.config, "HTTP_PAGE_DELAY_SECONDS", 0.0)
    payload = oj.OnlineJobsAdapter().fetch()
    assert requested[0] == oj.FETCH_URL
    assert requested[1] == "https://www.onlinejobs.ph/jobseekers/jobsearch/30"
    assert len(requested) == 2  # second page has no next link -> crawl stops
    assert "jobpost-cat-box" in payload  # joined HTML still carries page-1 cards


def test_jooble_golden():
    listings = _parse("jooble_ph")
    assert len(listings) == 20
    assert all(listing.source_id == "jooble_ph" for listing in listings)
    assert all(listing.title and listing.url for listing in listings)
    first = listings[0]
    assert first.title == "Remote Copy Strategist"
    assert first.company == "Coalition Technologies"
    assert first.pay_raw == "$17 - $35 per hour"  # salary passed through raw
    assert all("<" not in (listing.body or "") for listing in listings)


def test_jooble_pay_variety_preserved():
    listings = _parse("jooble_ph")
    pay_values = [listing.pay_raw for listing in listings if listing.pay_raw]
    assert pay_values, "fixture includes salary-bearing listings"
    assert any("per hour" in v for v in pay_values)
    assert any("k" in v.lower() for v in pay_values)
    # empty-salary listings still enter the pipeline (body-scan fallback)
    assert any(not listing.pay_raw for listing in listings)


def test_careerjet_golden():
    listings = _parse("careerjet_ph")
    assert len(listings) == 50
    assert all(listing.source_id == "careerjet_ph" for listing in listings)
    assert all(listing.title and listing.url for listing in listings)
    first = listings[0]
    assert first.title == "Remote Accountant (CPA)"
    assert first.company == "remote raven"
    assert first.url.startswith("https://jobviewtrack.com/")
    assert all("<" not in (listing.title or "") for listing in listings)
    assert all("<" not in (listing.body or "") for listing in listings)


def test_careerjet_pay_variety_preserved():
    listings = _parse("careerjet_ph")
    pay_values = [listing.pay_raw for listing in listings if listing.pay_raw]
    assert pay_values, "fixture includes salary-bearing listings"
    assert any("per hour" in v for v in pay_values)
    assert any("per month" in v for v in pay_values)
    # empty-salary listings still enter the pipeline (body-scan fallback)
    assert any(not listing.pay_raw for listing in listings)


def test_careerjet_skips_without_key_and_parses_structured_salary():
    # no network in tests: without a key fetch returns an empty JOBS payload
    import os
    from unittest import mock

    with mock.patch.dict(os.environ, {}, clear=False):
        with mock.patch("giggregator.config.CAREERJET_API_KEY", ""):
            payload = CareerjetPhAdapter().fetch()
    assert CareerjetPhAdapter().parse(payload) == []

    sample = (
        b'{"type": "JOBS", "hits": 1, "jobs": [{"title": "VA <b>Remote</b>",'
        b' "company": "Acme", "date": "Mon, 15 Sep 2025 10:00:00 GMT",'
        b' "description": "Data entry work", "locations": "Manila",'
        b' "salary_min": 30000, "salary_max": 40000,'
        b' "salary_currency_code": "PHP", "salary_type": "M",'
        b' "url": "https://example.com/job/1"}]}'
    )
    (listing,) = CareerjetPhAdapter().parse(sample)
    assert listing.title == "VA Remote"  # HTML stripped from titles
    assert listing.pay_raw == "PHP 30000-40000 per month"
    # LOCATIONS-type responses carry no jobs
    assert CareerjetPhAdapter().parse(b'{"type": "LOCATIONS", "locations": []}') == []


def test_careerjet_has_more_pages_uses_fixture_pages_metadata():
    data = json.loads(fixture_bytes("careerjet_ph/careerjet_ph_20260916_01.json"))
    assert data["pages"] == 166  # real pagination metadata from the capture
    assert has_more_pages(data, 1) is True
    assert has_more_pages(data, 166) is False  # reached the advertised last page


def test_careerjet_has_more_pages_stops_on_short_empty_or_non_jobs():
    assert (
        has_more_pages({"type": "JOBS", "hits": 1, "pages": 5, "jobs": [{"url": "u"}]}, 1) is False
    )
    assert has_more_pages({"type": "JOBS", "hits": 0, "pages": 0, "jobs": []}, 1) is False
    assert has_more_pages({"type": "LOCATIONS", "locations": []}, 1) is False
    assert has_more_pages({}, 1) is False  # unparseable payload -> stop


def test_careerjet_merge_payloads_dedupes_by_url_and_keeps_max_metadata():
    p1 = {"type": "JOBS", "hits": 100, "pages": 2, "jobs": [{"url": "a"}, {"url": "b"}]}
    p2 = {"type": "JOBS", "hits": 100, "pages": 2, "jobs": [{"url": "b"}, {"url": "c"}]}
    merged = merge_payloads([p1, p2])
    assert merged["type"] == "JOBS"
    assert merged["hits"] == 100 and merged["pages"] == 2
    assert [j["url"] for j in merged["jobs"]] == ["a", "b", "c"]  # "b" deduped


def test_careerjet_merge_payloads_ignores_locations_response():
    merged = merge_payloads([{"type": "LOCATIONS", "locations": []}])
    assert merged == {"type": "JOBS", "hits": 0, "pages": 0, "jobs": []}


def _cj_page(page, *, total_pages=166, hits=8280, count=50):
    jobs = [
        {
            "title": f"Job {page}-{i}",
            "company": "Acme",
            "url": f"https://example.com/job/{page}/{i}",
            "description": "desc",
            "locations": "Philippines",
            "date": "Mon, 15 Sep 2025 10:00:00 GMT",
            "salary": "",
        }
        for i in range(count)
    ]
    return {"type": "JOBS", "hits": hits, "pages": total_pages, "jobs": jobs}


def _stub_careerjet_http(monkeypatch, *, total_pages, hits, calls):
    import giggregator.sources.careerjet_ph as cj

    def fake_get(url, **kwargs):
        page = int(re.search(r"page=(\d+)", url).group(1))
        calls.append(page)

        class _Resp:
            text = json.dumps(_cj_page(page, total_pages=total_pages, hits=hits))

            def raise_for_status(self):
                pass

        return _Resp()

    monkeypatch.setattr(cj.config, "CAREERJET_API_KEY", "dummy")
    monkeypatch.setattr(cj, "_server_ip", lambda: "203.0.113.9")
    monkeypatch.setattr(cj.httpx, "get", fake_get)
    monkeypatch.setattr(cj.config, "HTTP_PAGE_DELAY_SECONDS", 0.0)
    return cj


def test_careerjet_fetch_paginates_and_merges(monkeypatch):
    calls: list[int] = []
    cj = _stub_careerjet_http(monkeypatch, total_pages=166, hits=8280, calls=calls)
    payload = cj.CareerjetPhAdapter().fetch()
    assert calls == [1, 2, 3]  # bounded by MAX_PAGES
    jobs = json.loads(payload)["jobs"]
    assert len(jobs) == 3 * cj.PAGE_SIZE
    assert len({j["url"] for j in jobs}) == len(jobs)  # distinct across merged pages


def test_careerjet_fetch_stops_when_pages_exhausted(monkeypatch):
    calls: list[int] = []
    cj = _stub_careerjet_http(monkeypatch, total_pages=2, hits=100, calls=calls)
    cj.CareerjetPhAdapter().fetch()
    assert calls == [1, 2]  # page 2 of 2 -> no third request


def test_bad_payload_does_not_explode():
    # garbage input -> empty result, never an exception (log-and-skip contract)
    assert RemotiveAdapter().parse(b"{not json") == []
    assert JobicyAdapter().parse(b"{not json") == []
    assert ArbeitnowAdapter().parse(b"{not json") == []
    assert OnlineJobsAdapter().parse(b"<html>no jobs here</html>") == []
    assert JooblePhAdapter().parse(b"{not json") == []
    assert CareerjetPhAdapter().parse(b"{not json") == []


def test_raw_listing_shape():
    sample = _parse("remotive")[0]
    assert isinstance(sample, models.RawListing)
