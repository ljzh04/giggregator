"""Ingest CLI: fetch -> parse -> enrich -> dedupe/store -> rescore.

Usage:
    uv run python -m giggregator.ingest --once [--db giggregator.db]

Network only happens in adapter.fetch(); parse/enrich/store are offline and unit-tested.
"""

from __future__ import annotations

import argparse
import sys

from . import config, db, dedupe, enrich, score
from .normalize import utcnow
from .sources import ADAPTERS, SourceAdapter


def ingest_adapter_payload(
    conn, adapter: SourceAdapter, payload: str | bytes, fetched_at=None
) -> tuple[int, int]:
    """Pure-ish core: parse payload + store + rescore. Used by CLI and golden tests."""
    now = fetched_at or utcnow()
    listings = adapter.parse(payload, fetched_at=now)
    stored = 0
    for raw in listings:
        try:
            gig = enrich.enrich(raw, fx=db.get_fx(conn) or config.USD_PHP_FALLBACK)
        except Exception as exc:  # log-and-skip: one bad listing never fails a batch
            db.record_source_error(conn, adapter.meta.id, repr(exc), now.isoformat())
            continue
        gig.dedupe_key = dedupe.dedupe_key(gig.company, gig.title)
        db.upsert_gig(conn, gig)
        stored += 1
    db.record_source_success(conn, adapter.meta.id, now.isoformat(), stored)
    return len(listings), stored


def rescore_all(conn, weights: dict[str, float] | None = None) -> int:
    now = utcnow()
    corpus = db.corpus_pay(conn)
    count = 0
    for row in conn.execute("SELECT * FROM gigs WHERE status = 'active'").fetchall():
        gig = db.gig_from_row(row)
        result = score.score_gig(gig, corpus, now, weights=weights)
        db.save_scores(conn, int(row["id"]), result)
        count += 1
    return count


def run(db_path: str = "giggregator.db") -> int:
    conn = db.connect(db_path)
    db.set_fx(conn, "USD", config.USD_PHP_FALLBACK, utcnow().isoformat())
    total = 0
    for adapter in ADAPTERS:
        db.upsert_source(conn, adapter.meta.id, adapter.meta.tier, adapter.meta.cadence_hours)
        try:
            payload = adapter.fetch()
            parsed, stored = ingest_adapter_payload(conn, adapter, payload)
            print(f"[{adapter.meta.id}] parsed={parsed} stored={stored}")
            total += stored
        except Exception as exc:
            print(f"[{adapter.meta.id}] ERROR: {exc}", file=sys.stderr)
            db.record_source_error(conn, adapter.meta.id, repr(exc), utcnow().isoformat())
    expired = db.expire_stale_gigs(conn)
    rescored = rescore_all(conn)
    print(f"stored={total} rescored={rescored} expired={expired} flagged={db.flagged_count(conn)}")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(prog="giggregator.ingest")
    parser.add_argument("--once", action="store_true", help="run one ingest cycle (MVP default)")
    parser.add_argument("--db", default="giggregator.db", help="sqlite db path")
    args = parser.parse_args()
    run(args.db)


if __name__ == "__main__":
    main()
