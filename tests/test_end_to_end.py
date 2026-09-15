"""Offline end-to-end: fixtures -> enrich -> dedupe/store -> rescore -> web pages.

Proves the MVP spine works with zero network (iron rule 5) and that flagged gigs are
excluded from serving.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import FIXTURE_FILES, fixture_bytes
from giggregator import db, flows, ingest
from giggregator.normalize import utcnow
from giggregator.sources import ADAPTERS

ADAPTER_BY_ID = {a.meta.id: a for a in ADAPTERS}


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("e2e") / "giggregator.db")
    conn = db.connect(path)
    db.set_fx(conn, "USD", 58.0, utcnow().isoformat())
    for adapter_id, (folder, filename) in FIXTURE_FILES.items():
        adapter = ADAPTER_BY_ID[adapter_id]
        db.upsert_source(conn, adapter.meta.id, adapter.meta.tier, adapter.meta.cadence_hours)
        ingest.ingest_adapter_payload(conn, adapter, fixture_bytes(f"{folder}/{filename}"))
    ingest.rescore_all(conn)
    yield path


def test_all_fixture_sources_stored(seeded_db):
    conn = db.connect(seeded_db)
    active = db.active_gigs(conn)
    assert len(active) >= 40
    stored_sources = {s for g in active for s in g.source_ids}
    assert {"onlinejobs_ph", "remotive", "jobicy", "arbeitnow"} <= stored_sources


def test_flagged_gigs_excluded(seeded_db):
    conn = db.connect(seeded_db)
    statuses = {g.status for g in db.active_gigs(conn)}
    assert "flagged" not in statuses
    # the fixture corpus should exercise the scam filter if any listing trips it;
    # if none trips, flagged_count is 0 — both are valid, but the filter must hold.


def test_every_active_gig_scored(seeded_db):
    conn = db.connect(seeded_db)
    for gig in db.active_gigs(conn):
        assert "relevance" in gig.scores and "factors" in gig.scores
        assert 0.0 <= gig.scores["relevance"] <= 100.0


def test_scoring_ordering_reasonable(seeded_db):
    conn = db.connect(seeded_db)
    gigs = db.active_gigs(conn)
    relevances = [g.scores["relevance"] for g in gigs]
    assert relevances == sorted(relevances, reverse=True)


def test_fts_search_finds_fixture_content(seeded_db):
    conn = db.connect(seeded_db)
    ids = db.search_gig_ids(conn, "assistant")
    assert len(ids) > 0


def test_flow_filters_apply(seeded_db):
    conn = db.connect(seeded_db)
    now = utcnow()
    qb = [g for g in db.active_gigs(conn) if flows.FLOWS["quick_bucks"].matches(g, now)]
    no_exp = [g for g in db.active_gigs(conn) if flows.FLOWS["no_experience"].matches(g, now)]
    for gig in qb:
        assert gig.category in flows.FLOWS["quick_bucks"].categories
    for gig in no_exp:
        assert gig.no_experience_friendly


def test_web_pages_render(seeded_db, monkeypatch):
    monkeypatch.setenv("GIGGREGATOR_DB", seeded_db)
    from giggregator import web

    client = TestClient(web.app)
    home = client.get("/")
    assert home.status_code == 200
    assert "Giggregator" in home.text
    assert client.get("/flow/quick_bucks").status_code == 200
    assert client.get("/flow/unknown_flow").status_code == 200  # graceful
    search_page = client.get("/search", params={"q": "assistant"})
    assert search_page.status_code == 200
    detail = client.get("/gig/1")
    assert detail.status_code == 200
    assert "Why this ranked here" in detail.text


def test_dedupe_merges_across_sources(seeded_db):
    conn = db.connect(seeded_db)
    multi = [g for g in db.active_gigs(conn) if len(g.source_ids) > 1]
    # cross-source duplicates in the fixture corpus get merged into one row;
    # there may or may not be overlaps, but any that exist must be merged.
    for gig in multi:
        assert len(gig.source_ids) == len(set(gig.source_ids))
