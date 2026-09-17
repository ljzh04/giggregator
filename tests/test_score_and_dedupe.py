"""Scoring math tests (ADR-0007) + dedupe/db merge behavior."""

from __future__ import annotations

import json
from datetime import timedelta

from giggregator import db, dedupe, enrich, ingest, models, score
from giggregator.normalize import utcnow


def test_freshness_halving():
    now = utcnow()
    assert score.freshness(now - timedelta(days=0), now) == 1.0
    assert score.freshness(now - timedelta(days=7), now) == 0.5
    assert score.freshness(now - timedelta(days=14), now) == 0.25
    assert score.freshness(None, now) == 0.3


def test_freshness_zero_for_ancient():
    now = utcnow()
    assert score.freshness(now - timedelta(days=90), now) < 0.01


def test_pay_percentile_and_shrink():
    corpus = [100.0, 200.0, 300.0]
    assert score.pay_percentile(200.0, corpus) == 0.5
    assert score.pay_percentile(100.0, corpus) == 0.0
    assert score.pay_percentile(400.0, corpus) == 1.0
    assert score.pay_percentile(None, corpus) is None
    # full confidence -> raw percentile; zero confidence -> median proxy
    assert score.pay_factor(0.9, 1.0) == 0.9
    assert score.pay_factor(0.9, 0.0) == 0.5
    assert score.pay_factor(None, 0.8) == 0.4  # unknown-pay baseline


def test_effort_fast_payout_beats_slow():
    req = models.Requirements()
    fast = score.effort_factor(models.PAYOUT_INSTANT, req, False)
    slow = score.effort_factor(models.PAYOUT_MONTHLY, req, False)
    assert fast > slow


def test_effort_commitment_penalty():
    committed = models.Requirements(hours=models.HOURS_FIXED, min_hours_per_week=40)
    flex = models.Requirements(hours=models.HOURS_FLEX)
    assert score.effort_factor(models.PAYOUT_MONTHLY, flex, True) > score.effort_factor(
        models.PAYOUT_MONTHLY, committed, False
    )


def test_trust_soft_flags_penalize_but_hard_excluded_upstream():
    assert score.trust_factor(0.8, []) == 0.8
    assert score.trust_factor(0.8, ["spam_repost"]) == 0.7
    assert score.trust_factor(0.8, ["fee_required"]) == 0.8  # handled by exclusion, not score


def test_relevance_weighted_sum():
    factors = {"pay": 1.0, "fresh": 1.0, "effort": 1.0, "match": 1.0, "trust": 1.0}
    assert score.relevance(factors) == 100.0
    factors_zero = {k: 0.0 for k in factors}
    assert score.relevance(factors_zero) == 0.0


def _gig(title, company, posted_at, body="apply now", hourly=250.0, source_id="remotive"):
    return models.Gig(
        source_id=source_id,
        url=f"https://example.com/{title.replace(' ', '-')}",
        title=title,
        body=body,
        company=company,
        posted_at=posted_at,
        first_seen_at=posted_at,
        last_verified_at=posted_at,
    )


def test_dedupe_key_order_insensitive():
    assert dedupe.dedupe_key("ACME Corp", "Senior Python Developer") == dedupe.dedupe_key(
        "acme CORP", "Developer Senior Python"
    )


def test_db_merge_dedupes_cross_source():
    conn = db.connect(":memory:")
    now = utcnow()
    g1 = _gig("Support Agent", "Acme", now)
    g2 = _gig(
        "Support Agent",
        "acme",
        now - timedelta(days=1),
        body="longer body " * 5,
        source_id="jobicy",
    )
    g1.dedupe_key = dedupe.dedupe_key(g1.company, g1.title)
    g2.dedupe_key = g1.dedupe_key
    id1 = db.upsert_gig(conn, g1)
    id2 = db.upsert_gig(conn, g2)
    assert id1 == id2  # merged, not duplicated
    row = conn.execute("SELECT * FROM gigs WHERE id = ?", (id1,)).fetchone()
    assert set(__import__("json").loads(row["source_ids"])) == {"remotive", "jobicy"}
    assert "longer" in row["body"]  # longer body wins
    assert row["posted_at"] == g2.posted_at.isoformat()  # earliest wins


def test_db_merge_tie_break_prefers_newer_extraction():
    """Equal-confidence pay: the newer crawl wins (parser logic improves over time)."""
    conn = db.connect(":memory:")
    now = utcnow()
    g1 = _gig("Worker", "Beta Co", now)
    g1.dedupe_key = dedupe.dedupe_key("Beta Co", "Worker")
    g1.pay.hourly_equiv_php, g1.pay.confidence = 100.0, 0.4
    db.upsert_gig(conn, g1)
    g2 = _gig("Worker", "Beta Co", now, source_id="jobicy")
    g2.dedupe_key = g1.dedupe_key
    g2.pay.hourly_equiv_php, g2.pay.confidence = 300.0, 0.4
    db.upsert_gig(conn, g2)
    row = conn.execute(
        "SELECT pay_hourly_php FROM gigs WHERE dedupe_key = ?", (g1.dedupe_key,)
    ).fetchone()
    assert row["pay_hourly_php"] == 300.0


def _expiry_gig(title, company, posted_at, verified_at, status=models.STATUS_ACTIVE):
    g = _gig(title, company, posted_at)
    g.dedupe_key = dedupe.dedupe_key(company, title)
    g.last_verified_at = verified_at
    g.status = status
    return g


def test_expire_stale_unseen_gigs():
    """Unseen for 30d+ -> expired; fresh gigs stay active (ADR-0009)."""
    conn = db.connect(":memory:")
    now = utcnow()
    fresh = _expiry_gig("Fresh Role", "Acme", now - timedelta(days=5), now - timedelta(days=5))
    stale = _expiry_gig("Stale Role", "Acme", now - timedelta(days=40), now - timedelta(days=31))
    db.upsert_gig(conn, fresh)
    db.upsert_gig(conn, stale)
    assert db.expire_stale_gigs(conn) == 1
    rows = {r["title"]: r["status"] for r in conn.execute("SELECT title, status FROM gigs")}
    assert rows["Fresh Role"] == models.STATUS_ACTIVE
    assert rows["Stale Role"] == models.STATUS_EXPIRED


def test_expire_absolute_cap_despite_recent_verify():
    """Posted 90d+ ago -> expired even if re-verified yesterday (ADR-0009)."""
    conn = db.connect(":memory:")
    now = utcnow()
    old = _expiry_gig("Ancient Role", "Acme", now - timedelta(days=91), now - timedelta(days=1))
    db.upsert_gig(conn, old)
    assert db.expire_stale_gigs(conn) == 1
    row = conn.execute("SELECT status FROM gigs WHERE dedupe_key = ?", (old.dedupe_key,)).fetchone()
    assert row["status"] == models.STATUS_EXPIRED


def test_expire_leaves_flagged_alone():
    """Scam-flagged gigs are excluded already; expiry must not touch them."""
    conn = db.connect(":memory:")
    now = utcnow()
    flagged = _expiry_gig(
        "Fee Job",
        "Scam Co",
        now - timedelta(days=60),
        now - timedelta(days=60),
        status=models.STATUS_FLAGGED,
    )
    db.upsert_gig(conn, flagged)
    assert db.expire_stale_gigs(conn) == 0
    row = conn.execute(
        "SELECT status FROM gigs WHERE dedupe_key = ?", (flagged.dedupe_key,)
    ).fetchone()
    assert row["status"] == models.STATUS_FLAGGED


def test_upsert_revives_expired_gig():
    """An expired gig re-appearing in a feed goes back to active."""
    conn = db.connect(":memory:")
    now = utcnow()
    g = _expiry_gig("Comeback Role", "Acme", now - timedelta(days=40), now - timedelta(days=35))
    db.upsert_gig(conn, g)
    assert db.expire_stale_gigs(conn) == 1
    seen_again = _expiry_gig("Comeback Role", "Acme", now, now)
    db.upsert_gig(conn, seen_again)
    row = conn.execute(
        "SELECT status, last_verified_at FROM gigs WHERE dedupe_key = ?", (g.dedupe_key,)
    ).fetchone()
    assert row["status"] == models.STATUS_ACTIVE
    assert row["last_verified_at"] == now.isoformat()


def test_upsert_flag_override_wins():
    """A newly-flagged extraction overrides active status (scam signals win)."""
    conn = db.connect(":memory:")
    now = utcnow()
    g = _expiry_gig("Shady Role", "Acme", now, now)
    db.upsert_gig(conn, g)
    flagged = _expiry_gig("Shady Role", "Acme", now, now, status=models.STATUS_FLAGGED)
    db.upsert_gig(conn, flagged)
    row = conn.execute("SELECT status FROM gigs WHERE dedupe_key = ?", (g.dedupe_key,)).fetchone()
    assert row["status"] == models.STATUS_FLAGGED


def test_score_expired_gig_gets_zero_freshness():
    """ARCH §5: expired rows score fresh=0 even with a recent posted_at."""
    now = utcnow()
    g = _gig("Old But Live", "Acme", now - timedelta(days=1))
    g.status = models.STATUS_EXPIRED
    result = score.score_gig(g, [100.0, 200.0, 300.0], now)
    assert result["factors"]["fresh"] == 0.0


def _match_gig(title, tags=(), category="other"):
    g = _gig(title, "Acme", utcnow())
    g.tags = list(tags)
    g.category = category
    return g


def test_match_query_title_beats_tags_beats_nothing():
    title_hit = _match_gig("Senior Accountant")
    tag_hit = _match_gig("Finance Clerk", tags=["accounting"])
    miss = _match_gig("Python Developer", tags=["python"])
    assert score.match_query("accounting", title_hit) == 0.0  # stem differs; no false hit
    assert score.match_query("accounting", tag_hit) == 0.5  # tag-only hit
    assert score.match_query("accounting", miss) == 0.0
    title_score = score.match_query("finance clerk", title_hit)  # 0.0
    tag_score = score.match_query("finance clerk", tag_hit)  # both title tokens -> 1.0
    assert tag_score > title_score
    assert score.match_query("python", tag_hit) < score.match_query("python", miss)


def test_match_query_empty_query_returns_baseline():
    g = _match_gig("Anything")
    assert score.match_query("", g) == 0.5
    assert score.match_query("   ", g) == 0.5


def test_source_reliability_degrades_with_errors_and_staleness():
    # Health -> reliability (ADR-0014): errors and staleness lower the value instead of
    # every source being a flat SOURCE_RELIABILITY_DEFAULT.
    now = utcnow()
    conn = db.connect(":memory:")
    db.upsert_source(conn, "healthy", 1, 6)
    db.record_source_success(conn, "healthy", now.isoformat(), 10)
    db.upsert_source(conn, "sick", 1, 6)
    db.record_source_error(conn, "sick", "boom", now.isoformat())
    db.record_source_error(conn, "sick", "boom", now.isoformat())
    assert db.source_reliability(conn, "healthy") > db.source_reliability(conn, "sick")

    db.upsert_source(conn, "ghost", 1, 6)
    conn.execute(
        "UPDATE sources SET last_success_at = ? WHERE id = ?",
        ((now - timedelta(days=100)).isoformat(), "ghost"),
    )
    conn.commit()
    assert db.source_reliability(conn, "ghost") < db.source_reliability(conn, "healthy")
    # unknown source (no health row) -> neutral default, never a crash
    assert db.source_reliability(conn, "never_seen") == 0.8


def test_rescore_wires_source_reliability_into_trust():
    # end-to-end of ADR-0014: after rescore_all, a degraded source's gigs carry a lower
    # trust factor than a healthy source's (trust is no longer a constant 0.8).
    now = utcnow()
    conn = db.connect(":memory:")
    for sid, title in (("good_src", "Accountant"), ("bad_src", "Bookkeeper")):
        db.upsert_source(conn, sid, 1, 6)
        g = _gig(title, "Acme", now, source_id=sid)
        g.dedupe_key = dedupe.dedupe_key(g.company, g.title)
        db.upsert_gig(conn, g)
    db.record_source_success(conn, "good_src", now.isoformat(), 1)
    for _ in range(6):
        db.record_source_error(conn, "bad_src", "boom", now.isoformat())
    conn.execute(
        "UPDATE sources SET last_success_at = ? WHERE id = ?",
        ((now - timedelta(days=100)).isoformat(), "bad_src"),
    )
    conn.commit()

    ingest.rescore_all(conn)
    trust = {
        r["source_ids"]: json.loads(r["factors_json"])["factors"]["trust"]
        for r in conn.execute("SELECT source_ids, factors_json FROM gigs").fetchall()
    }
    assert trust['["good_src"]'] == 0.8
    assert trust['["bad_src"]'] < trust['["good_src"]']


def test_enrich_maps_employment_type_from_raw_listing():
    raw = models.RawListing(
        source_id="onlinejobs_ph",
        url="https://example.com/data-entry",
        title="Data Entry",
        body="apply now",
        employment_type_raw="Gig",
    )
    assert enrich.enrich(raw).employment_type == models.EMPLOYMENT_GIG
    unknown = models.RawListing(
        source_id="onlinejobs_ph", url="https://example.com/x", title="X", body="apply now"
    )
    assert enrich.enrich(unknown).employment_type == models.EMPLOYMENT_UNKNOWN


def test_employment_type_round_trips_through_db_including_card_query():
    conn = db.connect(":memory:")
    now = utcnow()
    g = _gig("Data Entry Gig", "Acme", now)
    g.dedupe_key = dedupe.dedupe_key(g.company, g.title)
    g.employment_type = models.EMPLOYMENT_GIG
    gid = db.upsert_gig(conn, g)
    assert db.get_gig(conn, gid).employment_type == models.EMPLOYMENT_GIG
    (card,) = db.get_gig_cards(conn, [gid])  # body-free list query must carry it too
    assert card.employment_type == models.EMPLOYMENT_GIG


def test_migration_adds_employment_type_to_legacy_db(tmp_path):
    # a DB created with the pre-change schema must gain the column on connect()
    import sqlite3

    path = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(path)
    legacy.executescript(db.SCHEMA.replace(", employment_type TEXT", ""))
    legacy.commit()
    legacy.close()

    conn = db.connect(path)  # CREATE IF NOT EXISTS is a no-op; _migrate ALTERs
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(gigs)").fetchall()}
    assert "employment_type" in cols
    # and the migrated DB is usable end-to-end
    now = utcnow()
    g = _gig("Migrated Gig", "Acme", now)
    g.dedupe_key = dedupe.dedupe_key(g.company, g.title)
    g.employment_type = models.EMPLOYMENT_PART_TIME
    gid = db.upsert_gig(conn, g)
    assert db.get_gig(conn, gid).employment_type == models.EMPLOYMENT_PART_TIME
