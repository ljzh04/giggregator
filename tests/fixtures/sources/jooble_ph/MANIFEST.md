# Jooble fixtures

- **File**: `jooble_ph_20260916_01.json` — fetched 2026-09-16 via
  `POST https://jooble.org/api/{KEY}` with `{keywords: "remote",
  location: "Philippines", resultOnPage: 20, page: 1}` (20 jobs,
  totalCount 84769).
- **Quota note**: free Jooble keys are limited to 500 lifetime requests —
  fixtures are committed and live fetches stay at one small page per cycle.
- **Why chosen**: exercises salary-string passthrough (`"$17 - $35 per hour"`,
  `"$115k - $140k"`), empty-salary listings (pay falls back to body scan),
  snippet HTML stripping, mixed remote/on-site locations.
- **Edge cases covered**: missing salary, missing company, US-state locations
  alongside Remote ones.
