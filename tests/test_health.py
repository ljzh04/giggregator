"""Operator /health endpoint: per-source freshness/health, offline (iron rule 5)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from conftest import FIXTURE_FILES, fixture_bytes
from giggregator import db, ingest, web
from giggregator.normalize import utcnow
from giggregator.sources import ADAPTERS

ADAPTER_BY_ID = {a.meta.id: a for a in ADAPTERS}


def _seeded_db(tmp_path):
    path = str(tmp_path / "health.db")
    conn = db.connect(path)
    db.set_fx(conn, "USD", 58.0, utcnow().isoformat())
    for adapter_id, (folder, filename) in FIXTURE_FILES.items():
        adapter = ADAPTER_BY_ID[adapter_id]
        db.upsert_source(conn, adapter.meta.id, adapter.meta.tier, adapter.meta.cadence_hours)
        ingest.ingest_adapter_payload(conn, adapter, fixture_bytes(f"{folder}/{filename}"))
    ingest.rescore_all(conn)
    return path


def test_health_reports_fresh_sources_when_just_ingested(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGGREGATOR_DB", _seeded_db(tmp_path))
    client = TestClient(web.app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["active_gigs"] > 0
    ids = {s["id"] for s in body["sources"]}
    assert {"onlinejobs_ph", "remotive", "jobicy"} <= ids
    for source in body["sources"]:
        assert source["stale"] is False
        assert source["has_error"] is False
        assert source["reliability"] == 0.8


def test_health_flags_stale_and_errored_sources(tmp_path, monkeypatch):
    path = _seeded_db(tmp_path)
    conn = db.connect(path)
    conn.execute(
        "UPDATE sources SET last_success_at = ? WHERE id = ?",
        ((utcnow() - timedelta(hours=72)).isoformat(), "remotive"),
    )
    db.record_source_error(conn, "jobicy", "boom", utcnow().isoformat())
    conn.commit()

    monkeypatch.setenv("GIGGREGATOR_DB", path)
    body = TestClient(web.app).get("/health").json()
    assert body["ok"] is False
    by_id = {s["id"]: s for s in body["sources"]}
    assert by_id["remotive"]["stale"] is True
    assert by_id["remotive"]["age_hours"] > body["stale_after_hours"]
    assert by_id["jobicy"]["has_error"] is True
    assert by_id["jobicy"]["error_count"] == 1


def test_health_omits_raw_error_text(tmp_path, monkeypatch):
    # adapter error strings can embed key-bearing request URLs -> never expose them
    path = _seeded_db(tmp_path)
    conn = db.connect(path)
    db.record_source_error(
        conn, "jooble_ph", "https://jooble.org/api/SECRET-KEY-123 boom", utcnow().isoformat()
    )
    conn.commit()

    monkeypatch.setenv("GIGGREGATOR_DB", path)
    text = TestClient(web.app).get("/health").text
    assert "SECRET-KEY-123" not in text
    assert "last_error" not in text
