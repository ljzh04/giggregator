# Giggregator fixtures

`tests/fixtures/sources/<source_name>/` holds **committed, real, raw listings** (HTML/JSON)
per source. They power golden/snapshot tests so parsing breaks are caught offline, instantly.

Conventions (see `.clinerules/tests.md` and `docs/SOURCES.md`):

- File naming: `<source>_<yyyymmdd>_<nn>.<ext>` — e.g. `onlinejobs_ph_20260915_01.html`.
- 5–15 listings per source; capture the same URL-pattern variety the adapter handles
  (hourly pay, per-task pay, monthly salary, low/no-pay-text edge cases).
- Every fixture folder has a `MANIFEST.md` noting: fetched date, URL(s), and why the
  fixture set was chosen (edge cases covered).
- Fixture refresh is an **explicit task**: re-fetch with the adapter, review the snapshot
  diff, update `MANIFEST.md` with the new fetch date. Never silently regenerate.
- Keep fixtures small (strip <script>/tracking bloat) but preserve the fields the parser
  reads: title, pay text, posted date, location, body, canonical URL.
- No network in tests. Ever. (Base rule: `AGENTS.md` iron rule 5.)
