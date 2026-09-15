"""Live check of the configured DB backend (ADR-0011).

With TURSO_DATABASE_URL set: round-trips one probe gig through the remote Turso/libSQL
database and removes it. Without it: same round-trip against the local SQLite file.
Run: uv run --env-file .env python scripts/db_check.py
"""

from __future__ import annotations

import os

from giggregator import db, models
from giggregator.normalize import utcnow

conn = db.connect(os.environ.get("GIGGREGATOR_DB", "giggregator.db"))
backend = "remote (Turso/libSQL)" if os.environ.get("TURSO_DATABASE_URL") else "local sqlite"
print(f"backend: {backend}")

gig = models.Gig(
    source_id="remotive",
    url="https://example.com/probe-gig",
    title="Probe Gig zzverify",
    body="probe listing written by scripts/db_check.py",
    company="Probe Co",
    posted_at=utcnow(),
    first_seen_at=utcnow(),
)
gig.dedupe_key = "db-check-probe"
gid = db.upsert_gig(conn, gig)
print("upsert via lastrowid:", gid)

row = conn.execute("SELECT * FROM gigs WHERE dedupe_key = ?", ("db-check-probe",)).fetchone()
assert row is not None, "probe row not found"
assert row["title"] == "Probe Gig zzverify"
print(f"name access: title={row['title']!r} company={row['company']!r}")

ids = db.search_gig_ids(conn, "zzverify")
print("FTS search hits:", ids)
assert gid in ids, "FTS5 did not find the probe gig"

found = db.get_gig(conn, gid)
assert found is not None and found.title == "Probe Gig zzverify"
print("get_gig round-trip: OK")

conn.execute("DELETE FROM gigs WHERE id = ?", (gid,))
conn.commit()
left = conn.execute(
    "SELECT COUNT(*) AS c FROM gigs WHERE dedupe_key = ?", ("db-check-probe",)
).fetchone()["c"]
assert left == 0
print("cleanup: OK")
print("PASS")
