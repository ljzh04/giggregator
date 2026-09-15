# Giggregator — Decisions (ADR-lite)

One entry per consequential decision: context, decision, consequences. Any scoring-weight,
schema, or stack change **requires** an entry here (per `AGENTS.md`). Newest last. Statuses:
`accepted` / `proposed` / `superseded by NNNN`.

---

## ADR-0001 — Scope: PH remote/WFH online work only
**Status**: accepted
**Context**: original idea was global gigs (full-time → per-task, incl. local physical gigs).
**Decision**: narrow to remote/WFH work performable from PH on PC/mobile + internet, paid in
₱ or USD. Excludes physical gigs, relocation, non-standard equipment.
**Consequences**: kills location modeling + offline-logistics estimation; enables single ₱ pay
pool; sharpens product identity; tier-1 sources = OnlineJobs.ph + global remote feeds.

## ADR-0002 — SQLite + FTS5, plain server-rendered HTML
**Status**: accepted
**Decision**: SQLite + FTS5 storage/search; no JS framework; server-rendered HTML lists with
facet filters. Boring on purpose.
**Consequences**: hundreds of thousands of listings on a laptop; zero ops; trivial agent-manageable.

## ADR-0003 — Rules first; one embedding model, four jobs; tiny extraction fallback
**Status**: accepted
**Decision**: Phase 0 pure rules/regex. Phase 1 adds one multilingual embedding model
(multilingual-e5-small or granite-embedding-97m, ~150MB) reused for categorization (kNN vs seed
texts), semantic skill match, dedupe similarity, scam clustering. Phase 2 adds
NuExtract-1.5-tiny/Qwen2.5-0.5B GGUF (~400MB) as async fallback for low-confidence extractions.
ML never in the blocking ingestion path. Total ≈550MB (<1GB budget, open licenses, CPU-runnable).
**Consequences**: zero marginal cost; graceful degradation; no general-purpose local LLM in the
request path; no per-category fine-tuned classifiers.

## ADR-0004 — Single ₱-normalized pay pool
**Status**: accepted
**Decision**: FX-convert USD to ₱ (daily cached rate table), score pay percentile in one pool;
display in native currency (₱ default, USD kept for USD roles).
**Consequence**: simpler than the earlier two-bucket design; valid because all in-scope listings
are comparable online work.

## ADR-0005 — Stack: Python 3.11+, uv, pytest, ruff, SQLite/FTS5
**Status**: accepted (MVP scaffold landed on this stack; local interpreter is 3.11)
**Decision**: Python for ingestion/parsing/NLP (best scraping + small-model ecosystem);
uv for env/dependency management; pytest + golden fixtures; ruff for lint/format.
FastAPI + httpx + beautifulsoup4 for serving/fetching/parsing.

## ADR-0006 — Agent guidance: short AGENTS.md map + docs/ depth + thin tool deltas
**Status**: accepted
**Decision**: root `AGENTS.md` ≤~100 lines as TOC + iron rules + commands; depth in
`docs/{ARCHITECTURE,SOURCES,DECISIONS}.md`; Cline gets path-scoped deltas in `.clinerules/`;
Copilot gets a thin `.github/copilot-instructions.md` delta; opencode reads AGENTS.md natively.
No symlink tricks (Windows portability). No rule duplication across files.
**Consequence**: small, current, non-redundant agent context; non-negotiables enforced by
tests/CI rather than prose alone.

## ADR-0007 — Scoring v0 weights
**Status**: accepted (initial)
**Decision**: `relevance = 100 × Σ(weightᵢ × factorᵢ) / Σweights` with
pay 0.30 · fresh 0.25 · effort 0.15 · match 0.20 · trust 0.10.
Fresh = `0.5^(age_days/7)`, boost if re-verified alive, 0 if expired. Pay percentile-ranked,
confidence-shrunk toward category median. Effort = apply friction + time-to-payout +
min-hours commitment + device/comms barrier. Match = tag overlap vs. profile (anonymous
default: no-exp + flexible baseline). Trust = source health + re-verified credit + scam-signal
absence. Flows (Quick Bucks / Fresh / No-Experience / Mobile-Only / Flexible) are
filter/reweight permutations of the same table.
**Consequence**: changing any weight ⇒ DECISIONS entry + fixture-corpus score diff.

## ADR-0008 — MVP source set + OnlineJobs pay conventions
**Status**: accepted (live-verified 2026-09-15)
**Context**: RemoteOK's API is Cloudflare-blocked and WeWorkRemotely 403s plain clients;
Remotive's RSS is CF-challenged but its JSON API works.
**Decision**: MVP tier-1 set = OnlineJobs.ph (card HTML) + Remotive API + Jobicy API +
Arbeitnow API (remote-only gate). OnlineJobs pay strings are unit-ambiguous; conventions:
explicit `$`/Php markers set currency, bare numbers magnitude-guessed (`<20` → USD else PHP),
no explicit period ⇒ `>=100` treated as PH monthly salary, below as hourly piece rate;
confidence penalties apply and scoring shrinks low-confidence pay toward the corpus median.
Body-scan pay fallback requires currency/salary markers and clamps to ₱15–7,500/hr (live
false positive: "10 million visitors per month"). Dedupe merge tie-break prefers the newer
extraction on equal confidence.
**Consequence**: honest degradation instead of fabricated certainty; source substitutions
documented in `docs/SOURCES.md` status table.

## ADR-0009 — Expiry / re-crawl policy (hybrid 30d/90d + revive)
**Status**: accepted (2026-09-15)
**Context**: ARCHITECTURE.md mandates expiry detection, but nothing set `status=expired` —
stale gigs accumulated forever. All four adapters serve bounded recent lists (top-50), so
absence from a feed does **not** mean a gig is gone; miss-counting would expire live gigs.
Per-URL re-GET would violate the thin-fetch contract and politeness rules.
**Decision**: staleness-based expiry in `db.expire_stale_gigs()`, run each ingest cycle
before rescore. An active gig expires when `last_verified_at` is older than
`EXPIRY_VERIFIED_TTL_DAYS=30` (unseen for a month) or `posted_at` is older than
`EXPIRY_ABSOLUTE_MAX_DAYS=90` (hard cap even if re-seen). Re-seen expired gigs revive to
active on upsert; a newly-flagged extraction overrides to flagged (scam signals win).
`score_gig` forces `fresh=0.0` for expired rows per ARCH §5 (belt-and-braces with the
active-only serving filter). Thresholds live in `config.py`; changing them requires a new
ADR entry.
**Consequence**: the index self-cleans without extra network; revive keeps long-lived
reposted gigs alive; expiry is a policy knob, not a code change.

## ADR-0010 — JobStreet excluded on ToS grounds
**Status**: accepted (2026-09-15)
**Context**: `SOURCES.md` listed jobstreet_ph as Tier 2 planned, "scraping ToS check
first". Checked 2026-09-15: robots.txt permits generic-bot `?keywords` search URLs, but
robots.txt is not permission — the official Terms (ph.jobstreet.com/terms, cl. d) bind all
users to not "aggregate, copy or duplicate in any matter any of the Content or information
available from any of our websites and apps or Services ... other than as permitted by
these Terms or another agreement"; SEEK advertising terms likewise bar data mining,
robots, and screen scraping without prior written consent.
**Decision**: no JobStreet adapter. Status-table row → blocked. Revisit only with written
consent or a documented API under its terms (iron rule 3: respect robots.txt/ToS).
**Consequence**: Tier-2 PH-formal-board coverage stays open; API-based Tier-1 candidates
(CareerJet / Jooble publisher APIs, which grant keyed access under their own terms) are
the next-best PH coverage bets.

## ADR-0011 — Hosting: Vercel web + Turso (libSQL) DB + GitHub Actions ingest
**Status**: accepted (2026-09-15)
**Context**: Deployment needs a public URL (Careerjet publisher application) but the
MVP stack is a server-rendered FastAPI app over a local SQLite/FTS5 file (ADR-0002/0005).
Vercel's serverless filesystem is ephemeral — a SQLite file there does not survive
instance recycling, and Vercel Hobby crons run at most once daily (contract cadence is
2–6h). Postgres alternatives (Supabase/Neon) would require rewriting the FTS5 search
layer; Supabase's free tier also pauses after 1 week of inactivity.
**Decision**: Keep SQLite semantics and switch only the storage *location*:
1. **DB**: Turso cloud database on the classic **libSQL** engine (FTS5 verified working
   over its HTTP API). Local `db.connect()` behavior is unchanged; when
   `TURSO_DATABASE_URL` is set, `db.connect()` connects remotely through the `libsql`
   driver wrapped by `_RemoteConn` so call sites never branch on backend. The driver
   lacks `row_factory`, so remote rows are wrapped in a dict-based `_Row` supporting
   `row["col"]` access. Free tier: 5 GB / 500M reads / 10M writes per month.
2. **Web**: Vercel (framework preset "Other"), `api/index.py` re-exporting
   `giggregator.web:app` behind a catch-all rewrite; dependencies via an exported
   `requirements.txt` (Vercel does not read pyproject/uv.lock).
3. **Ingest**: GitHub Actions scheduled workflow (every 6h, manual dispatch available)
   running `python -m giggregator.ingest --once` with Turso credentials as repo
   secrets — restores contract cadence that Vercel Hobby crons cannot.
**Consequences**: (a) engine lock-in to libSQL-compatible SQLite — any future DB change
must preserve FTS5 or rewrite `db.search_gig_ids` (DECISIONS entry required);
(b) tests must never run with `TURSO_DATABASE_URL` exported — they always use local
`:memory:`/tmp SQLite (iron rule 5); (c) search latency is network round-trip per page
load; acceptable at MVP traffic, revisit with embedded replicas if it bites;
(d) `.env` holds credentials locally and is gitignored; rotate tokens that have been
exposed outside secret stores.
