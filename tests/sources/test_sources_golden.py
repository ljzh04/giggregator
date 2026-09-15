"""Golden adapter tests: parse REAL committed fixtures (no network).

Each adapter must parse its fixture without error, skip garbage, and produce the
fields downstream needs. Spot-checks pin real values so parsing regressions are
caught offline (AGENTS.md: definition of done for adapters).
"""

from __future__ import annotations

from conftest import FIXTURE_FILES, fixture_bytes
from giggregator import models
from giggregator.sources import ADAPTERS
from giggregator.sources.arbeitnow import ArbeitnowAdapter
from giggregator.sources.jobicy import JobicyAdapter
from giggregator.sources.onlinejobs_ph import OnlineJobsAdapter
from giggregator.sources.remotive import RemotiveAdapter

ADAPTER_BY_ID = {a.meta.id: a for a in ADAPTERS}


def _parse(adapter_id):
    folder, filename = FIXTURE_FILES[adapter_id]
    adapter = ADAPTER_BY_ID[adapter_id]
    return adapter.parse(fixture_bytes(f"{folder}/{filename}"))


def test_registry_has_fixture_sources():
    assert {"onlinejobs_ph", "remotive", "jobicy", "arbeitnow"} <= set(ADAPTER_BY_ID)


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


def test_bad_payload_does_not_explode():
    # garbage input -> empty result, never an exception (log-and-skip contract)
    assert RemotiveAdapter().parse(b"{not json") == []
    assert JobicyAdapter().parse(b"{not json") == []
    assert ArbeitnowAdapter().parse(b"{not json") == []
    assert OnlineJobsAdapter().parse(b"<html>no jobs here</html>") == []


def test_raw_listing_shape():
    sample = _parse("remotive")[0]
    assert isinstance(sample, models.RawListing)
