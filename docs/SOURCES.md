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
| onlinejobs_ph | 1 | PH home-based VA/support/remote, structured pay data | 2h | **MVP live-verified** | card-HTML parser; pay conventions in `pay_utils` + fixture MANIFEST |
| remotive | 1 | Global remote JSON API, USD roles | 6h | **MVP live-verified** | use `/api/remote-jobs` (RSS is CF-challenged) |
| jobicy | 1 | Global remote JSON API | 6h | **MVP live-verified** | structured salaryMin/Max/Currency/Period |
| arbeitnow | 1 | Global remote JSON API (remote-only gate) | 12h | **MVP live-verified** | `published_at` often null → fallbacks |
| remoteok | 1 | — | — | blocked | Cloudflare JS challenge for plain clients |
| weworkremotely | 1 | — | — | blocked | 403 for plain clients |
| careerjet_ph | 1 | PH publisher JSON API (Basic auth, locale en_PH, keywords=remote) | 6h | **live-verified 2026-09-16** (50 jobs, hits=8280, fixture committed) | publisher key is IP-bound → whitelist caller egress IP in publisher account; per-request `user_ip` required → server egress IP via cached api.ipify.org lookup (`GIGGREGATOR_CAREERJET_USER_IP` override); `Referer` header required matching declared domain (`GIGGREGATOR_CAREERJET_REFERER`); LOCATIONS-type responses = no jobs; structured salary re-serialized to raw pay string |
| jooble_ph | 1 | PH jobs API (POST, keywords=remote, location=Philippines) | on-demand only | **deferred 2026-09-16** (quota held; fixture committed, parses 20/20) | free quota is 500 lifetime requests/key → `GIGGREGATOR_JOOBLE_ENABLED` gates ingest (default off); re-enable only for explicit one-shot refreshes |
| jobstreet_ph | 2 | Dominant PH formal board (absorbed Kalibrr), home-based filter | daily | blocked | ToS check 2026-09-15: ph.jobstreet.com/terms cl. d bars aggregating/copying any site content without agreement; SEEK terms bar robots/screen-scraping without prior written consent — no adapter without consent (ADR-0010) |
| indeed_ph | 2 | PH remote filter listings | daily | planned | |
| upwork_public | 2 | Freelance/gig search | 12h | planned | public search only |
| virtualstaff_ph | 2 | PH VA platform listings | daily | planned | |
| community_submit | 3 | FB WFH groups / TG / submit-a-gig form | continuous | later | the raket wedge |

## Source health

Keep per-source: last_success_at, last_error, error_rate, listings_7d. Silent breakage is the
#1 failure mode of aggregators — the health table is the early-warning system.
