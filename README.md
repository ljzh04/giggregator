# Giggregator

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Code style: ruff](https://img.shields.io/badge/lint-ruff-261230)](https://docs.astral.sh/ruff/)

**The PH remote-work search engine for anyone with just a computing device + internet.**

Giggregator continuously ingests remote/WFH **online work** listings — VA, support, data entry,
transcription, AI-training/annotation tasks, online tutoring, writing, dev, design, social media,
QA/testing, microtasks — payable in ₱ or USD and performable from the Philippines. It normalizes
everything into one canonical record, scores it transparently, and serves it as plain, fast
HTML — no accounts, no app store, no laptop required.

Out of scope by design: physical-location work, relocation abroad, and gigs requiring
non-standard equipment. Pay-to-apply / training-fee scams are **auto-excluded**, not downranked.

## How it works

```
SOURCES ──> INGEST ──> RULES PASS ──> INDEX (instant, searchable)
 (tiered adapters,            │
  per-source cadence)         └──> ASYNC ENRICHMENT QUEUE ──> ML pass ──> upgrade + rescore

NORMALIZE ──> ENRICH ──> DEDUPE ──> SCORE ──> FTS5 ──> SERVE (plain HTML flows)
```

- **Adapters** are the only network boundary (read-only, rate-limited, ToS-respecting).
  Parse/normalize/enrich/score are pure functions, tested offline against committed fixtures.
- **Rules-only enrichment** means listings are searchable within seconds; ML passes (phase 1+)
  are async upgrades — if the model is down, the site stays fully functional.
- **Transparent scoring** (`relevance = Σ weight × factor`): pay (₱-normalized, confidence-
  shrunk), freshness (7-day half-life), effort (payout friction, hours, device barrier),
  match, trust (source health + scam signals). Every score is explainable.
- **Expiry** is staleness-based: a gig vanishes when unseen for 30 days, absolutely at 90.
- **Health**: `GET /health` exposes per-source `last_success_at`, staleness, error counts,
  7-day listing yield, and the scoring reliability — silent source breakage is the #1 failure
  mode of aggregators, so it's monitored from day one.

## Quick start

Prerequisites: **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/).

```bash
# 1. Install dependencies
uv sync

# 2. Run one ingest cycle (fetches all enabled sources, ingests, rescores)
uv run python -m giggregator.ingest --once

# 3. Serve the web app locally
uv run uvicorn giggregator.web:app --reload
```

Open <http://127.0.0.1:8000>. Without any configuration everything runs on a local SQLite
database (`giggregator.db`), and key-gated sources (CareerJet, Jooble) simply skip themselves.

Optional — copy `.env.example` to `.env` to connect Turso, add publisher-API keys, or set the
cron secret (see [Configuration](#configuration)).

## Configuration

All environment variables are optional; defaults keep everything local.

| Variable | Purpose |
|---|---|
| `GIGGREGATOR_TURSO_DATABASE_URL` / `GIGGREGATOR_TURSO_AUTH_TOKEN` | Remote Turso (libSQL) backend; when set, takes precedence over the local SQLite file |
| `GIGGREGATOR_DB` | Local SQLite path override (default `./giggregator.db`) |
| `GIGGREGATOR_CAREERJET_AFFILIATE_ID` / `GIGGREGATOR_CAREERJET_KEY` | CareerJet publisher-API credentials (adapter skips itself when absent) |
| `GIGGREGATOR_CAREERJET_REFERER` | Referer header CareerJet requires (must match the domain registered in the publisher account) |
| `GIGGREGATOR_CAREERJET_USER_IP` | Static egress-IP override for CareerJet's `user_ip` param (else auto-detected) |
| `GIGGREGATOR_JOOBLE_KEY` | Jooble API key |
| `GIGGREGATOR_JOOBLE_ENABLED` | Jooble's free key is capped at 500 lifetime requests → ingest is off unless explicitly set to `1` |
| `GIGGREGATOR_CRON_SECRET` | Shared secret guarding `GET /cron/ingest` (empty = route disabled) |

Never commit real keys — `.env` is gitignored.

## CLI reference

```bash
uv run python -m giggregator.ingest --once                        # one full ingest cycle
uv run python -m giggregator.ingest --once --only careerjet_ph    # a single adapter
uv run python -m giggregator.ingest --once --db prod.db           # explicit db path
uv run --env-file .env python scripts/db_check.py                 # round-trip check of the configured DB backend
```

One ingest cycle = fetch → parse → enrich → dedupe → store → expire stale → rescore (the
full-text index is maintained by triggers on every upsert). One failing adapter never fails
the batch: its error is logged to source health and the cycle continues.

## Web app

| Route | What it is |
|---|---|
| `/` | Home: flows + top listings |
| `/flow/{flow_id}` | Flow pages — Quick Bucks, Highest Relevance, Fresh Drops, No-Experience, Mobile-Only, Flexible Hours |
| `/search?q=…` | Full-text search (SQLite FTS5) with query-time re-ranking |
| `/gig/{gig_id}` | Gig detail with the "why this ranked here" factor breakdown |
| `/health` | Read-only JSON: per-source health + corpus counters (below) |
| `/cron/ingest` | Cron entry point; requires `Authorization: Bearer $GIGGREGATOR_CRON_SECRET` (404 when unset, 401 on a wrong secret) |

`/health` reports, per source: `last_success_at`, `age_hours`, `stale` (no success within
48h), `has_error` / `error_count`, `listings_7d`, and the scoring `reliability`; plus corpus
counters (`active_gigs`, `flagged_gigs`). Raw error text is intentionally **not** exposed
(adapter errors can embed key-bearing URLs).

## Deployment (Vercel + Turso)

The repo ships as a Vercel serverless app (`vercel.json`): all routes rewrite to
`/api/index/$1`, the function is pinned to the `hnd1` (Tokyo) region with `maxDuration: 300`,
and a daily cron (`0 1 * * *` UTC) calls `/cron/ingest`.

1. Create a Turso database and set `GIGGREGATOR_TURSO_DATABASE_URL` +
   `GIGGREGATOR_TURSO_AUTH_TOKEN` via `vercel env add`.
2. Set `GIGGREGATOR_CRON_SECRET` the same way (Vercel's cron sends it as a Bearer token).
3. `vercel deploy --prod`. Without Turso configured, deployments serve the bundled read-only
   `seed/seed.db` snapshot instead — useful for previews.
4. CareerJet's publisher key is IP-bound, so requests from rotating serverless egress IPs are
   rejected; the documented workaround is a scheduled home-IP top-up writing straight to
   production (see `docs/SOURCES.md`, `scripts/careerjet_topup.bat`).

## Project layout

```
src/giggregator/
  sources/       one adapter per source (fetch = network; parse = pure)
  normalize.py   pure parsing: pay, requirements, categories, scam flags
  enrich.py · dedupe.py · score.py     pure pipeline stages
  db.py          SQLite/Turso (libSQL) storage, FTS5, migrations, source health
  ingest.py      CLI ingest cycle
  web.py         FastAPI SSR app
  config.py      scoring weights, decay constants, env-driven keys
api/index.py     Vercel serverless entry (ASGI wrapper + seed snapshot)
tests/           pytest suite; per-source fixtures under tests/fixtures/sources/
docs/            ARCHITECTURE.md · DECISIONS.md (ADRs) · SOURCES.md (adapter status)
```

## Development

```bash
uv sync                      # install incl. dev deps
uv run pytest                # all tests (offline; fixtures only, no network)
uv run pytest tests/sources/test_sources_golden.py   # adapter golden tests
uv run ruff check . && uv run ruff format --check .  # lint + format gate
```

### Contributing conventions

The full contract lives in [`AGENTS.md`](AGENTS.md); the short version:

- **One adapter = one task**: adapter + committed fixtures (5–15 real captures with a dated
  `MANIFEST.md`) + golden test + a `docs/SOURCES.md` row update. Never bundle unrelated sources.
- **Fetch-then-parse separation**: `fetch()` is the only impure, network-touching code;
  `parse()` is a pure function tested offline against fixtures.
- **No network in unit tests.** Fixture-seeded databases only.
- **Never fabricate pay/requirements data.** Low-confidence parses persist `raw_text`
  alongside the parsed value; hard scam signals (pay-to-apply, training fees) auto-exclude
  the listing rather than downrank it.
- **Schema changes via migrations only; scoring-weight changes require a**
  **`docs/DECISIONS.md` ADR with a fixture-corpus score diff.**
- Never regenerate fixtures silently — a fixture refresh is an explicit, dated task.

### Adding a source adapter

1. Read [`docs/SOURCES.md`](docs/SOURCES.md) — the adapter contract, tiering (feeds/APIs
   first, HTML scraping second, community submissions third), and the live status table.
2. Check ToS/robots and access (API? feed? server-rendered HTML?) *before* writing code.
3. Implement `SourceAdapter` under `src/giggregator/sources/`, capture real fixtures with a
   `MANIFEST.md` (fetch date + why chosen), and add a golden test.
4. Update the source's row in `docs/SOURCES.md`.

### Adapter reliability

Sources drift — domains move, HTML/API schemas change, bot protection escalates. The
monitoring and remediation plan (endpoint overrides, retry/backoff, a `--probe` diagnose
mode, alarm wiring, fixture-refresh cadence) is specified in
[`docs/ARCHITECTURE.md` §10](docs/ARCHITECTURE.md).

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — full design: pipeline, canonical record,
  scoring, dedupe, flows, build order, risks
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — ADR log (stack, schema, scoring, deployment)
- [`docs/SOURCES.md`](docs/SOURCES.md) — adapter contract, tiering, and live source status
- [`AGENTS.md`](AGENTS.md) — contributor contract (iron rules, workflow, definition of done)

## License

[MIT](LICENSE) © 2026 Loel Joseph Hofileña


