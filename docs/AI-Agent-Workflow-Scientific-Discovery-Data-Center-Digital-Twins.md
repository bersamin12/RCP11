# AI Agent Workflow for Scientific Discovery in Data Center Digital Twins

> **Project ID:** RCP.2026/11 · **Type:** Renaissance Capstone Project (NTU)
> **Tagline:** *From research question to auditable simulation evidence.*

A closed-loop AI platform that automates the full research cycle — from reading papers to generating hypotheses, running simulations, and producing technical reports.

```
Knowledge Input → Idea Generation → Experiment Plan → Simulation → Analysis → Report
                       ↺                    Feedback Loop                    ↺
```

---

## 1. Project Identity

| Field | Value |
|---|---|
| Project ID | RCP2026/11 |
| Project Title | AI Agent Workflow for Scientific Discovery in Data Center Digital Twins |
| Faculty Supervisor | Prof Wen Yonggang – CCDS (`YGWEN@ntu.edu.sg`) |
| Student 1 | Sarah Wong Ee Min (BIE) |
| Student 2 | Kuang Yu Heng (CS) |
| Student 3 | Sun Sitong (CS) |
| Student 4 | Bersamin Justin Timothy Carmona (EEE) |
| Co-Examiners | Prof Lalit Goel, Assoc Prof Tan Meng How |

---

## 2. Overview & Core Proposition

**What it is:** A practical research cockpit combining literature memory, constrained LLM reasoning, reproducible Modelica experiments, and claim-level provenance.

**Technology pillars:** `Modelica × LLM-guided research × Auditable evidence`

The platform is a **research control plane — not an autonomous scientist**. It accelerates the tractable parts of computational research while making human choices and model limitations visible.

### What it automates
- Literature retrieval and screening
- Structured gap and hypothesis drafts
- Model selection and bounded parameterization
- Batch execution, analysis, and reporting

### What remains human
- Choice of research direction
- Approval of the scientific plan
- Interpretation of trade-offs
- Judgment about validity and contribution

### What is auditable
- Frozen literature snapshot
- Approved plan and protocol hashes
- Pinned runtime and raw-file fingerprints
- Revisioned analysis and claim links

> **Core proposition:** move faster without collapsing generation, execution, evidence, and scientific judgment into one opaque step.

---

## 3. Research Motivation

Computational research is fragmented at exactly the points that matter:

1. **Scattered Knowledge** — Papers, reports, and notes are spread across PDFs, web pages, and spreadsheets, making it hard to form a structured knowledge base.
2. **Execution Gap** — Research ideas stay as plain text, while real simulations require structured models, parameters, and solver settings.
3. **Fragmented Results** — Simulation outputs are generated, but computing metrics, creating charts, and writing reports still require repetitive manual work.

Four forms of "drift" (loss of intent/evidence across the loop):

1. **Literature drift** — Searches change; rationales disappear; missing abstracts are overinterpreted.
2. **Plan drift** — Parameters/metrics change between the research question, execution, and analysis.
3. **Environment drift** — Model libraries, solvers, and runtime images silently alter behavior.
4. **Evidence drift** — Final prose becomes detached from cases, files, comparisons, and caveats.

> **Goal:** Build a **"Research Operating System"** — the researcher provides a question; the system handles knowledge organization, experiment execution, and result documentation, keeping a complete evidence trail.
>
> **Design response:** treat every transition as a typed, inspectable artifact — not just a prompt or log line.

---

## 4. Scope

**Current domain:** Data-center cooling (the control pattern is designed to generalize).

### IN SCOPE
- Turn a research profile into ranked, traceable hypothesis candidates
- Compile approved ideas into registered Modelica experiments
- Execute matched studies inside a pinned OpenModelica environment
- Verify raw results, analyze under a preregistered protocol, and draft linked claims

### NOT CLAIMED
- Autonomous novelty determination or publication readiness
- Physical validation without calibration data
- Universal correctness of an LLM-generated hypothesis
- Replacement for a PI, domain expert, or independent reviewer

> **Success = a shorter path to a reviewable study — not an automated scientific verdict.**

---

## 5. Architecture

**Overall (four layers · six modules · one orchestration layer):**

| Layer | Contents |
|---|---|
| **Layer 1: Task Input** | Research topic, constraints, human instructions |
| **Layer 2: Research Intelligence** | Research Memory · Knowledge & Idea · Writing & Review |
| **Layer 3: Scientific Execution** | Experiment Planning · Execution/Simulation · Analysis |
| **Layer 4: Runtime & Storage** | LangChain/LangGraph · Object Storage · Logging · Traceability |

**Standard Objects:** `ResearchTopic · PaperCard · Hypothesis · ExperimentSpec · ResultBundle · ClaimBundle`

**Four reliability layers (the core boundary between probabilistic reasoning and deterministic evidence):**

| # | Layer | Contents |
|---|---|---|
| 01 | **Research Interface** | Profiles · gates · run cockpit · evidence review |
| 02 | **Agent Workflow** | Typed state · constrained LLM calls · revision loops |
| 03 | **Scientific Runtime** | Registry · compiler · OpenModelica · batch analysis |
| 04 | **Evidence Store** | Snapshots · raw series · hashes · revisions · exports |

> **Boundary rule:**
> LLMs may **propose**. Schemas must **validate**. Compilers **bound**. Runtimes **measure**. Hashes **prove**.
> *A fluent answer is never treated as a simulation result.*

### End-to-End Workflow (closed loop)

Eleven workflow nodes with explicit hand-offs and **two human gates**:

```
01 Research memory → 02 Gap mining → 03 Hypothesis generation → [H1: Select hypothesis]
→ 05 Compile specification → [H2: Approve plan] → 07 Run Modelica → 08 Analyze results
→ 09 Review evidence → 10 Draft report
```

- Failure handling is explicit; plan-revision loops are bounded to **three attempts**.
- LangGraph saves a checkpoint after every step → resumable from any point after interruption.
- Two human gates: **hypothesis selection** and **experiment spec approval**.

### Global State (LangGraph)
`topic & constraints · paper_cards · hypotheses · selected_hypothesis · experiment_spec · result_bundle · claim_bundle · report_draft`

### Nodes / Tools
- **Nodes:** `research_memory_build · gap_mining · hypothesis_gen · spec_compile · run_modelica · analyze_results · draft_report`
- **Tools:** `search_openalex · run_openmodelica · compute_metrics`
- **Human approval:** hypothesis selection, experiment spec approval, rollback decisions

---

## 6. Method

### 6.1 Constrained intelligence, not free-form automation
The LLM is used where ambiguity is real (synthesis, framing, drafting); deterministic components take over where correctness can be checked.

**LLM-suitable tasks:** synthesize literature themes, propose research gaps, draft candidate hypotheses, explain results in plain language.

**Deterministic tasks:** resolve/rank papers, validate schemas & bounds, compile experiment cases, compute metrics/hashes/quality gates.

*Human judgment spans both columns: selecting questions, approving plans, interpreting evidence.*

### 6.2 Typed artifacts (hand-offs between agents)

| # | Artifact | Fields |
|---|---|---|
| 01 | **ThesisProfile** | domain · interests · objectives · constraints |
| 02 | **PaperCard** | identity · methods · findings · limitations |
| 03 | **Hypothesis** | question · mechanism · contribution · risks |
| 04 | **ExperimentPlan** | cases · pairs · metrics · protocol |
| 05 | **ResultBundle** | files · fingerprints · metrics · warnings |
| 06 | **Claim** | statement · comparison IDs · paper IDs |

> Typed state makes a run resumable, testable, and reviewable without replaying the LLM conversation.

### 6.3 LLM layer — replaceable, constrained, measured
- **Default model:** DeepSeek V4 Flash via an OpenRouter-compatible endpoint
- **Temperature:** 0.2 (bias toward repeatable structured outputs)
- **Schema:** JSON via Pydantic; reject malformed/incomplete responses
- **Retry:** validation repair = a bounded second chance, not silent coercion
- **Usage:** token capture, per-call accounting retained in run state
- **Provider-agnostic:** OpenAI-compatible client boundary → replace model without changing scientific artifacts
- **Reasoning separated:** generated hypotheses/prose never overwrite observed Modelica outputs or hashes
- **Failure visible:** provider warnings, schema failures, missing evidence propagate to the UI

> Model choice is a **configuration decision**; evidentiary rules are **platform invariants**.

### 6.4 The scientific compiler (idea → executable cases)
```
Approved hypothesis (mechanism + boundary) → Registry lookup (known model + ranges)
→ Parameter binding (clamp / drop / warn) → Plan validation (cases + matched pairs)
→ Execution spec (sealed hash)
```
- **Bounded inputs:** ranges, units, defaults, operating envelopes live with each model
- **Reproducible expansion:** a 3×3 design becomes 18 explicit cases and 9 matched pairs
- **Fail closed:** unknown models, invalid structures, or unapproved plans do not reach the runtime

> Compilation is the **trust boundary** between generative intent and physical simulation.

### 6.5 Two human gates

| Gate | Review |
|---|---|
| **H1 · Select hypothesis** | ranked candidates, research question, novelty claim, feasibility, supporting papers, risks, model fit, provider warnings, ranking rationale |
| **H2 · Approve experiment plan** | model, parameters, operating ranges, cases, matched comparisons, outputs, metrics, protocol, validation issues, disclosures — before any compute |

Rejecting a plan creates a visible revision request; the loop is capped at **three revisions**.

### 6.6 Research Memory (frozen literature context)

```
Query planner (4 focused queries) → Dual retrieval (OpenAlex + Semantic Scholar)
→ Resolve identity (DOI dedup) → Screen (relevance + disclosure) → Enrich (Crossref metadata)
→ Rank (deterministic weights) → Extract (PaperCards) → Map (themes + gaps) → Freeze (snapshot hash)
```

**Credibility tiers (disclosed, never silently blended):**
- ✓ **Verified** — cross-source identity and publication metadata align
- ? **Likely / uncertain** — usable with an explicit confidence label
- P **Preprint** — not discarded, but never presented as peer-reviewed

- Missing abstracts are marked *insufficient*; the platform does not invent methods/limitations to complete a card.
- Ranking can prioritize attention; it cannot determine truth.

---

## 7. Models (Modelica)

**Modelica is the executable theory layer** — equation-based models make assumptions, state, and conservation relationships explicit, while the registry prevents "any model, any parameter" execution.

### Why Modelica
- **Declarative physics** — components describe equations/connections rather than a fixed procedural solver sequence (valuable for multi-domain thermal/fluid systems)
- **Composable systems** — rooms, heat exchangers, pumps, chillers, controllers, weather, sensors assemble while retaining physical interfaces
- **Reproducible execution** — OpenModelica compiles each sealed spec inside a pinned image; outputs become fingerprintable, reanalyzable files

> Modelica increases *transparency* of the model — it does not by itself *validate* the model against reality.

### Model Registry (`src/rcp/models_library/registry.json`)

| Model | Tier | Notes |
|---|---|---|
| **DataCenterRoom** | Conceptual · v1.0.0 | Single-zone thermal balance, proportional cooling, constant COP. Fast enough for interactive hypothesis exploration. |
| **Non-integrated plant** | Library-validated · Buildings 13.0.0 | Pinned wrapper around the non-integrated primary–secondary waterside-economizer example. **Baseline** in the milestone study. |
| **Integrated plant** | Library-validated · Buildings 13.0.0 | Pinned wrapper around the integrated primary–secondary waterside-economizer example. **Candidate** configuration. |

### DataCenterRoom (transparent conceptual model)
```
Room energy balance:   C · dT/dt = Q_IT + UA(T_amb − T) − Q_cool
Cooling:               Q_cool = clamp[k_p(T − T_set), 0, Q_max]
Power:                 P_cool = Q_cool / COP
```
- 8 bounded parameters
- Checks: 0 W energy-balance residual; 26.818 °C analytic equilibrium; 100 °C saturation branch equilibrium; bitwise repeatability; unit consistency; directional load/capacity sensitivity
- **Omitted:** spatial hot spots, humidity, airflow network, equipment transients, sensor uncertainty, calibration data

### Milestone Benchmark (two Buildings configurations)
Both configurations share the same room load (400–600 kW), weather profile, outputs, horizon, and chilled-water setpoint.

- **Non-integrated:** primary–secondary plant with waterside economizer (baseline); separate non-integrated economizer arrangement
- **Integrated:** primary–secondary plant with *integrated* economizer (candidate); economizer integrated into the chilled-water path

> Validation tier = agreement with pinned upstream library behavior, **not** calibration against a physical data center.

### Reproducibility Manifest (`data/runs/benchmark-bc0522c9/manifest.json`)
| Component | Version |
|---|---|
| OpenModelica | 1.26.3 |
| Modelica Standard Library | 4.1.0 |
| Buildings | 13.0.0 |
| Runtime image | `rcp-openmodelica-buildings` |

- Manifest records repository revision and dirty state (uncommitted code is part of the environment)
- Artifacts exported as ZIP with SHA-256 fingerprints and byte counts

---

## 8. Study — 18-case Modelica Benchmark

**Question:** Does integrating a primary–secondary waterside economizer improve energy or thermal performance across load and chilled-water setpoint?

- **18 cases · 9 matched pairs · 24 h each · 8 primary metrics**

### Design (3 × 3 matched comparison)

| | 6 °C CHW | 8 °C CHW | 10 °C CHW |
|---|---|---|---|
| **400 kW** | N vs I | N vs I | N vs I |
| **500 kW** | N vs I | N vs I | N vs I |
| **600 kW** | N vs I | N vs I | N vs I |

- N = non-integrated baseline · I = integrated candidate
- 18 simulation cases · 9 matched pairs · 1,440 intervals per case

### Analysis Protocol (`chiller-benchmark-analysis-v2`, hash `653a8df166…a997e6`)

| Metric | Direction | Definition | Unit |
|---|---|---|---|
| E_HVAC | lower | HVAC energy | kWh |
| PUE | lower | Power usage effectiveness | — |
| T_peak | lower | Peak room temperature | °C |
| Exceed. | lower | Degree-hours above 27 °C | °C·h |
| Free | context | Free-cooling duration | h |
| Partial | context | Partial-mechanical duration | h |
| Full | context | Full-mechanical duration | h |
| Switches | lower | Cooling-mode transitions | count |

### Numerical Impulse / Safeguards
- OpenModelica trajectories contain isolated nonphysical mover-power events.
- **Physical screen:** `0 ≤ P_HVAC ≤ 2 MW`
- **Repair rule:** linear bridge internally; nearest valid value at a boundary
- **Observed:** 0.068–0.512% screened; raw upstream energy retained as a diagnostic (never overwritten)

### Quality Gate (`experiment_results.json quality_report`)
- 18/18 cases successful · 9/9 matched pairs · 72/72 comparisons · **8+1 passed + warning**
- ✓ Primary metrics complete and finite
- ✓ Raw-series SHA-256 integrity verified
- ✓ PUE inside 1.0–3.0
- ✓ Cooling-mode time balances to 24 h
- ✓ IT energy monotonic with load
- ⚠ Power screening stays below 1% maximum

> Quality-valid = the declared analysis is internally defensible — not that the physical model is calibrated.

---

## 9. Results

**Headline: the integrated configuration is NOT an energy winner.**

- **+10.3%** mean HVAC energy
- **0 / 9** energy wins
- **cooler at 6 °C**
- **0** thermal exceedance

### Key findings
1. **Energy:** Integrated HVAC energy increases in every matched pair (+2.9% to +18.4%; mean +10.3%).
2. **Thermal:** Benefit appears only at the lowest setpoint (6 °C): integration lowers peak room temp by 0.243–0.869 °C; at 8–10 °C effect is negligible or slightly adverse (worst +0.105 °C).
3. **Operating mode:** at 500 kW & 6 °C, full-mechanical hours disappear (baseline 17.1 h free + 6.9 h full → integrated 7.2 h free + 16.8 h partial; both 4 mode switches).

### Conclusion (conditional, not "integrated is better")
- **Supported:** integration can reduce peak temperature at 6 °C, with higher HVAC energy.
- **Not supported:** integration minimizes energy across the evaluated domain.
- **Next question:** what control objective values thermal margin enough to justify the cost?

### Evidence Chain (sealed provenance)
```
Approved plan (cc273daa59…59de99) → Analysis protocol (653a8df166…a997e6)
→ Execution specs (18 case hashes) → Raw results (7a892f4093…dba500)
→ Analysis revision (4b5e8132fa…27336d) → Claim (comparison + case + paper IDs)
```
- **Tamper evidence:** raw files checked against recorded SHA-256 fingerprints before analysis
- **Append-only analysis:** protocol change → new revision; previous result retained
- **Claim links:** draft statements cite comparison, case, and supporting-paper identifiers

> *The report is a view over evidence — not the evidence itself.*

### Versioned reanalysis
- **REVISION 01** (`f906…ec70f`) — retained as historical analysis (protocol change)
- **CURRENT** (`4b5e8132fa…27336d`) — metrics recomputed from stored raw series

---

## 10. Product

### Interface (reviewable research state)
- Light/dark themes, keyboard-visible controls, responsive layouts, URL-addressable views, explicit lifecycle actions
- **Run Portfolio / Run Cockpit:** status at a glance (active, attention, completed, failed); lifecycle navigation (stages, gates, tabs, claims, artifacts); safe operations (archive/retry update the same view after backend succeeds)
- **Researcher flow:** 01 Frame (research profile + constraints) → 02 Ground (credibility-aware PaperCards) → 03 Explore (bounded model quick simulation)

### Deployment & Access (`docs/DEPLOYMENT.md`, `deploy/rcp.service`, `src/rcp/api/auth.py`)
- Reviewer reaches platform via browser (nothing to install) → Tailscale Funnel (public TLS :443) → Basic-auth gate (ASGI middleware) → supervised `rcp serve` (127.0.0.1, systemd) → run manager (one worker, Docker)
- **Fail closed:** `rcp serve` will not start without a password, rejects passwords < 16 chars, will not disable auth on a non-loopback host
- **Pass-through streaming:** run events keep flowing (15 s keepalive); PDF range requests still return 206
- **Supervised single worker:** systemd unit, 120 s stop timeout for the 1200 s simulation call; live run state is in-process → worker count structurally refused
- **What it protects:** anonymous access to API, interface, event stream, and schema (interactive docs withdrawn when auth is on)
- **What it is not:** one shared credential identifies nobody, rate-limits nothing, caps no spend; Funnel hostname published to Certificate Transparency logs

### Evaluation (`docs/EVALUATION.md`) — software correctness vs scientific validity

| Tier | Contents |
|---|---|
| **A. Automated verification** | backend tests; frontend interaction tests; production build; environment doctor; model validation checks; raw integrity + study quality |
| **N. Numerical regression** | pinned upstream trajectories; normalized RMSE ≤ 0.5%; benchmark repeatability; metric completeness; physical plausibility screens |
| **H. Manual blind review** | traceability; missing-evidence visibility; preregistration; reproducibility; calibration disclosure; verification time |

- Manual review uses ≥ 2 reviewers, never collapses into a single "scientific validity score."

### Current State (`docs/EVALUATION.md`)
- **174** backend tests passed · **60** frontend tests passed · **7/7** conceptual model checks valid · **18-case** study quality valid
- **Strong today:** auditable workflow, bounded registry, pinned runtime, evidence hashes, revisioned analysis, coherent UI, supervised authenticated deployment
- **Needs research work:** facility calibration, uncertainty quantification, broader scenarios, independent replication
- **Needs product work:** per-reviewer identity, rate limiting & spend caps, multi-user provenance, long-running job infrastructure, observability

> **Readiness claim:** strong prototype for supervised, reproducible computational studies.

---

## 11. Risks, Roadmap & Next Steps

### Top Risks & Mitigations

| Risk | Mitigation |
|---|---|
| **Calibration gap** (library regression ≠ facility validation) | Acquire measured plant data; calibrate and hold out validation periods |
| **Scenario narrowness** (one dry-cold weather profile, 3×3 matrix) | Add climates, seasons, load profiles, faults, control variants |
| **LLM dependence** (hypothesis quality varies) | Benchmark prompts/models; capture uncertainty; retain human selection |
| **Numerical events** (isolated mover-power impulses) | Investigate upstream dynamics; compare alternate solvers/tolerances |

### Development Roadmap

| Phase | Deliverable |
|---|---|
| **Phase 1** | LangGraph backbone + Research Memory MVP |
| **Phase 2** | OpenModelica execution chain + initial model library |
| **Phase 3** | Knowledge & Idea module |
| **Phase 4** | Experiment Planning module |
| **Phase 5** | Analysis + Writing → full closed loop |
| **Phase 6** | Orchestration & traceability hardening |

**Staged plan (deepen evidence before broadening automation):**
- **0–3 months — VALIDATE:** replicate benchmark · investigate power impulses · add uncertainty bands · define calibration dataset
- **3–6 months — GENERALIZE:** new weather profiles · dynamic load traces · control variants · cross-solver comparison
- **6–12 months — TRANSLATE:** facility calibration · prospective case study · independent reviewer study · operational deployment plan

> **Decision rule:** do not add a new autonomous step until its inputs, outputs, failure modes, and review point are explicit.

### Open Decisions for the PI
1. **Scientific target** — optimize energy only, or formalize a weighted energy/thermal-margin objective?
2. **Validation access** — which facility data, collaborator, or measured benchmark can anchor calibration?
3. **Evaluation design** — which users/reviewers should test traceability and verification-time gains?

> **Take-away:** RCP can make simulation research faster and more reviewable — provided the model, protocol, and human judgment remain first-class evidence.

---

## 12. Modules Reference (from project pitch)

### Module 1 — Research Memory
Query Planner (expand topic → multiple queries) → Source Connectors (OpenAlex + Semantic Scholar) → Dedup & Normalize (DOI) → PaperCard Extractor (problem/method/metrics/limitations) → Theme Builder (clusters + citation maps) → Memory Store (cards, topic trees, citation graphs, version snapshots).
> Outcome: downstream modules answer "what has been studied, what has not, and where conflicts exist" without re-reading raw PDFs.

### Module 2 — Knowledge & Idea Agent
- **Gap Miner** — finds gaps in methods, scenarios, metrics, system scope
- **Contradiction Detector** — spots conflicting conclusions across papers
- **Hypothesis Builder** — structured hypotheses with variables, metrics, risks
- **Priority Ranker** — ranks by novelty, feasibility, expected contribution

### Module 3 — Experiment Planning Agent
- **Spec Compiler** — hypothesis → model name, parameters, outputs, metrics
- **Constraint Checker** — validates units, types, value ranges, solver compatibility
- **Plan Expander** — auto-generates baseline, ablation, parameter-sweep plans
- **Experiment Registry** — version control + status of all experiment specs

> A "Scientific Compiler": converts research ideas into simulation-ready specifications with validation checks before real execution.

### Module 4 — Execution / Simulation (OpenModelica + Buildings Library)
1. **Model Registry** — models, versions, parameters, I/O definitions
2. **OMPython Runner** — `OMCSessionZMQ` to load models, set params, run, read results
3. **Batch Executor** — one ExperimentSpec → baseline, ablation, sweeps
4. **Result Collector** — MAT/CSV/log → unified `ResultBundle`
5. **Failure Handler** — invalid params, missing deps, non-convergence → rollback
6. **Co-sim Adapter** — reserved for future OMSimulator / FMI co-simulation

**Data Center Models (Buildings Library):**
- `ChillerCooled` — chilled-water plant scenarios for air-based equipment cooling
- `DXCooled` — direct-expansion cooling scenarios for data center environments

### Module 5 — Analysis
- **Metric Engine** — peak temp, average temp, energy use, stability
- **Comparator** — baseline vs. candidate side-by-side
- **Trend & Anomaly Analyzer** — pattern and outlier detection
- **Evidence Builder** → outputs a `ClaimBundle` object

### Module 6 — Writing & Review
- Generates method, experiment, and result sections
- Auto-generates figure captions, numbering, variable definitions
- Consistency check: do conclusions match the evidence?
- Internal review comments and terminology check

---

*Sources: RCP_Platform_PI_Review_Aug_2026.pdf (17 Aug 2026), Multi Agent Sys Sci Disco.pdf (project pitch), 1b. List of RCP Teams 2026.pdf.*
