---
paths:
  - "tests/**"
---

# Test rules (delta — base rules live in AGENTS.md, don't duplicate them here)

- No network. Unit tests use committed fixtures from `tests/fixtures/sources/<name>/`.
- Golden/snapshot pattern: parse output over a source's fixture corpus is snapshotted; a
  snapshot diff is a review artifact, not noise — explain or fix it.
- Test names: `test_<behavior>_when_<condition>`.
- Parse/normalize/enrich/score are pure functions — test them directly, no mocking.
- Never edit fixtures to make a test pass unless it's an explicit fixture-refresh task
  (then note the fetch date in the fixture README).
- DB-touching tests use the fixture-seeded dev SQLite; migrations tests run against fresh DBs.
