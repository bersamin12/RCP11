# Product Requirements Document

**Project:** AI Agent Workflow for Scientific Discovery in Data Center Digital Twins
**Programme:** Renaissance Capstone Project AY2026/27 — Serial No. RCP2026/11 (Cloud Application and Platform Group)
**Team size:** 4 students · **Duration:** ~1 year (start Aug–Oct 2026) · **MVP target:** 2–3 months from kickoff
**Document status:** Draft v1.0 — 2026-07-18

---

## 1. Overview

This project builds a **closed-loop AI research platform** ("Research Operating System") that automates the full research lifecycle for data center studies: from reading papers, to generating hypotheses, to running physics-based simulations, to producing technical reports — with iterative feedback between stages and a complete evidence trail.

A researcher provides a research topic and constraints; the system handles knowledge organization, idea generation, experiment execution, result analysis, and report drafting, pausing at defined human-approval gates.

**Domain focus:** data-center-related research — energy optimization, scheduling, thermal analysis, and digital twin evaluation — using fast physics-based simulators (OpenModelica), not CFD.

## 2. Problem Statement

Three gaps motivate the platform (from the project deck):

1. **Scattered knowledge** — papers, reports, and notes live across PDFs, web pages, and spreadsheets; no structured knowledge base exists.
2. **Execution gap** — research ideas stay as plain text, while real simulations require structured models, parameters, and solver settings. There is no automated path from idea to executable experiment.
3. **Fragmented results** — simulation outputs are produced, but computing metrics, creating charts, and writing reports remain repetitive manual work.

More broadly (from the kickoff meeting): existing AI research tools lack loops that **interact with real physics** and support **full-cycle** AI research.

## 3. Goals and Non-Goals

### Goals (from Objectives.txt)

- **G1.** Design and implement an AI agent workflow for data center research covering the end-to-end lifecycle from knowledge input to technical output.
- **G2.** Develop three core agent modules: (1) Knowledge & Idea Agent, (2) Experiment & Simulation Agent, (3) Analysis & Writing Agent.
- **G3.** Build a closed-loop workflow linking knowledge retrieval → experiment execution → result analysis → report generation, with iterative feedback.
- **G4.** Validate the workflow on representative data center research tasks; evaluate usability, efficiency, and output quality.
- **G5.** Deliver reusable software modules, documentation, and evaluation results for future research and collaboration.

### Non-Goals

- **Not** CFD or other slow high-fidelity simulation — fast physics-based models only.
- **Not** fully autonomous research with zero human oversight — human approval gates are a design requirement, not a limitation.
- **Not** a simple RAG chatbot — the research memory is a structured, multi-agent-built knowledge base, explicitly more than retrieval-augmented generation.
- **Not** limited to reproducing existing GitHub projects — original multi-agent design is expected (reproduction alone is acceptable but inferior).
- Detailed computing-hardware modeling can be abstracted unless a team member specifically pursues it.

## 4. Users and Use Cases

**Primary user:** a researcher (student, PhD student, or faculty) studying data center topics.

Three task archetypes the system must support (from the end-to-end workflow slide):

- **Task 1 — Reproduce:** reproduce results from existing papers.
- **Task 2 — Improve:** given candidate ideas A, B, C…, choose the best and improve it.
- **Task 3 — Explore:** generate new ideas from the current literature autonomously.

**Illustrative use case (from kickoff):** network science within data centers — collect papers, build a knowledge database, generate ideas via multi-agent reasoning, and verify them with simulation.

## 5. System Architecture

### 5.1 Four-Layer Architecture

| Layer | Contents |
|---|---|
| **1. Task Input** | Research topic, constraints, human instructions |
| **2. Research Intelligence** | Research Memory · Knowledge & Idea · Writing & Review |
| **3. Scientific Execution** | Experiment Planning · Execution/Simulation · Analysis |
| **4. Runtime & Storage** | LangChain/LangGraph orchestration · object storage · logging · traceability |

A control panel / orchestration layer coordinates the entire workflow.

### 5.2 Orchestration Backbone (LangChain + LangGraph)

- **LangChain** provides the model interface layer (swap LLM providers without code changes), tool abstraction (any Python function becomes an agent tool), and agent encapsulation.
- **LangGraph** provides shared **state management**, workflow orchestration with **checkpoints after every step** (resume from any point after interruption), failure recovery (fail → re-plan edges), and **human-in-the-loop pauses**.
- Core primitives: **Tool** (callable function, e.g. `search_papers`), **State** (shared object: topic, papers, results), **Node** (one processing step), **Edge** (transition rule).

**Reference graph nodes:** `research_memory_build` → `gap_mining` → `hypothesis_gen` → `spec_compile` → `run_modelica` → `analyze_results` → `draft_report`

**Reference tools:** `search_openalex`, `run_openmodelica`, `compute_metrics`

### 5.3 Standard Data Objects

All modules exchange typed objects (the contract between modules):

`ResearchTopic` · `PaperCard` · `Hypothesis` · `ExperimentSpec` · `ResultBundle` · `ClaimBundle`

Global workflow state holds: topic & constraints, paper_cards, hypotheses, selected_hypothesis, experiment_spec, result_bundle, claim_bundle, report_draft.

### 5.4 Human-in-the-Loop Gates

Two key mandatory gates, plus rollback:

1. **Hypothesis selection** — human picks/approves which hypothesis proceeds.
2. **Experiment spec approval** — human approves the compiled simulation spec before execution.
3. **Rollback decisions** — human decides on rollback when the failure handler triggers.

## 6. Functional Requirements by Module

### Module 1 — Research Memory (knowledge base construction)

Builds a structured knowledge base from papers and reports so downstream modules can answer *"what has been studied, what has not, and where conflicts exist"* without re-reading raw PDFs.

| ID | Requirement | Priority |
|---|---|---|
| M1.1 | **Query Planner** — expand a research topic into multiple search queries | P0 |
| M1.2 | **Source Connectors** — fetch metadata/papers from OpenAlex and Semantic Scholar | P0 |
| M1.3 | **Dedup & Normalize** — remove duplicates by DOI; clean and unify fields | P0 |
| M1.4 | **PaperCard Extractor** — extract problem, method (incl. mathematical models), metrics, and limitations per paper | P0 |
| M1.5 | **Theme Builder** — cluster papers by topic; build citation-based theme maps / topic trees | P1 |
| M1.6 | **Memory Store** — persist paper cards, topic trees, citation graphs, version snapshots | P0 |

### Module 2 — Knowledge & Idea Agent

Chains paper findings via long chains of thought to identify gaps and propose hypotheses, preserving physics fidelity in the reasoning.

| ID | Requirement | Priority |
|---|---|---|
| M2.1 | **Gap Miner** — find gaps in existing methods, scenarios, metrics, system scope | P0 |
| M2.2 | **Contradiction Detector** — spot conflicting conclusions / unexplained differences across papers | P1 |
| M2.3 | **Hypothesis Builder** — generate structured hypotheses with variables, metrics, and risks | P0 |
| M2.4 | **Priority Ranker** — rank hypotheses by novelty, feasibility, expected contribution | P1 |
| M2.5 | Idea verification & improvement loop (idea → verify feasibility → refine → select) | P1 |

### Module 3 — Experiment Planning Agent ("Scientific Compiler")

Converts research ideas into simulation-ready specifications, with validation before real execution.

| ID | Requirement | Priority |
|---|---|---|
| M3.1 | **Spec Compiler** — map a hypothesis to model name, parameters, outputs, metrics (`ExperimentSpec`) | P0 |
| M3.2 | **Constraint Checker** — validate units, types, value ranges, solver compatibility | P0 |
| M3.3 | **Plan Expander** — auto-generate baseline, ablation, and parameter-sweep plans | P1 |
| M3.4 | **Experiment Registry** — track all specs with version control and status | P1 |

### Module 4 — Execution / Simulation (OpenModelica + Buildings Library)

| ID | Requirement | Priority |
|---|---|---|
| M4.1 | **Model Registry** — manage Modelica models, versions, parameters, I/O definitions | P0 |
| M4.2 | **OMPython Runner** — use `OMCSessionZMQ` to load models, set parameters, run, read results | P0 |
| M4.3 | **Batch Executor** — expand one `ExperimentSpec` into multiple jobs (baseline / ablation / sweeps) | P1 |
| M4.4 | **Result Collector** — convert MAT/CSV/log outputs into a unified `ResultBundle` | P0 |
| M4.5 | **Failure Handler** — detect invalid parameters, missing dependencies, non-convergence; trigger rollback | P0 |
| M4.6 | **Co-sim Adapter** — reserved interface for future OMSimulator / FMI co-simulation | P2 |

**Initial model library (Buildings Library):** `ChillerCooled` (chilled-water plant scenarios) and `DXCooled` (direct-expansion cooling for data centers). Start with existing models, then gradually expand control strategies and parameter space.

### Module 5 — Analysis

| ID | Requirement | Priority |
|---|---|---|
| M5.1 | **Metric Engine** — peak temperature, average temperature, energy use, stability | P0 |
| M5.2 | **Comparator** — baseline vs. candidate side-by-side comparison | P0 |
| M5.3 | **Trend & Anomaly Analyzer** — pattern and outlier detection | P1 |
| M5.4 | **Evidence Builder** — output a `ClaimBundle` linking every claim to its supporting results | P0 |

Analysis must be tied to physical constraints with strong physical explanations — not purely AI-generated narrative.

### Module 6 — Writing & Review

| ID | Requirement | Priority |
|---|---|---|
| M6.1 | Generate method, experiment, and result sections from templates + collected artifacts | P0 |
| M6.2 | Auto-generate figure captions, numbering, and variable definitions | P1 |
| M6.3 | **Consistency check** — do conclusions match the evidence (`ClaimBundle`)? | P0 |
| M6.4 | Internal review loop — paper checker + paper reviewer agents, review comments, terminology check | P1 |

### Cross-cutting Requirements

| ID | Requirement | Priority |
|---|---|---|
| X.1 | Closed loop: analysis results and review feedback flow back to idea refinement / re-planning | P0 |
| X.2 | Checkpoint after every step; resumable after interruption (LangGraph checkpointing) | P0 |
| X.3 | Full traceability: every claim in the final report traceable to results, specs, and source papers | P0 |
| X.4 | Every module produces standalone useful intermediate artifacts (paper cards, hypotheses, specs, result bundles) — not just the final report | P0 |
| X.5 | LLM-provider-agnostic model layer (token budgets vary per student/school) | P1 |

## 7. Non-Functional Requirements

- **Simulation speed:** fast physics-based models; individual runs should complete in minutes, enabling iteration within the loop.
- **Cost awareness:** token spend must be controllable/configurable — compute-token funding comes from each student's school, with no central project budget.
- **Reusability:** modules are independently usable Python packages with documented interfaces (deliverable G5).
- **Reliability:** failure handling and rollback are first-class (Failure Handler + LangGraph recovery edges).
- **Observability:** logging of all agent steps, tool calls, and simulation runs (Layer 4).

## 8. Success Metrics (for G4 validation)

- **End-to-end completion:** the system runs topic → report on ≥1 representative data center task (MVP), later ≥3 tasks covering the Reproduce / Improve / Explore archetypes.
- **Output quality:** technical reports judged by supervisors for correctness of physical reasoning and evidence-claim consistency.
- **Efficiency:** wall-clock and human-effort reduction vs. a manual baseline for the same task.
- **Usability:** a researcher outside the team can run a new topic through the system using only the documentation.
- **Traceability:** 100% of report claims link back to a `ClaimBundle` entry with underlying results.

## 9. Milestones and Roadmap

MVP of the closed-loop system in **2–3 months**, then iterative deepening over the ~1-year project. (The 2–3 month estimate from the kickoff assumed five people; with four members the MVP scope should be held to the thin vertical slice below, and the timeline reviewed at the first checkpoint.)

| Phase | Scope |
|---|---|
| **Phase 1** | LangGraph backbone + Research Memory MVP |
| **Phase 2** | OpenModelica execution chain + initial model library (ChillerCooled, DXCooled) |
| **Phase 3** | Knowledge & Idea module |
| **Phase 4** | Experiment Planning module |
| **Phase 5** | Analysis + Writing → **full closed loop (MVP)** |
| **Phase 6** | Orchestration & traceability hardening |

**MVP definition:** a thin vertical slice through all six modules — one topic, a small paper set, one hypothesis (human-selected), one approved spec, one Modelica model, basic metrics, and a draft report with evidence links.

## 10. Team and Roles (official 4-role structure)

Roles map to distinct modules, requirement IDs, roadmap phases, and deliverables. Backgrounds span computer science, electrical engineering, and bioengineering.

### Role 1 — Knowledge & Idea Agent (CS / DSAI preferable)

*Knowledge ingestion, representation, semantic retrieval, and AI-assisted idea generation and refinement from research artifacts.*

- **Owns:** Module 1 (Research Memory) + Module 2 (Knowledge & Idea Agent)
- **Requirements:** M1.1–M1.6, M2.1–M2.5
- **Key objects produced:** `PaperCard`, topic trees, citation graphs, `Hypothesis`
- **Roadmap:** Phase 1 (Research Memory MVP, with Orchestration), Phase 3 (Knowledge & Idea module)
- **Deliverables:** knowledge base construction pipeline (OpenAlex/Semantic Scholar connectors, dedup, PaperCard extraction, theme builder, memory store); gap miner, contradiction detector, hypothesis builder, priority ranker; idea verification & improvement loop

### Role 2 — Experiment & Simulation Agent (EEE / ME / CE preferable)

*Experiment intelligence: test-case generation, experiment configuration, parameter exploration, and integration with simulation services.*

- **Owns:** Module 3 (Experiment Planning) + Module 4 (Execution / Simulation)
- **Requirements:** M3.1–M3.4, M4.1–M4.6
- **Key objects produced:** `ExperimentSpec`, `ResultBundle`
- **Roadmap:** Phase 2 (OpenModelica execution chain + initial model library), Phase 4 (Experiment Planning module)
- **Deliverables:** spec compiler + constraint checker ("scientific compiler"); baseline/ablation/sweep plan expander and experiment registry; OpenModelica integration via OMPython (`OMCSessionZMQ`); model registry seeded with Buildings Library `ChillerCooled` and `DXCooled`; batch executor, result collector, failure handler

### Role 3 — Analysis & Writing Agent (DSAI / ADM / SSS preferable)

*Result interpretation, visualization, feedback/comment loops, and structured technical report generation support.*

- **Owns:** Module 5 (Analysis) + Module 6 (Writing & Review)
- **Requirements:** M5.1–M5.4, M6.1–M6.4
- **Key objects produced:** `ClaimBundle`, report drafts, figures/visualizations
- **Roadmap:** Phase 5 (Analysis + Writing → full closed loop)
- **Deliverables:** metric engine (peak/average temp, energy, stability), baseline-vs-candidate comparator, trend & anomaly analyzer, evidence builder; report section generation with figure captions and consistency checks; internal review loop (checker/reviewer agents) whose feedback/comments feed the closed loop (X.1); leads evaluation of usability, efficiency, and output quality (G4, Section 8)

### Role 4 — Orchestration & Platform (CS preferable)

*AI agent workflow coordination: agent communication design, pipeline orchestration, execution scheduling, state management, and system integration across agents and platform services.*

- **Owns:** Layer 4 (Runtime & Storage) + all cross-cutting requirements
- **Requirements:** X.1–X.5
- **Key objects owned:** global workflow state, checkpoints, standard object schemas (Section 5.3 — the contracts between the other three roles)
- **Roadmap:** Phase 1 (LangGraph backbone), Phase 6 (orchestration & traceability hardening), plus continuous integration support across Phases 2–5
- **Deliverables:** LangGraph state graph (nodes/edges per Section 5.2), checkpointing and failure-recovery (fail → re-plan), human-in-the-loop gates (Section 5.4), object storage and logging, LLM-provider-agnostic model layer, end-to-end traceability (X.3), and integration of the three agent roles into the closed loop

**Team note:** the team is now four members (the fifth member, Umairah, has left), matching the four-role structure one-to-one. The five-role breakdown previously requested for RCP office approval is no longer needed. Role 1 (Knowledge & Idea) is the largest role — 11 requirements across two modules and two roadmap phases — so the other members should expect to share load there if needed, with the `PaperCard` → `Hypothesis` boundary as the natural split point.

**Time budget:** per RCP office, ~12 hours/week over two semesters (framings varied: 4 contact hours/week under the 8-AU Renaissance project); depth of engagement may vary per member.

## 11. Dependencies

- **LLM API access** — token funding secured individually via each student's school (action item, open).
- **OpenAlex & Semantic Scholar APIs** — paper metadata (free, rate-limited).
- **OpenModelica + Buildings Library** — simulation engine and data center cooling models; accessed via OMPython (`OMCSessionZMQ`).
- **Existing data center platform** — data lake, analytics, simulator, computing cluster (per the official project brief's context diagram).
- **PhD student Shi Yuan** — technical guidance; Liu Xiyuan's detailed project document.

## 12. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Limited Modelica expertise on the team | Start with existing Buildings Library models (ChillerCooled, DXCooled); abstract computing details; lean on Shi Yuan for guidance |
| Token/compute funding not secured | Provider-agnostic model layer; small/cheap models for bulk tasks; cache aggressively; secure school funding early |
| LLM reasoning breaks physics fidelity | Constraint Checker before execution; human spec-approval gate; analysis tied to physical constraints |
| Long-term memory & efficient chain-of-thought maintenance (acknowledged open research questions) | Scope MVP to short-horizon loops; treat as stretch research topics, not MVP blockers |
| 4-person coordination with limited weekly hours | Module boundaries = role boundaries (one module pair per member); typed data objects as contracts; integrate early via the thin vertical slice |
| MVP timeline (2–3 months) was estimated for 5 people, team is now 4 | Hold MVP to the thin vertical slice; defer P1/P2 items; review timeline at first checkpoint |
| Scope creep (6 modules × many sub-components) | Strict P0/P1/P2 priorities; MVP = vertical slice, not full-featured modules |

## 13. Deliverables

1. Working closed-loop platform (source code, all six modules + orchestration).
2. Reusable software modules with documented interfaces.
3. Documentation: setup guide, user guide, module API docs.
4. Evaluation results on representative data center research tasks (usability, efficiency, output quality).
5. Sample outputs: knowledge base snapshots, hypothesis sets, experiment specs, result bundles, and at least one full technical report produced by the system.

## 14. Open Questions

1. Which representative research tasks will be used for validation (beyond the network-science and cooling examples)?
2. Final per-student time allocation from the RCP office (Justin and Sun Sitong to confirm).
3. Token budget per student/school — determines model choices and loop depth.
4. Role assignments — to be settled after reviewing Liu Xiyuan's detailed document and notifying Liu.
5. Exact LLM provider(s) and whether local/open models are needed as fallback.
6. How much of the existing data center platform (data lake, cluster) is actually accessible to the team, and via what interfaces?
