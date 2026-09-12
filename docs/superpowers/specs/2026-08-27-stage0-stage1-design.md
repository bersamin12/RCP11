# Stage 0 & Stage 1 Design — Research Operating System (overhaul)

**Status:** Draft v1.0 — 2026-08-27
**Scope:** Stage 0 (direction → research field) and Stage 1 (field → research questions) only.
**Supersedes:** the Stage 0/1 portions of `docs/PRD.md` Modules 1–2. Stages 2+ (spec compilation,
simulation, analysis, reporting) are unchanged and out of scope here.
**Target:** a new repository. This repo supplies the domain lock, the typed-object discipline,
and the deterministic-ranking pattern; its code is reference, not a base.

---

## 1. Purpose

Turn a vague research direction into a small set of evidence-grounded, testable research
questions, with every claim traceable to specific papers and quotes.

Stage 0 narrows: *vague direction → theme → field*, with a human gate at each narrowing.
Stage 1 mines: *field → gap summaries → ranked gaps → broadened research questions →
verified research questions*, ending at a human selection gate.

Stage 1's output is an `IdeaBundle`. Nothing in this spec compiles a spec, runs a simulation,
or writes a report.

### 1.1 Vocabulary

Both are the same object (`ResearchField`) at different granularities.

- **Theme** — a coarse Leiden cluster from Stage 0 round 1. Answers *"which part of this
  literature?"* Typically 200–1000 papers. Roughly OpenAlex **subfield** granularity.
  Example: *Cooling & thermal management*.
- **Field** — a fine Leiden cluster from round 2, computed inside the chosen theme. Answers
  *"which specific problem?"* Typically 50–250 papers. Roughly OpenAlex **topic** granularity.
  Example: *Chilled-water plant optimisation & chiller sequencing*.

**Operational test for "field, not theme":** can a single research question be stated in it
whose answer would change practice, naming variables and metrics? If not, it is still a theme.

---

## 2. Decisions and rationale

| # | Decision | Rationale |
|---|---|---|
| D1 | **Domain-locked to data centres** throughout Stage 0/1 | Downstream stages execute Modelica models for data-centre cooling; an unconstrained corpus produces questions no registered model can test |
| D2 | **LangGraph (Python) orchestrates; pi runs as a subprocess** | The science stack (graph algorithms, clustering, HTTP federation) is Python-native; pi is TypeScript-only with no Python SDK |
| D3 | **Hybrid similarity graph + Leiden**, not HDBSCAN | Citation links inside one keyword slice are sparse and penalise recent work; embeddings alone discard the citation structure. Fusing citation + bibliographic coupling + semantic kNN keeps recent papers clusterable and makes each channel ablatable |
| D4 | **Two fixed narrowing rounds**, not an open dialogue | Bounded cost, exactly two gates, every round is a checkpointable node |
| D5 | **Bounded agentic probe** for gap verification | The only genuinely unbounded step; capped tool calls keep cost knowable while preserving agency |
| D6 | **Shared cache + frozen per-run view** | Round 2 is a subset of round 1; re-fetching is waste. A recorded `corpus_hash` preserves reproducibility (PRD X.3) |
| D7 | **One source defines the corpus; all others only enrich** | Multi-source discovery would make a run's paper set irreproducible |
| D8 | **Free-tier sources are the required path; institutional sources are optional plug-ins** | Anyone must be able to reproduce a run; licence terms forbid redistributing Elsevier/IEEE content |
| D9 | **Graph state holds references, not corpora** | 3000 papers cannot be inlined into a checkpoint |
| D10 | **Prevalence is deterministic and quote-bound** | It is the one ranking axis that must not be an LLM assertion |

---

## 3. Architecture

### 3.1 Package layout

```
src/ros/
  contracts/      typed pydantic objects — the ONLY module every other one imports
  knowledge/      Knowledge Sub System
      sources/      one adapter per data source (see §5); `sources/openalex.py` is the
                    discovery client and owns landscape / sweep / probe queries
      merge.py      cross-source record merge + field provenance
      origin.py     origin + domain filter (deterministic)
      graph.py      edge construction (citation / coupling / semantic)
      cluster.py    Leiden + cluster characterisation
      embed.py      fallback embedder (papers) + sentence embedder (gap statements)
      store.py      shared SQLite cache + frozen run views
  idea/           Idea Sub System
      select.py     budgeted, stratified paper selection
      summarise.py  four-channel gap summaries
      mine.py       gap grouping + synthesis
      rank.py       prevalence / impact / novelty
      broaden.py    gap → research question
      verify.py     fan-out probe orchestration
  pi/             pi subprocess adapter
      runner.py     invoke, JSON contract, timeout, budget accounting
      roles/        one prompt file per pi role
      tools/        tool schemas exposed to the probe role only
  graph/          LangGraph: state, nodes, gates, build
  cli.py
```

Each subpackage depends only on `contracts/`. `knowledge/` never imports `idea/`.

### 3.2 The pi adapter

```python
run_pi(role: str, payload: dict, schema: type[T],
       tools: list[Tool] | None = None, budget: PiBudget) -> T
```

Spawns pi headless, supplies `roles/<role>.md` as the system prompt and the payload as JSON on
stdin, and requires a final JSON object validating against `schema`. One reprompt on invalid
JSON, then hard failure. Token usage and wall-clock are recorded per call in the `pi_calls`
ledger.

**Two backends.** `direct` — a single provider-agnostic LLM call — serves the one-shot roles and
is what CI and low-budget runs use. `pi` — the real subprocess with a tool loop — is required
only for the verification probe. Consequences: the system is runnable and testable without pi
installed, and pi's documented lack of a permission system is contained to exactly one process,
which is the only one containerised (network egress restricted to the source API hosts).

**Roles.** Every LLM step is a role with a prompt file under `pi/roles/`. Only one of them
requires the `pi` backend; the rest run on either.

| Role | Stage | Calls per run | Tools | Backend |
|---|---|---|---|---|
| `plan_direction` | 0 | 1 per round (≤2) | none | direct or pi |
| `label_clusters` | 0 | 1 per round (≤2) | none | direct or pi |
| `summarise_paper` | 1 | ~60 (one per selected paper) | none | direct or pi |
| `synthesise_gaps` | 1 | 1 | none | direct or pi |
| `rank_gaps` | 1 | 1 | none | direct or pi |
| `broaden_gap` | 1 | 1 (batched over top-K gaps) | none | direct or pi |
| `verify_gap` | 1 | 1 per surviving RQ (≤8) | `search_literature` | **pi required** |

`summarise_paper` is deliberately many small `direct` calls rather than an agent task: it is 60
independent cheap extractions with no need for tool use or multi-turn reasoning.

---

## 4. Data contracts

All objects are pydantic models carrying `schema_version`, and every derived object carries the
IDs of what it was derived from.

| Object | Fields (abridged) |
|---|---|
| `ResearchDirection` | `text`, `constraints[]`, `scope_override`, `created_at` |
| `SearchPlan` | `round`, `queries[]`, `openalex_filters{}`, `expansion_seeds[]`, `rationale` |
| `PaperRecord` | OpenAlex id, `doi`, title, abstract, year, type, authors, venue, `referenced_works[]`, `cited_by_count`, OA/licence fields, `topics[]`, `primary_topic`, `specter_v2`, `tldr`, `citation_contexts[]`, `venue_tier`, `integrity{doaj, retracted, crossmark, publisher, is_preprint}`, `origin_verdict{keep, score, reasons[]}`, `field_provenance{field: [sources]}` |
| `CorpusSnapshot` | `run_id`, `round`, `plan`, `paper_ids[]`, `corpus_hash`, counts, `degraded_sources[]`, `params{alpha,beta,gamma,resolution,seed}`, `fetched_at` |
| `KnowledgeGraph` | `nodes[]`, `edges[{src,dst,type,weight}]`, `clusters{id:{label, description, paper_ids[], keywords[], size, exemplars[], median_year, growth_rate, top_venues[], topic_ids[]}}` |
| `ResearchField` | `id`, `label`, `description`, `level` (`theme`\|`field`), `cluster_ids[]`, `topic_ids[]`, `paper_count`, `exemplars[]`, `maturity{median_year, growth_rate}` |
| `GapSummary` | `paper_id`, `items[{statement, channel, evidence_strength, quote, locator, source_paper_id}]`, `extraction_basis` (`abstract`\|`full_text`), `access_source` |
| `Gap` | `id`, `statement`, `category`, `paper_ids[]`, `summary_item_ids[]`, `prevalence_count`, `inferred_support_count`, `inferred_only`, `scores{prevalence, impact, novelty}`, `score`, `weights{}`, `rank` |
| `ResearchQuestion` | `id`, `question`, `broadened_from` (gap id), `broadening_note`, `variables[]`, `metrics[]`, `expected_effect`, `risks[]`, `candidate_models[]`, `model_gap_note` |
| `VerificationVerdict` | `rq_id`, `verdict` (`addressed`\|`partial`\|`open`\|`unknown`), `evidence[{paper_id, quote}]`, `queries_used[]`, `tool_calls_used`, `confidence`, `note` |
| `IdeaBundle` | `run_id`, `field`, `corpus_hash`, `questions[]`, `verdicts[]`, `gaps[]`, `generated_at` |
| `GateRequest` / `GateResponse` | `gate_id`, `kind`, `options[]`, `context{}` / `selection`, `feedback` |

### 4.1 Two deliberate departures from the current repo

1. **`PaperRecord` is not `PaperCard`.** Stage 0 handles thousands of papers, so per-paper LLM
   extraction is unaffordable there. `PaperRecord` is metadata-only. LLM extraction is deferred
   to Stage 1, over the chosen field's papers only.
2. **Gap provenance is quote-bound.** A `Gap` may only count a paper toward `prevalence_count`
   when a `GapSummary` item cites a verbatim quote from it.

---

## 5. Multi-source federation

**Governing rule (D7): OpenAlex defines the corpus. Every other source only enriches records
that already exist.** Enrichment never adds or removes a paper. Without this, `corpus_hash`
means nothing.

### 5.1 Sources

| Source | Role | Unique contribution | Auth |
|---|---|---|---|
| **OpenAlex** | Spine — discovery, ID space, citation edges | Coverage, Topics hierarchy, `referenced_works`, retraction/paratext flags | `mailto` |
| **Semantic Scholar Graph** | Enrichment | `embedding.specter_v2`, `citations.contexts` + SciCite `intents`, `tldr` | free key, 1 req/s |
| **Crossref** | Integrity | Publisher, Crossmark retraction/update notices, funder; metadata backstop | `mailto` |
| **DOAJ** | Legitimacy | Journal-level vetting — the non-heuristic answer to "suspicious publisher" | none |
| **DBLP** | Venue normalisation | Clean conference identity and conference-vs-workshop separation for CS/systems venues (OSDI, NSDI, SIGCOMM, ASPLOS, SoCC), where OpenAlex venue strings are unreliable and DOAJ does not apply | none |
| **Unpaywall / OA locations** | Full text (free) | Open-access PDFs for Stage 1 | email |
| **arXiv** | Recency | Preprints, flagged unreviewed | none |

**Optional institutional plug-ins (D8), full text only, never discovery:**

| Source | Access | Contribution |
|---|---|---|
| **Elsevier ScienceDirect TDM** | dev.elsevier.com key + institutional token; NTU subscription | Full text of *Applied Thermal Engineering*, *Energy and Buildings*, *Applied Energy* — the core paywalled journals for data-centre cooling |
| **IEEE Xplore** | NTU subscription, key by request | Full text of ITherm / SEMI-THERM / IEEE journals |

Deliberately excluded: Scopus and Web of Science (duplicate what OpenAlex + DOAJ + DBLP already
provide, at the cost of two more adapters and two more licence regimes); OpenAIRE, Europe PMC,
CORE, Dimensions, Lens.org (redundant with OpenAlex for a data-centre corpus).

### 5.2 Why Semantic Scholar is load-bearing

1. `embedding.specter_v2` supplies the semantic edges of the hybrid graph with **no local
   embedding model and no GPU** for papers. `embed.py` is reduced to a fallback for papers S2
   does not cover, plus sentence embedding for gap statements (§7.3).
2. `citations.contexts` + `intents` give the sentences in which **later** papers cite this one.
   A paper's self-reported limitations are systematically modest; its citation contexts are
   where other researchers state what it failed to do. This is the strongest gap-mining channel.
3. `tldr` gives uniform one-sentence summaries for cluster labelling and summary priors.

### 5.3 Federation mechanics

A `Source` protocol with three capabilities: `discover(plan) -> ids`, `enrich(ids) -> partials`,
`verify(id) -> integrity`. Merge is DOI-first, then title+year fuzzy match, with per-field
precedence and `field_provenance` recorded on every record. Every response is cached with
`fetched_at` and `etag`.

### 5.4 Rate limits (these constrain the pipeline, not just the client)

- OpenAlex: polite pool with `mailto`; `cursor=*`, `per_page=200`, trimmed `select=`.
  A 3000-paper sweep is ~15 requests.
- Semantic Scholar: the unauthenticated pool is shared across all anonymous users and unusable
  at scale. A free API key grants a dedicated **1 request/second**. Enrichment therefore runs as
  a batched background pass over the corpus (`/paper/batch`, 500 IDs per request — 3000 papers
  ≈ 6 requests), never inline per paper.
- **Hard requirement:** a run must complete correctly, with degraded semantic edges, when S2 is
  unavailable.

---

## 6. Knowledge Sub System

Three modes over a shared pipeline.

### 6.1 Mode A — `landscape()`

One request:
`/works?filter=title_and_abstract.search:<direction>,<domain guard>&group_by=primary_topic.id`,
plus a `publication_year` grouping. Returns a topic histogram **without downloading any works**,
so query planning is grounded in the real shape of the literature. Also drives entry-route
classification (§7.1).

### 6.2 Mode B — `sweep()`

1. **Plan** — pi role `plan_direction`: direction + histogram → `SearchPlan`. Filters always pin
   `is_retracted:false`, `is_paratext:false`, scholarly types, and a date window.
   Search uses `title_and_abstract.search`, **not** `title.search`: a large share of relevant
   data-centre thermal work never puts the keyword in the title, and title-only search is a
   recall trap. Precision is recovered by the origin filter and clustering, not by the query.
2. **Fetch** — cursor paging, `per_page=200`, trimmed `select=`. Hard cap, default 3000/round.
3. **Origin filter** — deterministic and scored, never LLM:
   - *Hard drops*: retracted, paratext, non-scholarly type, untitled.
   - *Scored signals*: DOAJ listing, Crossref publisher, DBLP venue tier, citations-vs-age,
     preprint status, missing abstract.
   - *Domain lock*: `primary_topic`/`topics` must intersect the data-centre allowlist, or
     title+abstract must match the domain lexicon.
   - **Every drop records a reason**, so the filter is auditable and tunable.
4. **Enrich** — S2 batch (§5.4). Missing S2 data degrades edges; it never fails the run.
5. **Graph** — nodes are kept papers; three edge types:
   - `cites` — `referenced_works` restricted to in-set targets
   - `coupling` — bibliographic coupling via an inverted reference index, minimum 2 shared
     references, normalised
   - `semantic` — mutual-kNN (k ≈ 10) on SPECTER2 cosine

   Fused weight `α·cites + β·coupling + γ·semantic`, defaults 1.0 / 0.7 / 0.5, **recorded in the
   snapshot** so clustering is reproducible and each channel is ablatable.
6. **Leiden** — on the fused weighted graph; resolution auto-tuned by binary search to a 5–15
   cluster target; clusters under 3 papers fold into `unclustered`; seed recorded.
7. **Characterise** (deterministic) — per cluster: size, c-TF-IDF terms, exemplars by citation
   count and by in-cluster PageRank, year histogram, median year, growth rate, top venues,
   top OpenAlex topics.
8. **Label** — pi role `label_clusters`, **one call covering all clusters** (terms + 5 exemplar
   titles + tldrs each), returning a label and one-line description per cluster. A single call
   keeps labels mutually distinguishable and costs almost nothing.
9. **Persist** — `KnowledgeGraph` + `CorpusSnapshot`, `corpus_hash = hash(sorted paper_ids +
   plan + params)`.

### 6.3 Mode C — `probe()`

Same fetch and origin filter, capped at ~50 papers, no graph, no clustering. Exposed to the
verification agent as the tool `search_literature(query, year_from, limit)`.

---

## 7. Stage 0 — narrowing

### 7.1 Entry routes

`intake` classifies input specificity from the `landscape()` call it makes anyway: topic
histogram concentration (top-topic share / Herfindahl) and result count give a deterministic
signal; `plan_direction` returns a verdict alongside it.

| Route | Input looks like | Path |
|---|---|---|
| `broad` | "data centre efficiency" | round 1 → Gate 1 → round 2 → Gate 2 |
| `theme` | "data centre cooling" | skip round 1 and Gate 1; one narrow sweep → Gate 2 |
| `field` | "chiller sequencing in data centres" | one focused sweep + expansion → cluster → **Gate C** |
| `question` | "does predictive chiller sequencing beat threshold sequencing" | build corpus → **Gate C** → **formalise into a `ResearchQuestion`** via `broaden_gap` in formalise mode (§8.5) → verification (§8.6), skipping §8.1–8.4 |

The route is a **default, not a verdict**: `--scope broad|theme|field|question` overrides the
classifier. State records `entry_route` and `route_reason`; `CorpusSnapshot` records which
rounds ran.

The `field` route still sweeps and still clusters — Stage 1 needs a clustered corpus regardless.
What is skipped is narrowing, not retrieval. Clustering the field's own corpus frequently
reveals that a stated field is two communities (e.g. rule-based plant control vs. MPC/learning
control), which is exactly what the user needs to see before committing.

### 7.2 Graph

```
intake → landscape → plan_round1 → sweep_round1 → propose_themes
   → ⟨GATE 1: select_theme⟩ → plan_round2 → sweep_round2 → propose_fields
   → ⟨GATE 2: select_field⟩ → Stage 1
```

Round 2 seeds from the chosen cluster's terms **and** expands via `related_to` / `cites` on that
cluster's exemplar papers. That expansion is what lets narrowing reach relevant work which never
contained the original keyword, rather than merely re-slicing round 1.

### 7.3 Gates

Every gate is a LangGraph `interrupt()` carrying a typed `GateRequest` and resuming on a
`GateResponse`. CLI and web render the same payload; neither is privileged.

- **Gate 1 — select theme.** Options are round-1 clusters as `ResearchField(level="theme")`.
- **Gate 2 — select field.** Options are round-2 clusters as `ResearchField(level="field")`.
- **Gate C — confirm scope** (`field` and `question` routes). Not a selection: shows corpus
  size, sub-clusters found inside the field, **the neighbouring clusters the expansion touched
  but excluded**, and the year distribution. Showing excluded neighbours is what compensates for
  skipping round 1 — the bypassed serendipity is surfaced rather than lost silently. On the
  `question` route it is the *only* gate before Stage 1 spends a probe, which is why it cannot be
  scoped to `field` alone without breaking the invariant below.

Every gate accepts free-text refinement instead of a selection, looping back to the preceding
`plan_*` node with that feedback, **capped at 2 refinements per gate**.

**Invariant: at least one human gate fires before Stage 1 begins on every route.** Stage 1 is
the expensive stage; no route reaches it without a human confirming the corpus.

A round-2 cluster that is still too coarse is handled by the gate's refinement loop, not by a
third automatic round — the user is the cheapest judge of "specific enough", and a third round
would double the cost of every run to serve a minority of cases.

---

## 8. Stage 1 — Idea Sub System

Input: chosen `ResearchField`, its frozen corpus, its sub-cluster structure — plus, on the
`question` entry route, the user's supplied question.
Output: `IdeaBundle`.

On the `question` route only, §8.1–8.4 are skipped: there is no gap to mine because the user
supplied the question. The question is formalised (§8.5) and verified (§8.6) directly.

### 8.1 Paper selection

Budgeted subset (default 60) chosen by in-cluster PageRank, recency, citation velocity, venue
tier, and full-text availability, **stratified across sub-clusters** so selection does not
collapse onto the famous old work. Reviews and surveys receive an explicit boost: they state
future directions outright.

### 8.2 Gap summaries — four evidence channels

| # | Channel | Source | `evidence_strength` |
|---|---|---|---|
| 1 | **Self-reported** | Limitations / Future Work sections (full text where available, else abstract hedges) | `stated` |
| 2 | **Citation context** | Sentences where later papers cite this one, with SciCite intents | `external` |
| 3 | **Structural absence** | Deterministic: conditions, scales, climate zones, metrics the metadata shows were not covered | `structural` |
| 4 | **LLM-inferred** | The model reasons about what is missing that the authors never stated: unexamined assumptions, absent baselines, untested conditions, unvalidated claims | `inferred` |

Channels 1–3 **must** carry a verbatim quote and locator, or the item is dropped. That rule is
what makes prevalence a count of evidence rather than of assertions.

Channel 4 has no quote by construction — a gap nobody wrote down cannot be quoted. It must
instead anchor on a quote of what the paper **did** say, plus the inference drawn from it.
Consequences:

- Channel-4 items do **not** contribute to `prevalence_count`. They contribute to a separate
  `inferred_support_count`, weighted lower in ranking.
- A gap supported **only** by channel 4 is flagged `inferred_only` and faces a stricter
  verification bar (§8.6) before reaching Gate 3.

Rationale: channel 4 is simultaneously the most likely to surface a genuinely novel gap and the
most likely to hallucinate. Separating the counters lets it be tuned without corrupting the one
deterministic ranking axis.

**Execution:** a single node running a bounded thread pool (concurrency ~8) against the `direct`
backend, writing incrementally to the store. Resumability comes from the store — a paper already
summarised is skipped — not from graph topology. Sixty cheap tasks do not warrant sixty
checkpointed nodes; the probes in §8.6 do, because each is expensive and independently failable.

### 8.3 Gap mining

~60 papers yield ~300 raw items. Embed the statements with a small CPU sentence model
(SPECTER2 covers papers, not arbitrary sentences), agglomerate at a cosine threshold into
candidate groups, then role `synthesise_gaps` writes one canonical statement and category per
group. `prevalence_count` is computed deterministically as the number of **distinct papers** with
quoted (channel 1–3) evidence in the group.

### 8.4 Ranking

| Axis | Method |
|---|---|
| **Prevalence** | Fully deterministic: distinct papers with quoted evidence, normalised by field size |
| **Impact** | Role `rank_gaps` on a fixed rubric with mandatory justification citing specific papers, fused with a deterministic signal (aggregate citation weight of the stating papers; whether the gap touches a domain metric — energy, PUE, exceedance hours) |
| **Novelty** | Mostly deterministic: recency of the stating papers (a gap voiced only in 2015 papers is probably closed) and sub-cluster growth rate, fused with `rank_gaps` judgment |

Weighted sum with recorded weights and **exposed per-axis subscores** — never a single opaque
number. Top-K gaps (default 8) proceed.

### 8.5 Broadening

Per gap, role `broaden_gap` produces a research question deliberately wider than the gap's literal statement,
plus a `broadening_note` recording exactly what was widened (scope / population / mechanism /
metric). A hypothesis narrow enough to be trivially unaddressed is also trivially uninteresting;
broadening is what makes the novelty check meaningful.

The ceiling is enforced deterministically before any probe is spent: `variables` non-empty,
`metrics` non-empty, `expected_effect` stated, and — per the domain lock — the RQ must map to a
registry model or explicitly name the model it would require (`model_gap_note`). An RQ failing
the checklist is rejected at zero probe cost.

### 8.6 Verification fan-out

Per surviving RQ, LangGraph `Send` spawns one containerised pi process with the
`search_literature` tool, capped at **3 tool calls / 15 papers / a wall-clock timeout**.
Returns a `VerificationVerdict`.

- `addressed` **requires** a cited paper plus a quote that directly answers the RQ. No quote →
  downgraded to `partial`, RQ survives.
- Ambiguity, timeout, or crash → `unknown`, RQ survives with a flag.
- `partial` → survives, annotated with what is already covered so the human can re-scope.
- `inferred_only` gaps (§8.2) face a stricter bar, stated concretely: the probe must spend its
  full tool-call budget and return at least 2 distinct queries, and the verdict must include an
  explicit negative finding ("no paper in N retrieved addresses X"). A probe that stops early,
  or returns `open` without that statement, downgrades the verdict to `unknown`. An `unknown`
  `inferred_only` RQ still reaches Gate 3, but ranked below every evidence-backed RQ and labelled
  as unverified.

The asymmetry is deliberate: silently dropping a good question costs far more than carrying a
redundant one to a human who can see the evidence and dismiss it in seconds.

Probe results never enter the frozen corpus; they attach to the verdict.

### 8.7 Gate 3 — research-question selection

Surviving RQs, ranked, each showing gap provenance, prevalence evidence, verification verdict
and what it found, the broadening note, candidate models, and risks. The human selects one or
more → `IdeaBundle` → Stage 2. This is the PRD's mandatory hypothesis-selection gate, now with
evidence behind it.

---

## 9. Storage and provenance

SQLite in `data/`, blobs on disk addressed by content hash.

| Table | Contents |
|---|---|
| `papers` | merged canonical record + `field_provenance` |
| `source_payloads` | raw per-source responses, `fetched_at`, `etag`, **`cache_partition`** |
| `edges` | `src`, `dst`, `type`, `weight` |
| `embeddings` | `work_id`, vector, model name |
| `snapshots` | `corpus_hash`, run, round, plan, `paper_ids[]`, `degraded_sources[]`, params |
| `graphs` | snapshot → clusters and labels |
| `gap_summaries`, `gaps`, `research_questions`, `verdicts` | per run |
| `pi_calls` | role, tokens, wall-clock, node, run — the cost ledger |

**Licence partitioning (D8).** Content obtained through institutional plug-ins is written to a
separate `cache_partition` that is git-ignored, TTL'd, and excluded from every export path.
Free-tier content is freely cacheable and exportable. `GapSummary.access_source` records which
partition a summary drew on, so a run that depended on institutional access is identifiable.

**Reproducibility.** A run is reproducible from `corpus_hash` + `SearchPlan` + `params`
(α, β, γ, resolution, seed). Re-running with the same inputs must produce the same clusters.

---

## 10. Failure, degradation, cost

**Failure handling.** Retry with exponential backoff and jitter, honouring `Retry-After`;
per-source circuit breaker. A source outage **degrades, never fails**: if S2 is down, γ goes to
zero, `degraded_sources[]` is recorded on the snapshot, and Leiden runs on citation + coupling
alone. A pi subprocess timeout, non-zero exit, or invalid JSON gets one retry, then a typed node
failure routed to `handle_stage_failure`, which offers resume, skip, or abort. Every node is
idempotent, so re-running one is always safe.

**Cost bounds**, declared per run and enforced: `max_papers_per_round`, `max_gap_summaries`,
`max_gaps`, `max_probe_tool_calls`, `max_refinements_per_gate`, plus a `RunBudget` token ceiling.
`pi/runner.py` accounts every call and raises `BudgetExceeded`, which the graph converts into a
gate ("budget spent — continue?") rather than a crash.

**Rough envelope.** Stage 0: ~4 LLM calls (2 rounds × `plan_direction` + `label_clusters`) and
~40 HTTP requests. Stage 1: ~60 `summarise_paper` calls + 1 `synthesise_gaps` + 1 `rank_gaps` +
1 `broaden_gap` + up to 8 `verify_gap` probe agents.

---

## 11. Testing

- **Contracts** — pydantic round-trip and `schema_version` migration.
- **Source adapters** — recorded HTTP cassettes; **no live network in CI**.
- **Determinism** — a fixed 200-paper fixture asserts exact origin-filter verdicts, exact edge
  set, and exact Leiden assignment at a fixed seed. *Same input → same clusters* is the core
  guarantee behind "largely deterministic".
- **Degradation** — the same fixture with S2 responses removed must still cluster, and must
  record `degraded_sources`.
- **LLM/pi steps** — `direct` backend against a stub provider returning canned JSON; assert the
  contract, never the prose. Plus one small human-graded golden set for cluster-label quality
  and gap-extraction quality.
- **Quote binding** — a summary item without a quote in channels 1–3 must be dropped; a
  channel-4 item must never increment `prevalence_count`.
- **Gates** — interrupt/resume round-trip through the checkpointer.
- **E2E smoke** — 50-paper corpus through all four entry routes with auto-resolved gates.

---

## 12. Out of scope

No spec compilation, no simulation, no analysis, no report generation, no closed-loop feedback
from results back into ideas. Stage 1 ends at `IdeaBundle`. Scopus and Web of Science adapters
are excluded (§5.1). No third automatic narrowing round (§7.3).

---

## 13. Open questions

1. The data-centre topic allowlist and domain lexicon (§6.2 step 3) need to be enumerated from
   OpenAlex's topic tree before implementation.
2. Default α/β/γ and Leiden resolution targets are stated as priors; they need tuning against a
   labelled fixture once one exists.
3. Whether Gate 3 permits selecting multiple RQs for parallel Stage 2 runs, or exactly one.
4. Elsevier institutional-token approval timeline is unknown; the free-tier path must ship first
   regardless.
