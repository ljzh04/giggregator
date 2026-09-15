"""SQLite + FTS5 storage (ADR-0002). Schema lifecycle: init_db is the migration entry
point; future schema changes go through this module with a DECISIONS.md entry.

Storage backends (ADR-0011): local SQLite file by default; when GIGGREGATOR_TURSO_DATABASE_URL is
set, a remote Turso/libSQL database over HTTPS (same engine, same SQL, FTS5 included).
The _RemoteConn wrapper below makes both backends behave identically to the rest of
the codebase — call sites never branch on backend."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import timedelta
from typing import Any

from . import config, models

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  tier INTEGER NOT NULL DEFAULT 1,
  cadence_hours INTEGER NOT NULL DEFAULT 6,
  last_success_at TEXT,
  last_error TEXT,
  error_count INTEGER NOT NULL DEFAULT 0,
  listings_7d INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS fx_rates (
  code TEXT PRIMARY KEY,
  php_rate REAL NOT NULL,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS gigs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedupe_key TEXT UNIQUE,
  source_ids TEXT NOT NULL DEFAULT '[]',
  url TEXT, title TEXT, company TEXT, body TEXT,
  posted_at TEXT, first_seen_at TEXT, last_verified_at TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  pay_json TEXT, requirements_json TEXT, payout_cadence TEXT,
  tags_json TEXT, category TEXT, no_experience_friendly INTEGER NOT NULL DEFAULT 0,
  trust_flags_json TEXT, location TEXT,
  pay_hourly_php REAL, pay_confidence REAL NOT NULL DEFAULT 0,
  factors_json TEXT, relevance REAL NOT NULL DEFAULT 0,
  updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_gigs_status_rel ON gigs(status, relevance DESC);
CREATE INDEX IF NOT EXISTS idx_gigs_cat ON gigs(category);

CREATE VIRTUAL TABLE IF NOT EXISTS gigs_fts USING fts5(
  title, body, tags, content='gigs', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS gigs_ai AFTER INSERT ON gigs BEGIN
  INSERT INTO gigs_fts(rowid, title, body, tags)
  VALUES (new.id, new.title, new.body, new.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS gigs_ad AFTER DELETE ON gigs BEGIN
  INSERT INTO gigs_fts(gigs_fts, rowid, title, body, tags)
  VALUES ('delete', old.id, old.title, old.body, old.tags_json);
END;

CREATE TRIGGER IF NOT EXISTS gigs_au AFTER UPDATE OF title, body, tags_json ON gigs BEGIN
  INSERT INTO gigs_fts(gigs_fts, rowid, title, body, tags)
  VALUES ('delete', old.id, old.title, old.body, old.tags_json);
  INSERT INTO gigs_fts(rowid, title, body, tags)
  VALUES (new.id, new.title, new.body, new.tags_json);
END;
"""


class _Row(dict):
    """Dict-based row emulating sqlite3.Row: name access with integer fallback.

    The libsql driver has no row_factory support, so remote results are wrapped in
    one of these to keep `row["col"]` call sites identical across backends."""

    def __init__(self, columns: list[str], values: tuple) -> None:
        super().__init__(zip(columns, values, strict=True))
        self._values = tuple(values)

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


class _RemoteCursor:
    """Wraps a libsql cursor, converting fetched tuples into _Row objects."""

    def __init__(self, cur: Any) -> None:
        self._cur = cur

    def __iter__(self) -> _RemoteCursor:
        return self

    def __next__(self) -> _Row:
        return self._wrap(next(self._cur))

    def _wrap(self, values: tuple | None) -> _Row | None:
        if values is None:
            return None
        cols = [d[0] for d in (self._cur.description or [])]
        return _Row(cols, values)

    @property
    def description(self) -> Any:
        return self._cur.description

    @property
    def rowcount(self) -> int:
        return getattr(self._cur, "rowcount", -1)

    @property
    def lastrowid(self) -> int | None:
        return getattr(self._cur, "lastrowid", None)

    def fetchone(self) -> _Row | None:
        return self._wrap(self._cur.fetchone())

    def fetchall(self) -> list[_Row]:
        return [self._wrap(v) for v in self._cur.fetchall()]


class _RemoteConn:
    """Connection wrapper over the libsql driver exposing the sqlite3 surface that
    giggregator uses (execute/commit/executescript, name-access rows).

    The Hrana protocol drops idle streams server-side, so a long ingest cycle
    (network fetches between writes) can hit "stream not found" / connection
    errors. execute() therefore reconnects and retries transient transport
    failures instead of aborting the whole run."""

    _TRANSIENT = (
        "stream not found",
        "stream error",
        "connection error",
        "dns error",
        "connection reset",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "idle for too long",
        "rolled back",
        "sqlite_busy",
    )
    _RETRIES = 5

    def __init__(self, conn: Any, url: str = "", token: str = "") -> None:
        self._conn = conn
        self._url = url
        self._token = token

    def _reconnect(self, attempt: int) -> None:
        import time

        import libsql

        time.sleep(min(2**attempt, 15))
        try:
            self._conn.close()
        except Exception:
            pass
        self._conn = libsql.connect(database=self._url, auth_token=self._token)

    @classmethod
    def _transient(cls, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "hrana" in msg and any(t in msg for t in cls._TRANSIENT)

    def execute(self, sql: str, params: tuple = ()) -> _RemoteCursor:
        last: Exception | None = None
        for attempt in range(self._RETRIES + 1):
            try:
                return _RemoteCursor(self._conn.execute(sql, params))
            except Exception as exc:  # noqa: BLE001 — transport errors only retried
                if not self._transient(exc) or attempt >= self._RETRIES:
                    raise
                last = exc
                self._reconnect(attempt)
        raise last  # pragma: no cover — loop always returns or raises

    def executescript(self, script: str) -> None:
        self._conn.executescript(script)

    def commit(self) -> None:
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def connect(path: str = ":memory:") -> sqlite3.Connection | _RemoteConn:
    """Open the giggregator database.

    Default: local SQLite file (or :memory: for tests). When GIGGREGATOR_TURSO_DATABASE_URL is
    set (production: Vercel web app, GitHub Actions ingest), connect to the remote
    Turso/libSQL database instead. Tests never load .env, so they always stay local.
    """
    url = os.environ.get("GIGGREGATOR_TURSO_DATABASE_URL") or os.environ.get("TURSO_DATABASE_URL")
    if url and path != ":memory:":
        import libsql

        token = os.environ.get("GIGGREGATOR_TURSO_AUTH_TOKEN") or os.environ.get(
            "TURSO_AUTH_TOKEN", ""
        )
        remote = _RemoteConn(libsql.connect(database=url, auth_token=token), url, token)
        remote.executescript(SCHEMA)
        return remote
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _iso(dt) -> str | None:
    return dt.isoformat() if dt is not None else None


def upsert_source(conn: sqlite3.Connection, source_id: str, tier: int, cadence_hours: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO sources (id, tier, cadence_hours) VALUES (?, ?, ?)",
        (source_id, tier, cadence_hours),
    )
    conn.commit()


def record_source_success(
    conn: sqlite3.Connection, source_id: str, at_iso: str, count: int
) -> None:
    conn.execute(
        "UPDATE sources SET last_success_at = ?, last_error = NULL, listings_7d = ? WHERE id = ?",
        (at_iso, count, source_id),
    )
    conn.commit()


def record_source_error(conn: sqlite3.Connection, source_id: str, error: str, at_iso: str) -> None:
    conn.execute(
        "UPDATE sources SET last_error = ?, error_count = error_count + 1 WHERE id = ?",
        (error, source_id),
    )
    conn.commit()


def get_fx(conn: sqlite3.Connection, code: str = "USD") -> float | None:
    row = conn.execute("SELECT php_rate FROM fx_rates WHERE code = ?", (code,)).fetchone()
    return row["php_rate"] if row else None


def set_fx(conn: sqlite3.Connection, code: str, php_rate: float, updated_at: str) -> None:
    conn.execute(
        "INSERT INTO fx_rates (code, php_rate, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(code) DO UPDATE SET php_rate = excluded.php_rate,"
        " updated_at = excluded.updated_at",
        (code, php_rate, updated_at),
    )
    conn.commit()


def _earliest(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def _gig_values(gig: models.Gig) -> list[Any]:
    return [
        gig.dedupe_key,
        json.dumps(gig.source_ids),
        gig.url,
        gig.title,
        gig.company,
        gig.body,
        _iso(gig.posted_at),
        _iso(gig.first_seen_at),
        _iso(gig.last_verified_at),
        gig.status,
        json.dumps(gig.pay.__dict__),
        json.dumps(gig.requirements.__dict__),
        gig.payout_cadence,
        json.dumps(gig.tags),
        gig.category,
        int(gig.no_experience_friendly),
        json.dumps(gig.trust_flags),
        gig.location_raw,
        gig.pay.hourly_equiv_php,
        gig.pay.confidence,
        _iso(gig.first_seen_at),
    ]


def upsert_gig(conn: sqlite3.Connection, gig: models.Gig) -> int:
    """Insert or merge by dedupe_key (ARCHITECTURE.md §4: earliest posted_at, longest body,
    union of sources, highest-confidence pay). Returns the gig row id."""
    values = _gig_values(gig)
    existing = conn.execute(
        "SELECT id, source_ids, body, posted_at, first_seen_at, pay_confidence,"
        " pay_hourly_php, status FROM gigs WHERE dedupe_key = ?",
        (gig.dedupe_key,),
    ).fetchone()
    if existing is None:
        cur = conn.execute(
            "INSERT INTO gigs (dedupe_key, source_ids, url, title, company, body, posted_at,"
            " first_seen_at, last_verified_at, status, pay_json, requirements_json,"
            " payout_cadence, tags_json, category, no_experience_friendly, trust_flags_json,"
            " location, pay_hourly_php, pay_confidence, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )
        conn.commit()
        return int(cur.lastrowid)

    merged_source_ids = sorted(set(json.loads(existing["source_ids"])) | set(gig.source_ids))
    body = gig.body if len(gig.body) > len(existing["body"] or "") else existing["body"]
    posted_at = _earliest(existing["posted_at"], values[6])
    first_seen = _earliest(existing["first_seen_at"], values[7])
    pay_hourly, pay_conf = values[18], values[19]
    if (existing["pay_confidence"] or 0) > (pay_conf or 0):
        pay_hourly = existing["pay_hourly_php"]
        pay_conf = existing["pay_confidence"]
    # Re-seen gigs revive: an expired row re-appearing in a feed is live again.
    # A newly-flagged extraction overrides to flagged (scam signals win).
    status = existing["status"]
    if gig.status == models.STATUS_FLAGGED:
        status = models.STATUS_FLAGGED
    elif status == models.STATUS_EXPIRED and gig.status == models.STATUS_ACTIVE:
        status = models.STATUS_ACTIVE
    conn.execute(
        "UPDATE gigs SET source_ids = ?, body = ?, posted_at = ?, first_seen_at = ?,"
        " last_verified_at = ?, pay_hourly_php = ?, pay_confidence = ?, status = ?,"
        " updated_at = ? WHERE id = ?",
        (
            json.dumps(merged_source_ids),
            body,
            posted_at,
            first_seen,
            values[8],
            pay_hourly,
            pay_conf,
            status,
            values[20],
            existing["id"],
        ),
    )
    conn.commit()
    return int(existing["id"])


def expire_stale_gigs(conn: sqlite3.Connection, now_iso: str | None = None) -> int:
    """Mark stale active gigs expired (ADR-0009). Returns the expired count.

    A gig expires when unseen for EXPIRY_VERIFIED_TTL_DAYS (last_verified_at cutoff)
    or unconditionally at EXPIRY_ABSOLUTE_MAX_DAYS old (posted_at cutoff). Flagged
    gigs are untouched. Pure SQL on ISO timestamps — no network, no model.
    """
    from .normalize import parse_dt, utcnow

    now = parse_dt(now_iso) if now_iso else utcnow()
    verified_cutoff = (now - timedelta(days=config.EXPIRY_VERIFIED_TTL_DAYS)).isoformat()
    absolute_cutoff = (now - timedelta(days=config.EXPIRY_ABSOLUTE_MAX_DAYS)).isoformat()
    cur = conn.execute(
        "UPDATE gigs SET status = 'expired', updated_at = ?"
        " WHERE status = 'active'"
        " AND (last_verified_at IS NULL OR last_verified_at < ? OR posted_at < ?)",
        (now.isoformat(), verified_cutoff, absolute_cutoff),
    )
    conn.commit()
    return cur.rowcount


def gig_from_row(row: sqlite3.Row) -> models.Gig:
    from . import normalize

    pay = models.PayInfo(**json.loads(row["pay_json"] or "{}"))
    req = models.Requirements(**json.loads(row["requirements_json"] or "{}"))
    source_ids = json.loads(row["source_ids"] or "[]")
    gig = models.Gig(
        source_id=(source_ids or ["unknown"])[0],
        url=row["url"],
        title=row["title"],
        body=row["body"] or "",
        company=row["company"] or "",
        posted_at=normalize.parse_dt(row["posted_at"]),
        first_seen_at=normalize.parse_dt(row["first_seen_at"]),
        last_verified_at=normalize.parse_dt(row["last_verified_at"]),
        status=row["status"],
        pay=pay,
        requirements=req,
        payout_cadence=row["payout_cadence"] or models.PAYOUT_UNKNOWN,
        tags=json.loads(row["tags_json"] or "[]"),
        category=row["category"] or "other",
        no_experience_friendly=bool(row["no_experience_friendly"]),
        trust_flags=json.loads(row["trust_flags_json"] or "[]"),
        location_raw=row["location"] or "",
        dedupe_key=row["dedupe_key"] or "",
        source_ids=source_ids,
        id=int(row["id"]),
    )
    gig.scores = json.loads(row["factors_json"] or "{}")
    if isinstance(gig.scores, dict) and gig.scores:
        gig.scores["relevance"] = row["relevance"]
    return gig


def get_gig(conn: sqlite3.Connection, gig_id: int) -> models.Gig | None:
    row = conn.execute("SELECT * FROM gigs WHERE id = ?", (gig_id,)).fetchone()
    return gig_from_row(row) if row else None


def active_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM gigs WHERE status = 'active'").fetchone()
    return int(row["n"])


def active_gigs(conn: sqlite3.Connection) -> list[models.Gig]:
    rows = conn.execute(
        "SELECT * FROM gigs WHERE status = 'active' ORDER BY relevance DESC, id"
    ).fetchall()
    return [gig_from_row(r) for r in rows]


# Columns for list pages: everything gig_from_row needs except the multi-KB
# body (detail page only). '' AS body keeps gig_from_row working unchanged.
_CARD_COLS = (
    "id, dedupe_key, source_ids, url, title, company, '' AS body,"
    " posted_at, first_seen_at, last_verified_at, status, pay_json,"
    " requirements_json, payout_cadence, tags_json, category,"
    " no_experience_friendly, trust_flags_json, location,"
    " pay_hourly_php, pay_confidence, factors_json, relevance, updated_at"
)


def active_gig_cards(conn: sqlite3.Connection, limit: int | None = None) -> list[models.Gig]:
    """Active gigs without body text — cheap over Hrana for list pages."""
    sql = f"SELECT {_CARD_COLS} FROM gigs WHERE status = 'active' ORDER BY relevance DESC, id"
    params: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (limit,)
    return [gig_from_row(r) for r in conn.execute(sql, params).fetchall()]


def get_gig_cards(conn: sqlite3.Connection, gig_ids: list[int]) -> list[models.Gig]:
    """Body-free fetch for a known id set in one round trip (no N+1)."""
    if not gig_ids:
        return []
    placeholders = ",".join("?" for _ in gig_ids)
    rows = conn.execute(
        f"SELECT {_CARD_COLS} FROM gigs WHERE id IN ({placeholders})", tuple(gig_ids)
    ).fetchall()
    by_id = {int(r["id"]): gig_from_row(r) for r in rows}
    return [by_id[i] for i in gig_ids if i in by_id]


def corpus_pay(conn: sqlite3.Connection) -> list[float]:
    rows = conn.execute(
        "SELECT pay_hourly_php FROM gigs WHERE status = 'active' AND pay_hourly_php IS NOT NULL"
    ).fetchall()
    return sorted(float(r["pay_hourly_php"]) for r in rows)


def save_scores(conn: sqlite3.Connection, gig_id: int, scores: dict) -> None:
    conn.execute(
        "UPDATE gigs SET factors_json = ?, relevance = ? WHERE id = ?",
        (json.dumps(scores), scores.get("relevance", 0.0), gig_id),
    )
    conn.commit()


def search_gig_ids(conn: sqlite3.Connection, query: str, limit: int = 500) -> list[int]:
    """FTS5 match on title/body/tags; empty query matches all active gigs."""
    if not query.strip():
        rows = conn.execute("SELECT id FROM gigs WHERE status = 'active'").fetchall()
    else:
        rows = conn.execute(
            "SELECT g.id FROM gigs g JOIN gigs_fts f ON g.id = f.rowid"
            " WHERE gigs_fts MATCH ? AND g.status = 'active'",
            (query,),
        ).fetchall()
    return [r["id"] for r in rows][:limit]


def flagged_count(conn: sqlite3.Connection) -> int:
    return int(
        conn.execute("SELECT COUNT(*) AS c FROM gigs WHERE status = 'flagged'").fetchone()["c"]
    )
