# Remotive fixtures

- **File**: `remotive_20260915_01.json` — fetched 2026-09-15 from
  `https://remotive.com/api/remote-jobs?limit=50` (16 jobs).
- **Crawl notes**: plain JSON GET works without Cloudflare issues (the RSS feed at
  `/feed/remote-jobs` is Cloudflare-challenged for plain clients — use the API).
- **Why chosen**: exercises the k-notation salary parsing (`"$31,2k- $52k"` with European
  decimal comma), HTML description stripping, tag lists, publication dates.
- **Edge cases covered**: missing salary (pay falls back to body scan), Worldwide locations,
  full-time/part-time job types.
