"""Cron hook + Jooble deferral: offline tests, zero network (iron rule 5).

- Jooble fetch self-skips unless GIGGREGATOR_JOOBLE_ENABLED=1 (quota held).
- /cron/ingest is 404 with no secret, 401 on wrong secret, and runs a full
  cycle (fixtures only — adapters' fetch is stubbed) on the right secret.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import FIXTURE_FILES, fixture_bytes
from giggregator import config, db, ingest, web
from giggregator.normalize import utcnow
from giggregator.sources import ADAPTERS

ADAPTER_BY_ID = {a.meta.id: a for a in ADAPTERS}


def test_jooble_fetch_deferred_by_default(monkeypatch):
    monkeypatch.setattr(config, "JOOBLE_ENABLED", False)
    monkeypatch.setattr(config, "JOOBLE_API_KEY", "dummy")
    payload = ADAPTER_BY_ID["jooble_ph"].fetch()
    gigs = ADAPTER_BY_ID["jooble_ph"].parse(payload, utcnow().isoformat())
    assert gigs == []


def test_jooble_fixture_still_parses_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "JOOBLE_ENABLED", True)
    adapter = ADAPTER_BY_ID["jooble_ph"]
    payload = fixture_bytes("jooble_ph/jooble_ph_20260916_01.json")
    assert len(adapter.parse(payload, utcnow().isoformat())) == 20


def _seeded_db(tmp_path):
    path = str(tmp_path / "cron.db")
    conn = db.connect(path)
    db.set_fx(conn, "USD", 58.0, utcnow().isoformat())
    for adapter_id, (folder, filename) in FIXTURE_FILES.items():
        if adapter_id == "jooble_ph":
            continue  # deferred: cron must not burn quota
        adapter = ADAPTER_BY_ID[adapter_id]
        db.upsert_source(conn, adapter.meta.id, adapter.meta.tier, adapter.meta.cadence_hours)
        ingest.ingest_adapter_payload(conn, adapter, fixture_bytes(f"{folder}/{filename}"))
    ingest.rescore_all(conn)
    return path


def test_cron_disabled_without_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGGREGATOR_DB", _seeded_db(tmp_path))
    monkeypatch.setattr(config, "CRON_SECRET", "")
    client = TestClient(web.app)
    assert client.get("/cron/ingest").status_code == 404


def test_cron_auth_and_cycle(tmp_path, monkeypatch):
    monkeypatch.setenv("GIGGREGATOR_DB", _seeded_db(tmp_path))
    monkeypatch.setattr(config, "CRON_SECRET", "test-secret")
    client = TestClient(web.app)
    assert client.get("/cron/ingest").status_code == 401
    assert client.get("/cron/ingest",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401
    # stub network: serve each adapter its committed fixture
    for adapter in ingest.ADAPTERS:
        folder, filename = FIXTURE_FILES[adapter.meta.id]
        data = fixture_bytes(f"{folder}/{filename}")
        adapter.fetch = (lambda d: (lambda: d))(data)
    try:
        resp = client.get("/cron/ingest", headers={"Authorization": "Bearer test-secret"})
    finally:
        for adapter in ingest.ADAPTERS:  # restore bound methods
            del adapter.fetch
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["stored"] >= 0 and body["rescored"] > 0
    assert set(body["sources"]) == {a.meta.id for a in ingest.ADAPTERS}
