"""Plain server-rendered HTML (ADR-0002). No JS framework; one ranked table per page.

Run: uv run uvicorn giggregator.web:app --reload
DB path: env GIGGREGATOR_DB (default ./giggregator.db)
"""

from __future__ import annotations

import hmac
import html
import os
import sqlite3

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import config, db, flows, ingest
from .normalize import parse_dt, utcnow

app = FastAPI(title="Giggregator")


_CONN = None
_CONN_KEY = None


def _is_remote() -> bool:
    return bool(
        os.environ.get("GIGGREGATOR_TURSO_DATABASE_URL") or os.environ.get("TURSO_DATABASE_URL")
    )


def get_conn() -> sqlite3.Connection:
    # ponytail: cache only the remote Turso connection (TLS + Hrana handshake
    # per request is the ~3s warm cost on Vercel). Local sqlite connects are
    # cheap and not thread-safe to share, so those stay per-request.
    global _CONN, _CONN_KEY
    key = os.environ.get("GIGGREGATOR_DB", "giggregator.db")
    if not _is_remote():
        return db.connect(key)
    if _CONN is None or _CONN_KEY != key:
        _CONN = db.connect(key)
        _CONN_KEY = key
    return _CONN


# ---------------------------------------------------------------- rendering

_CSS = """
body{font-family:system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem}
table{border-collapse:collapse;width:100%}
td,th{border:1px solid #ccc;padding:.35rem .5rem;text-align:left;vertical-align:top}
th{background:#f5f5f5}
.badge{display:inline-block;background:#eee;border:1px solid #ccc;border-radius:3px;
 padding:0 .35rem;margin:.05rem;font-size:.8em}
.flowbox{display:flex;gap:.5rem;flex-wrap:wrap;margin:1rem 0}
.flowbox a{border:1px solid #888;border-radius:4px;padding:.4rem .7rem;text-decoration:none}
.meta{color:#666;font-size:.85em}
"""

_PAGE = (
    "<!doctype html><html><head><meta charset='utf-8'>"
    "<title>{title} — Giggregator</title><style>"
    + _CSS.replace("{", "{{").replace("}", "}}")  # keep CSS literal through .format
    + "</style></head>"
    "<body><h1>Giggregator</h1><p class='meta'>PH remote-work search — device +"
    " internet is the only ticket.</p>{body}</body></html>"
)


def _esc(text: str | None) -> str:
    return html.escape(str(text or ""))


def _age(posted_at) -> str:
    if posted_at is None:
        return "?"
    delta = utcnow() - posted_at
    minutes = delta.total_seconds() / 60
    if minutes < 60:
        return f"{int(minutes)}m"
    hours = minutes / 60
    if hours < 48:
        return f"{int(hours)}h"
    return f"{int(hours / 24)}d"


def _pay_display(gig) -> str:
    parts = []
    if gig.pay.raw_text:
        parts.append(_esc(gig.pay.raw_text))
    if gig.pay.hourly_equiv_php is not None:
        parts.append(f"≈₱{gig.pay.hourly_equiv_php:,.0f}/hr")
    if gig.pay.hourly_equiv_php is not None and gig.pay.confidence < 0.55:
        parts.append("(low conf)")
    return "<br>".join(parts) if parts else "<span class='meta'>pay not stated</span>"


def _effort_display(gig) -> str:
    effort = (gig.scores or {}).get("factors", {}).get("effort")
    if effort is None:
        return "—"
    badge = "⚡" if effort >= 0.75 else ""
    extras = []
    req = gig.requirements
    if req.device == "pc_required":
        extras.append("needs PC")
    if req.comms == "live":
        extras.append("live calls")
    if req.min_hours_per_week:
        extras.append(f"{req.min_hours_per_week}h/wk")
    line = f"{badge}effort {effort:.2f}"
    return line + ("<br>" + _esc(", ".join(extras)) if extras else "")


def render_listing(gig, rank: int | None = None) -> str:
    tags = " ".join(f"<span class='badge'>{_esc(t)}</span>" for t in gig.tags[:6])
    sources = ", ".join(_esc(s) for s in gig.source_ids)
    rel = gig.scores.get("relevance")
    rank_cell = f"{rank}. " if rank else ""
    return (
        f"<tr><td>{rank_cell}<a href='/gig/{gig.id}'>{_esc(gig.title)}</a>"
        f"<br><span class='meta'>{_esc(gig.company) or '<i>employer n/a</i>'} · "
        f"{_esc(gig.category)} · {_age(gig.posted_at)} old · via {sources}</span></td>"
        f"<td>{_pay_display(gig)}</td>"
        f"<td>{_effort_display(gig)}</td>"
        f"<td>{tags}</td>"
        f"<td><b>{rel if rel is not None else '—'}</b></td></tr>"
    )


def _table(gigs, ranked: bool = False) -> str:
    head = "<tr><th>Gig</th><th>Pay</th><th>Effort</th><th>Tags</th><th>Score</th></tr>"
    rows = "".join(
        render_listing(g, rank=i + 1) if ranked else render_listing(g) for i, g in enumerate(gigs)
    )
    if not rows:
        rows = "<tr><td colspan='5'><i>No listings. Run an ingest cycle first.</i></td></tr>"
    return f"<table>{head}{rows}</table>"


def _flow_nav(active_id: str | None = None) -> str:
    links = []
    for fid, flow in flows.FLOWS.items():
        mark = f"<b>{_esc(flow.label)}</b>" if fid == active_id else _esc(flow.label)
        links.append(f"<a href='/flow/{fid}'>{mark}</a>")
    links.append("<a href='/search'>Search</a>")
    return f"<div class='flowbox'>{''.join(links)}</div>"


def _flow_header(flow) -> str:
    weights = ", ".join(f"{k}={v}" for k, v in flows.flow_weights(flow).items())
    return (
        f"<h2>{_esc(flow.label)}</h2>"
        f"<p class='meta'>{_esc(flow.description)} · weights: {weights}</p>"
    )


def _flow_gigs(conn, flow, limit: int = 40):
    from .score import relevance

    now = utcnow()
    gigs = [g for g in db.active_gig_cards(conn) if flow.matches(g, now)]
    weights = flows.flow_weights(flow)
    for g in gigs:
        factors = g.scores.get("factors") or {}
        g.scores["relevance"] = relevance(factors, weights)
    gigs.sort(key=lambda g: g.scores.get("relevance", 0), reverse=True)
    return gigs[:limit]


# ---------------------------------------------------------------- routes


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    conn = get_conn()
    total = db.active_count(conn)
    top = db.active_gig_cards(conn, limit=40)
    flagged = db.flagged_count(conn)
    body = (
        _flow_nav()
        + _table(top, ranked=True)
        + f"<p class='meta'>Top {len(top)} of {total} active listings."
        f" Flagged (scam-signal) listings excluded: {flagged}.</p>"
    )
    return _PAGE.format(title="Home", body=body)


@app.get("/flow/{flow_id}", response_class=HTMLResponse)
def flow_page(flow_id: str) -> str:
    flow = flows.FLOWS.get(flow_id)
    if flow is None:
        return _PAGE.format(title="Not found", body="<p>Unknown flow.</p>")
    conn = get_conn()
    gigs = _flow_gigs(conn, flow)
    body = _flow_nav(flow_id) + _flow_header(flow) + _table(gigs, ranked=True)
    return _PAGE.format(title=flow.label, body=body)


@app.get("/search", response_class=HTMLResponse)
def search(
    q: str = "", category: str = "", device: str = "", hours: str = "", min_pay: float = 0.0
) -> str:
    conn = get_conn()
    ids = db.search_gig_ids(conn, q)
    gigs = db.get_gig_cards(conn, ids)
    if category:
        gigs = [g for g in gigs if g.category == category]
    if device:
        gigs = [g for g in gigs if g.requirements.device == device]
    if hours:
        gigs = [g for g in gigs if g.requirements.hours == hours]
    if min_pay > 0:
        gigs = [g for g in gigs if (g.pay.hourly_equiv_php or 0) >= min_pay]
    if q.strip():
        from .score import match_query

        scored = [(match_query(q, g), g.scores.get("relevance", 0), g) for g in gigs]
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        gigs = [g for _, _, g in scored]
    else:
        gigs.sort(key=lambda g: g.scores.get("relevance", 0), reverse=True)
    active_filters = " ".join(
        f"<span class='badge'>{_esc(k)}={_esc(v)}</span>"
        for k, v in [
            ("q", q),
            ("category", category),
            ("device", device),
            ("hours", hours),
            ("min_pay", min_pay or ""),
        ]
        if v not in ("", None)
    )
    form = (
        "<form action='/search' method='get'>"
        "<input name='q' value='" + _esc(q) + "' placeholder='keywords'> "
        "<input name='category' value='" + _esc(category) + "' placeholder='category'> "
        "<input name='device' value='" + _esc(device) + "' placeholder='device'> "
        "<input name='hours' value='" + _esc(hours) + "' placeholder='hours'> "
        "<input name='min_pay' value='" + _esc(min_pay or "") + "' size='6'"
        " placeholder='min ₱/hr'> <button>Go</button></form>"
    )
    body = (
        _flow_nav()
        + f"<h2>Search {active_filters}</h2>"
        + form
        + _table(gigs[:40], ranked=True)
        + f"<p class='meta'>{len(gigs)} matches.</p>"
    )
    return _PAGE.format(title="Search", body=body)


@app.get("/gig/{gig_id}", response_class=HTMLResponse)
def gig_detail(gig_id: int) -> str:
    conn = get_conn()
    gig = db.get_gig(conn, gig_id)
    if gig is None:
        return _PAGE.format(title="Not found", body="<p>No such gig.</p>")
    scores = gig.scores or {}
    factors = scores.get("factors", {})
    why_rows = "".join(
        f"<tr><td>{_esc(k)}</td><td>{factors.get(k, 0):.2f}</td></tr>"
        for k in ("pay", "fresh", "effort", "match", "trust")
    )
    req = gig.requirements
    min_hours = f", min {_esc(req.min_hours_per_week)}h/wk" if req.min_hours_per_week else ""
    tags = " ".join(f"<span class='badge'>{_esc(t)}</span>" for t in gig.tags)
    body = (
        "<p><a href='/'>&larr; back</a></p>"
        f"<h2>{_esc(gig.title)}</h2>"
        f"<p class='meta'>{_esc(gig.company)} · {_esc(gig.category)} · via "
        f"{', '.join(_esc(s) for s in gig.source_ids)} · {_age(gig.posted_at)} old · "
        f"status: {_esc(gig.status)}</p>"
        f"<p><b>Pay:</b> {_pay_display(gig)}<br><span class='meta'>raw: "
        f"{_esc(gig.pay.raw_text)} (confidence {gig.pay.confidence:.2f})</span></p>"
        f"<p><b>Requirements:</b> device={_esc(req.device)}, internet={_esc(req.internet)}, "
        f"hours={_esc(req.hours)}{min_hours}, comms={_esc(req.comms)} · "
        f"payout: {_esc(gig.payout_cadence)}</p>"
        f"<p><b>Tags:</b> {tags}</p>"
        f"<p><a href='{_esc(gig.url)}'>Apply at source &rarr;</a></p>"
        f"<h3>Why this ranked here (relevance {scores.get('relevance', 0)})</h3>"
        f"<table><tr><th>factor</th><th>value</th></tr>{why_rows}</table>"
        f"<h3>Listing text</h3><p>{_esc(gig.body[:3000])}</p>"
    )
    return _PAGE.format(title=gig.title, body=body)


@app.get("/health")
def health() -> JSONResponse:
    """Per-source freshness/health — the operator early-warning view (AGENTS.md: silent
    breakage is the #1 failure mode). Public and read-only; a source is "stale" when it
    has not succeeded within SOURCE_STALE_HOURS (or never). Raw last_error text is
    deliberately omitted: adapter error strings can embed request URLs that carry API
    keys (CareerJet/Jooble), so only has_error + error_count are surfaced; the message
    stays in the DB for the operator.
    """
    conn = get_conn()
    now = utcnow()
    sources = []
    for row in db.source_health(conn):
        last = parse_dt(row["last_success_at"])
        age_hours = (now - last).total_seconds() / 3600.0 if last else None
        sources.append(
            {
                "id": row["id"],
                "tier": row["tier"],
                "cadence_hours": row["cadence_hours"],
                "last_success_at": row["last_success_at"],
                "age_hours": round(age_hours, 2) if age_hours is not None else None,
                "stale": age_hours is None or age_hours > config.SOURCE_STALE_HOURS,
                "has_error": bool(row["last_error"]),
                "error_count": row["error_count"],
                "listings_7d": row["listings_7d"],
                "reliability": db.source_reliability(conn, row["id"]),
            }
        )
    return JSONResponse(
        {
            "ok": all(not s["stale"] and not s["has_error"] for s in sources),
            "active_gigs": db.active_count(conn),
            "flagged_gigs": db.flagged_count(conn),
            "stale_after_hours": config.SOURCE_STALE_HOURS,
            "sources": sources,
        }
    )


@app.api_route("/cron/ingest", methods=["GET", "POST"])
def cron_ingest(request: Request) -> JSONResponse:
    """Vercel-cron ingest hook: one full ingest cycle against the live DB.

    Vercel Cron Jobs issue a GET carrying ``Authorization: Bearer
    <CRON_SECRET>`` natively; manual runs can POST with the same header.
    Constant-time compare; 404 when no secret is configured so the route is
    inert locally. Per-adapter isolation in ``ingest`` keeps the cycle green
    if one source fails (e.g. CareerJet from a non-whitelisted egress IP).
    """
    secret = config.CRON_SECRET
    if not secret:
        return JSONResponse({"ok": False, "error": "cron disabled"}, status_code=404)
    auth = request.headers.get("authorization", "")
    if not hmac.compare_digest(auth, f"Bearer {secret}"):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    conn = get_conn()
    stored = rescored = 0
    per_source: dict[str, dict[str, int]] = {}
    for adapter in ingest.ADAPTERS:
        try:
            payload = adapter.fetch()
            n_parsed, n_stored = ingest.ingest_adapter_payload(conn, adapter, payload)
            per_source[adapter.meta.id] = {"stored": n_stored, "parsed": n_parsed}
            stored += n_stored
        except Exception as exc:  # noqa: BLE001 - one bad source must not fail the cycle
            per_source[adapter.meta.id] = {"error": str(exc)}
    rescored = ingest.rescore_all(conn)
    flagged = db.flagged_count(conn)
    return JSONResponse(
        {
            "ok": True,
            "stored": stored,
            "rescored": rescored,
            "flagged": flagged,
            "sources": per_source,
        }
    )
