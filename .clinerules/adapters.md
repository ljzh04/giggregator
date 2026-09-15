---
paths:
  - "src/giggregator/sources/**"
  - "src/giggregator/sources/*"
  - "tests/sources/**"
---

# Adapter rules (delta — base rules live in AGENTS.md, don't duplicate them here)

- Follow the adapter contract in `docs/SOURCES.md` exactly: `fetch(cadence_cursor) ->
  Iterable[RawListing]`, fetch-then-parse separation.
- One adapter per source; one task per adapter (adapter + fixtures + golden test +
  `docs/SOURCES.md` row update). Never bundle unrelated sources.
- Strip tracking params from URLs; emit canonical URLs.
- Rate-limit + cache raw responses before any parsing.
- Log-and-skip bad listings; never fail the batch; never swallow the log.
- Update the per-source health fields (last_success_at, last_error, error_rate).
- No parsing logic inside the adapter — parsing is pure functions, tested against fixtures.
