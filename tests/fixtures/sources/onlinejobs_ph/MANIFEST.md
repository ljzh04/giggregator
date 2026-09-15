# OnlineJobs fixtures

- **File**: `onlinejobs_ph_20260915_01.html` — fetched 2026-09-15 from
  `https://www.onlinejobs.ph/jobseekers/jobsearch` (home-based job cards).
- **Crawl notes**: plain GET with a browser UA works today; no auth. Watch for
  Cloudflare challenges on future fetches — if the fixture stops refreshing cleanly,
  check the source-health table first.
- **Why chosen**: the pay `<dd>` column is unit-ambiguous gold for the pay parser:
  `"$7/hour"`, `"500-700"`, `"120/hr"`, `"1000"`, `"400/Month"`, `"750 to 1200 per month"`,
  `"$3/gig"`, `"$6–$7 USD/hour depending on experience"`, `"$800 month"`,
  `"Negotiable – based on experience"`, `"$500-1000/month DOE"`, `"Php 45,000 - Php 63,000"`.
- **Documented heuristics** (`pay_utils._onlinejobs_defaults`): explicit `$`/Php markers set
  currency; bare numbers are magnitude-guessed (`<20` → USD, else PHP). Period: explicit
  markers left to the shared parser; otherwise values `>= 100` are treated as PH monthly
  salaries, below that as hourly piece rates. Confidence penalties apply; scoring shrinks
  low-confidence pay toward the corpus median so wrong guesses degrade gracefully instead
  of fabricating certainty.
- **Edge cases covered**: badge types (Gig / Part Time / Full time), `data-temp-2` UTC
  posted dates, tag badges, desc excerpts with truncated links.
