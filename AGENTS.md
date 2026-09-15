# AGENTS.md — Giggregator

## What this is

Giggregator is the **PH remote-work search engine** for anyone with just a computing device
(PC/mobile) + internet. Scope contract: remote/WFH **online work only** — VA, support, data
entry, transcription, AI-training/annotation tasks, online tutoring, writing, dev, design,
social media, testing, microtasks — payable in ₱ or USD, performable from the Philippines.
Physical-location work, relocation abroad, and gigs requiring non-standard equipment do **not**
enter the pipeline. Full design: `docs/ARCHITECTURE.md`.

## Read first, by task type

| Task | Read |
|---|---|
| Adding/changing a source adapter | `docs/SOURCES.md` (adapter contract + status table) |
| Parsing / normalization / enrichment / scoring | `docs/ARCHITECTURE.md` + the module's tests |
| Relevance weights, schema, or stack decisions | `docs/DECISIONS.md` (write an entry) |
| Anything else | `docs/ARCHITECTURE.md` |

## Stack & commands

Stack: **Python 3.11+, uv, pytest, ruff, SQLite (FTS5)** — see `docs/DECISIONS.md` ADR-0005.
These commands are the contract; they must exist and work once the MVP scaffold lands.

- Setup: `uv sync`
- One ingest cycle: `uv run python -m giggregator.ingest --once`
- Serve (dev): `uv run uvicorn giggregator.web:app --reload`
- All tests: `uv run pytest`
- Single source: `uv run pytest tests/sources/<name>/`
- Lint: `uv run ruff check . && uv run ruff format --check .`

## Iron rules

1. **Never fabricate pay/requirements data.** A low-confidence parse is acceptable; an invented
   value is not. Always persist `raw_text` alongside any parsed field.
2. **ML/extraction must never block ingestion.** Listings enter the index on rules-only
   enrichment (confidence-flagged); model passes are async upgrades. Model down = site still
   fully functional.
3. **Adapters are read-only over the network.** No auth, no posting; respect robots.txt/ToS;
   rate-limit and cache. One adapter per source.
4. **Schema changes via migrations only.** Scoring-weight changes require a
   `docs/DECISIONS.md` entry (with a fixture-corpus score diff).
5. **No network calls in unit tests** — fixtures only (`tests/fixtures/sources/<name>/`).

## Workflow conventions

- One adapter = one task: adapter + fixtures + golden test + `docs/SOURCES.md` row update.
  Never mix unrelated sources in one change.
- Parse → normalize → enrich → score are **pure functions**; adapters are the only network
  boundary.
- Fixture refresh is an explicit task ("refresh <source> fixtures") with the fetch date noted —
  never silently regenerate fixtures.
- Dev DB is SQLite seeded from fixtures; never hand-edit a migrated DB.
- Trust/health flags and scam hard-signals (pay-to-apply, training fees) must auto-exclude, not
  downrank. See `docs/ARCHITECTURE.md` §Scam layer.

## Definition of done

- `uv run pytest` passes — **report actual output, never a recalled summary**.
- New/changed adapter → committed fixtures + golden test + `docs/SOURCES.md` row updated.
- Weights/schema/stack changed → `docs/DECISIONS.md` entry added.
- Lint clean (command above).

## Verification ritual

After any change: run the tests, show the output, state which rules above you checked against.
If asked "what checks are required after changing an adapter?", answer from this file.

# Agent Instructions

## General principles

- Understand existing code before changing it.
- Prefer the smallest correct change.
- Reuse existing abstractions.
- Do not introduce dependencies without justification.
- Do not perform unrelated refactoring.
- Never weaken tests to make them pass.
- Treat generated code as untrusted until verified.

## Development workflow

For non-trivial tasks:

Explorer
→ Architect
→ Human approval
→ Implementer
→ Verifier
→ Reviewer

For failures:

Debugger
→ Implementer
→ Verifier
→ Reviewer

## Verification

An implementation is not considered complete until the appropriate
type checks, tests, linting, build, or project-specific validation
has been performed.

## Decision boundaries

Thinking agents should not modify files.

Verification agents should not fix files.

Review agents should not silently modify files.

Implementation agents should not silently redesign architecture.

When requirements or architecture are materially unclear, stop and report
the uncertainty rather than guessing.
