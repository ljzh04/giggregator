# Giggregator — Sources

Adapters turn one external source into canonical `RawListing`s. **One adapter per source.**
This file holds the adapter contract and the live status table — update the row whenever you
touch a source (per `AGENTS.md`).

## Adapter contract

```python
fetch(cadence_cursor) -> Iterable[RawListing]

RawListing: { source_id, url, title, body, posted_at_raw,
              pay_raw, location_raw, fetched_at }
```

Rules (see also `AGENTS.md` iron rules 3 & 5):

- Read-only over the network: no auth, no posting, respect robots.txt/ToS.
- Rate-limit per source; cache raw responses before parsing.
- Never let one bad listing fail a batch: log + skip; surface in source health.
- Emit canonical/deduped URLs (strip tracking params).
- Fetch-then-parse separation: adapter fetches; pure functions parse/normalize (testable offline).
- Every adapter ships with 5–15 committed real fixtures in `tests/fixtures/sources/<name>/`
  plus a golden test that runs the full parse over them (snapshot on parse output).

## Tiering & cadence

| Tier | Method | Cadence |
|---|---|---|
| 1 | Feeds / APIs (MVP first) | 1–6h |
| 2 | HTML scraping (URL-filtered) | daily |
| 3 | Community / user submissions | continuous |

## Status table

| Source | Tier | What it gives us | Cadence | Status | Notes |
|---|---|---|---|---|---|
| onlinejobs_ph | 1 | PH home-based VA/support/remote, structured pay data | 2h | **MVP live-verified** | card-HTML parser; pay conventions in `pay_utils` + fixture MANIFEST; paginates up to `MAX_PAGES` (3) result pages/cycle |
| remotive | 1 | Global remote JSON API, USD roles | 6h | **MVP live-verified** | use `/api/remote-jobs` (RSS is CF-challenged) |
| jobicy | 1 | Global remote JSON API | 6h | **MVP live-verified** | structured salaryMin/Max/Currency/Period |
| arbeitnow | 1 | Global remote JSON API (remote-only gate) | 12h | **MVP live-verified** | `published_at` often null → fallbacks |
| remoteok | 1 | — | — | blocked | Cloudflare JS challenge for plain clients |
| weworkremotely | 1 | — | — | blocked | 403 for plain clients |
| careerjet_ph | 1 | PH publisher JSON API (Basic auth, locale en_PH, keywords=remote) | 6h | **live-verified 2026-09-16** (50 jobs, hits=8280, fixture committed) | publisher key is IP-bound → whitelist caller egress IP in publisher account; per-request `user_ip` required → server egress IP via cached api.ipify.org lookup (`GIGGREGATOR_CAREERJET_USER_IP` override); `Referer` header required matching declared domain (`GIGGREGATOR_CAREERJET_REFERER`); LOCATIONS-type responses = no jobs; structured salary re-serialized to raw pay string; paginates up to `MAX_PAGES` (3) pages using the response `pages` metadata (per-page jobs merged into one payload); Vercel cron egress IPs rotate → 403 from serverless (cycle isolation contains it; home-IP top-up covers it: `uv run --env-file .env python -m giggregator.ingest --once --only careerjet_ph --db prod` writes straight to production Turso; automated daily 08:30 via Windows scheduled task `Giggregator CareerJet top-up` → `scripts/careerjet_topup.bat`) |
| jooble_ph | 1 | PH jobs API (POST, keywords=remote, location=Philippines) | on-demand only | **deferred 2026-09-16** (quota held; fixture committed, parses 20/20) | free quota is 500 lifetime requests/key → `GIGGREGATOR_JOOBLE_ENABLED` gates ingest (default off); re-enable only for explicit one-shot refreshes |
| jobstreet_ph | 2 | Dominant PH formal board (absorbed Kalibrr; Kalibrr still operates its own board — see kalibrr_ph), home-based filter | daily | blocked | ToS check 2026-09-15: ph.jobstreet.com/terms cl. d bars aggregating/copying any site content without agreement; SEEK terms bar robots/screen-scraping without prior written consent — no adapter without consent (ADR-0010) |
| indeed_ph | 2 | PH remote filter listings | daily | planned | ToS caution: Indeed ToS bars scraping; probe alternative access before building |
| upwork_public | 2 | Freelance/gig search | 12h | planned | public search only |
| himalayas | 1 | Global remote JSON API, structured salary + employment type | 24h | **candidate — verified 2026-09-18** | free public API, no auth (`/jobs/api` browse w/ cursor paging `limit≤20`, `/jobs/api/search` filters); docs explicitly permit job-board operators; `minSalary`/`maxSalary`+ISO currency; `employmentType` enum maps ~1:1 to ADR-0015 constants; data refreshes every 24h → set cadence 24h and respect the 429; recommended next adapter |
| welocalize_lever | 1 | AI-training/annotation/search-rater roles via public Lever postings API | daily | **candidate — verified 2026-09-18** | `api.lever.co/v0/postings/weloglobal?mode=json` returns live no-auth JSON (probe >5MB → use Lever query filters / parse a subset); fills the AI-training category gap; Lever pattern reusable for other AI-training firms on Lever/Greenhouse |
| workingnomads | 1 | Global remote JSON feed (title, category, tags, location, pub_date) | 12h | **candidate — endpoint verified 2026-09-18** | `/api/exposed_jobs/` live, no-auth (~hundreds of jobs, HTML body); **no salary field** → body-scan pay parse, low confidence; docs page 404'd → confirm attribution terms (historically "Powered by Working Nomads") before adapter |
| kalibrr_ph | 2 | PH board with structured ₱ monthly ranges + FULL_TIME/PART_TIME badges + Remote category | daily | **candidate — ToS check pending** | live 2026-09-18 w/ server-rendered WFH listings (e.g. ₱34–35k/mo online tutors) — would be 2nd PH source w/ structured pay; **SEEK-owned** (JobStreet parent, cf. ADR-0010); terms page JS-walled → explicit ToS verdict required before any adapter |
| philjobnet | 2 | DOLE official portal; accredited-employers-only | daily | **candidate — probe volume** | gov-run, free, server-rendered, no API documented; employer accreditation = built-in trust signal (candidate for elevated `source_reliability`, ADR-0014); check remote/WFH listing volume |
| mynimo | 2 | Cebu-centric PH board, dedicated "Work From Home" category (~40 listings) | daily | **candidate — low volume** | server-rendered; small but PH-targeted; look for RSS/feed; cheap tier-2 add |
| crowdgen_appen | 2 | AI-training project board (Appen's CrowdGen) | — | blocked | projects are login-gated; no public listing surface (verified 2026-09-18); at best tier-3 community content |
| virtualstaff_ph | 2 | PH VA platform listings | daily | **dropped 2026-09-18** | site no longer has publicly browsable listings — homepage is a login-gated "Seats" staffing funnel; scrape target assumed by this row no longer exists (verified 2026-09-18) |
| community_submit | 3 | FB WFH groups / TG / submit-a-gig form | continuous | later | the raket wedge |

## Source health

Keep per-source: last_success_at, last_error, error_rate, listings_7d. Silent breakage is the
#1 failure mode of aggregators — the health table is the early-warning system.

Surfaced read-only at `GET /health` (JSON): per-source `last_success_at`, `age_hours`,
`stale` (no success within `SOURCE_STALE_HOURS`, default 48h), `has_error`/`error_count`,
`listings_7d`, and the scoring `reliability` (ADR-0014), plus `active_gigs`/`flagged_gigs`.
Raw `last_error` text is intentionally **not** exposed — adapter error messages can embed
key-bearing request URLs.
