# Arbeitnow fixtures

- **File**: `arbeitnow_20260915_01.json` — fetched 2026-09-15 from
  `https://www.arbeitnow.com/api/job-board-api` (250 jobs, trimmed to 30 remote after fetch).
- **Crawl notes**: plain JSON GET, no auth, no bot protection observed.
- **Why chosen**: exercises the remote-only scope filter (`remote: true` gate in the
  adapter), nullable `published_at` (falls back to `created_at` then fetched_at),
  German-market listings with "Homeoffice" locations.
- **Edge cases covered**: empty company_name, freelance/part-time job_types, HTML
  description bodies.
- **Note**: this folder previously held the RemoteOK adapter's intended fixtures;
  RemoteOK's public API is Cloudflare-blocked for plain clients (403/JS challenge), so
  Jobicy + Arbeitnow fill the tier-1 global-remote quota instead (see docs/SOURCES.md).
