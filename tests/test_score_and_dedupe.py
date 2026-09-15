"""Scoring math tests (ADR-0007) + dedupe/db merge behavior."""

from __future__ import annotations

from datetime import timedelta

from giggregator import db, dedupe, models, score
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
    assert score.effort_factor(models.PAYOUT_MONTHLY, flex, True) > \
        score.effort_factor(models.PAYOUT_MONTHLY, committed, False)


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
        source_id=source_id, url=f"https://example.com/{title.replace(' ', '-')}",
        title=title, body=body, company=company, posted_at=posted_at,
        first_seen_at=posted_at, last_verified_at=posted_at,
    )


def test_dedupe_key_order_insensitive():
    assert dedupe.dedupe_key("ACME Corp", "Senior Python Developer") == \
        dedupe.dedupe_key("acme CORP", "Developer Senior Python")


def test_db_merge_dedupes_cross_source():
    conn = db.connect(":memory:")
    now = utcnow()
    g1 = _gig("Support Agent", "Acme", now)
    g2 = _gig("Support Agent", "acme", now - timedelta(days=1),
              body="longer body " * 5, source_id="jobicy")
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
    row = conn.execute("SELECT pay_hourly_php FROM gigs WHERE dedupe_key = ?",
                       (g1.dedupe_key,)).fetchone()
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
    row = conn.execute("SELECT status FROM gigs WHERE dedupe_key = ?",
                       (old.dedupe_key,)).fetchone()
    assert row["status"] == models.STATUS_EXPIRED


def test_expire_leaves_flagged_alone():
    """Scam-flagged gigs are excluded already; expiry must not touch them."""
    conn = db.connect(":memory:")
    now = utcnow()
    flagged = _expiry_gig("Fee Job", "Scam Co", now - timedelta(days=60),
                          now - timedelta(days=60), status=models.STATUS_FLAGGED)
    db.upsert_gig(conn, flagged)
    assert db.expire_stale_gigs(conn) == 0
    row = conn.execute("SELECT status FROM gigs WHERE dedupe_key = ?",
                       (flagged.dedupe_key,)).fetchone()
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
    row = conn.execute("SELECT status, last_verified_at FROM gigs WHERE dedupe_key = ?",
                       (g.dedupe_key,)).fetchone()
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
    row = conn.execute("SELECT status FROM gigs WHERE dedupe_key = ?",
                       (g.dedupe_key,)).fetchone()
    assert row["status"] == models.STATUS_FLAGGED


def test_score_expired_gig_gets_zero_freshness():
    """ARCH §5: expired rows score fresh=0 even with a recent posted_at."""
    now = utcnow()
    g = _gig("Old But Live", "Acme", now - timedelta(days=1))
    g.status = models.STATUS_EXPIRED
    result = score.score_gig(g, [100.0, 200.0, 300.0], now)
    assert result["factors"]["fresh"] == 0.0
