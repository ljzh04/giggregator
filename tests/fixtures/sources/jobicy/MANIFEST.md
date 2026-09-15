# Jobicy fixtures

- **File**: `jobicy_20260915_01.json` — fetched 2026-09-15 from
  `https://jobicy.com/api/v2/remote-jobs?count=50` (50 jobs, trimmed to 30 after fetch).
- **Crawl notes**: plain JSON GET, no auth, no bot protection observed.
- **Why chosen**: exercises structured salary fields (salaryMin/Max/Currency/Period) that
  the adapter re-serializes into a raw pay string, multi-valued jobType arrays, pubDate
  with timezone offsets.
- **Edge cases covered**: missing salary (null fields), non-USD currencies, jobGeo
  "Worldwide" vs specific countries.
