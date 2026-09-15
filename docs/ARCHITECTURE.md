# Giggregator — Architecture (Master Plan v1.0)

**Thesis**: the PH remote-work search engine for anyone with just a device + internet.
In scope: remote/WFH online work (VA, support, data entry, transcription, AI training/annotation,
online tutoring, writing, dev, design, social media, QA/testing, microtasks), paid ₱ or USD.
Out of scope: physical work, relocation abroad, gigs needing non-standard equipment.

## 1. Pipeline

```
SOURCES ──> INGEST ──> RULES PASS ──> INDEX (instant, searchable)
 (tiered adapters,             │
  per-source cadence)          └──> ASYNC ENRICHMENT QUEUE ──> ML pass ──> upgrade + rescore

NORMALIZE ──> ENRICH ──> DEDUPE ──> SCORE ──> FTS5/FACETS ──> SERVE (plain HTML flows)
```

Iron rule: ML never blocks ingestion. Listings are searchable within seconds on rules-only
enrichment, flagged with confidence, then upgraded asynchronously. Model down = site functional.

## 2. Canonical Gig record

```
Gig:
  id, source_ids[], canonical_url, title, company, body_text
  posted_at, first_seen_at, last_verified_at, status (active|expired|flagged)
  pay: { kind: hourly|per_task|salary|commission, raw_text,
         hourly_equiv_php, confidence }            # single ₱-normalized pool (ADR-0004)
  requirements: { device: mobile_only|pc_required|any,
                  internet: any|stable_high,
                  hours: flexible|fixed_shift, min_hours_per_week, comms: async|live }
  payout_cadence: instant_gcash|daily|weekly|per_task|monthly
  tags[], category, no_experience_friendly: bool
  embedding (phase 1+), dedupe_key, trust_flags[]
```

## 3. Enrichment phases

- **Phase 0 (MVP, zero ML)**: regex pay extraction (~80% coverage), requirement-profile phrase
  rules, curated Taglish-aware category/skill dictionary (~15 online-work categories),
  `no_experience` heuristics.
- **Phase 1 (~150MB)**: one multilingual embedding model (`multilingual-e5-small` or
  `granite-embedding-97m-multilingual`) reused for 4 jobs: categorization (kNN vs. category
  seed texts — a new category = 5 seed sentences), semantic skill match, embedding dedupe,
  scam-farm clustering.
- **Phase 2 (~400MB)**: `NuExtract-1.5-tiny` (or Qwen2.5-0.5B GGUF) fallback extraction for
  low-confidence pay/requirements only (~20% of listings), CPU async. Free-tier cloud API only
  as later fallback. Total ML budget ≈ 550MB (< 1GB cap, open licenses).


## 4. Dedupe

Stage 1 (cheap): canonical URL + normalized `(company+title)` exact key.
Stage 2 (post-enrichment, pre-scoring): embedding similarity on `company+title+location`
(~0.85 threshold) within a 30-day window → merge: earliest `posted_at`, richest body, union of
sources (shown as "also seen on"). Prevents score double-counting.

## 5. Scoring (transparent, additive, explainable)

```
relevance = 100 × Σ(weightᵢ × factorᵢ) / Σweights

  pay      0.30   percentile in the single ₱-normalized pool; confidence-shrunk toward
                  category median for low-confidence extractions
  fresh    0.25   0.5^(age_days / 7); +boost if re-verified alive on last crawl; 0 if expired
  effort   0.15   apply friction + time-to-payout (payout_cadence) + min_hours_per_week
                  commitment + device/comms barrier
  match    0.20   tag overlap vs. user profile; anonymous default = no-exp + flexible
                  baseline; semantic (embedding) upgrade in phase 1; implicit click-feedback
                  loop (small CTR nudge on similar listings)
  trust    0.10   source health + re-verified credit + scam-signal absence
```

Every weight change requires a `docs/DECISIONS.md` entry with a fixture-corpus score diff.

### Scam layer (inside trust)

- Hard signals → **auto-exclude** (status=flagged, excluded from all flows): any upfront fee /
  pay-to-apply / pay-to-train; unverified recruiter patterns; repeat spam.
- Soft signals → downrank: no company name + text-only contact; pay far above category median
  with zero skill requirement; months-long daily reposts.
- Positive: consistent employer history, re-verified alive, engagement (clicks).
- Rules first; phase-1 embedding clusters catch new copy-paste scam farms.

## 6. Flows (filter/reweight permutations of one scored table)

| Flow | Definition |
|---|---|
| Quick Bucks | microtask/encoding/transcription/annotation ∧ no-exp ∧ low barrier ∧ fast payout |
| Highest Relevance | default weights |
| Fresh Drops | posted ≤48h ∧ active |
| No-Experience | `no_experience_friendly` (student default) |
| Mobile-Only | `device: mobile_only` |
| Flexible Hours | `hours: flexible` |

## 7. Serving

SQLite + FTS5; plain server-rendered HTML (ADR-0002). Listing line: title · pay (equiv + raw)
· age ("2d") · effort badge (⚡easy / est hours) · tags · source(s). Facets: category, device,
hours, payout cadence, pay floor. "Why this ranked here?" expander = the factor breakdown.
Pages: Home (flows + top listings), Flow pages, Search, Gig detail, Submit gig, (later) Profile.

## 8. Build order

1. **MVP spine**: OnlineJobs.ph + Remotive/RemoteOK feeds → rules enrichment → SQLite/FTS5 →
   scoring (pay+fresh+effort) → plain-HTML flows; enrichment-queue hook points stubbed.
2. Trust & quality: scam rules, dedupe, expiry detection, JobStreet adapter.
3. Phase-1 embeddings (categorization, match, dedupe upgrade).
4. Phase-2 extraction model + Tier-2/3 sources + profiles/implicit feedback.

## 9. Key risks

- Scraping fragility → disposable adapters, Tier-1-first, aggressive caching, fixtures.
- Pay-guessing errors → confidence + raw text always shown; never fabricate.
- Listing rot → expiry detection is mandatory; feeds the freshness factor.
- Scams → hard-signal auto-exclusion from day one.
- Over-scoring early → ship with 2–3 factors, iterate against the fixture corpus.
