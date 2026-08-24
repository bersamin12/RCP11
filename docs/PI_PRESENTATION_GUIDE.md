# RCP Platform PI Review — Presenter Guide

Companion to `RCP_Platform_PI_Review_Aug_2026.pptx`.

## Recommended format

- Audience: principal investigator, research leads, and technical collaborators.
- Main presentation: 30–35 minutes, followed by 15–20 minutes of discussion.
- Short version: slides 1–6, 8–10, 13, 15–20, 21–25, 27–33, 36, 38–41.
- Detailed version: all 41 slides.
- Central message: RCP is a research control plane that accelerates computational studies while keeping the model, approved protocol, evidence chain, and human judgment visible.

## Narrative arc

### 1–6 · Why the platform exists

Open with the research problem, not the software. Computational studies lose rigor when literature context, plans, environments, results, and claims drift apart. RCP addresses that fragmentation through typed artifacts and explicit hand-offs.

Suggested phrase: “The goal is not to automate scientific judgment. It is to make the tractable work faster and every important transition reviewable.”

### 7–14 · How constrained LLM assistance works

Explain Research Memory as a frozen literature context built from OpenAlex, Semantic Scholar, DOI deduplication, Crossref enrichment, deterministic ranking, PaperCards, and themes. DeepSeek V4 Flash is the current default LLM through an OpenRouter-compatible boundary; it is replaceable. Structured Pydantic outputs, validation retries, human gates, and the deterministic scientific compiler are the important controls.

Emphasize the division of labor:

- LLM: synthesis, gap proposals, hypothesis drafts, and explanatory prose.
- Deterministic code: identity resolution, ranking, schema validation, parameter bounds, experiment expansion, metrics, hashes, and quality gates.
- Human: research direction, plan approval, validity judgment, and interpretation.

### 15–20 · Why Modelica and what the models mean

Modelica is the executable theory layer. It makes equations and component connections inspectable, but it does not automatically make a model physically valid.

Use the two credibility tiers carefully:

- `DataCenterRoom` is conceptual and fast. Its validation checks establish internal consistency, repeatability, units, equilibrium behavior, and directional sensitivity—not facility calibration.
- The two Buildings 13.0.0 chiller configurations are library-validated. They reproduce pinned upstream behavior, but they are still not calibrated to a physical data center.

The pinned OpenModelica, Modelica Standard Library, Buildings commit, runtime image, model versions, and raw-file hashes are part of each run’s reproducibility record.

### 21–26 · How the benchmark was conducted

The benchmark is a preregistered 3 × 3 matched design:

- 400, 500, and 600 kW computer-room loads.
- 6, 8, and 10 °C chilled-water setpoints.
- Non-integrated baseline and integrated candidate at every point.
- 18 cases, nine matched pairs, 24 hours per case, and 1,440 intervals per case.

The approved analysis protocol defines eight primary metrics, their direction, units, a 27 °C thermal threshold, a 0–2 MW physical HVAC-power screen, a maximum screened fraction of 1%, and plausibility checks.

The power-screen slide is important. OpenModelica produced isolated nonphysical mover-power impulses. The platform preserves raw upstream energy as a diagnostic and computes the primary metric only after applying the preregistered bridge rule. The observed screened fraction is 0.068–0.512%, below the 1% maximum. Present this as evidence that the safeguards caught a real numerical issue—not as an inconvenient detail.

### 27–33 · What the benchmark found

The main result is deliberately nuanced:

- Integrated HVAC energy is higher in all nine matched pairs.
- The increase ranges from 2.9% to 18.4%, with a mean of 10.3%.
- PUE also rises in all nine pairs.
- At the 6 °C setpoint, peak room temperature is 0.243–0.869 °C lower with integration.
- At 8–10 °C, the peak-temperature effect is negligible or slightly adverse.
- Thermal exceedance above 27 °C is zero in every case.

The supported interpretation is an energy–thermal-margin trade-off at 6 °C. The study does not support the claim that integration minimizes energy in the evaluated domain.

The provenance and revision slides show how a reviewer can travel from a claim to comparison IDs, case specifications, verified raw results, the analysis protocol, and supporting papers. A protocol change creates a new analysis revision instead of replacing history.

### 34–38 · What users see, how they reach it, and how it is evaluated

The UI follows the research lifecycle rather than hiding it behind one chat window. The deck uses current light-mode captures of the run portfolio, run cockpit, research-profile flow, Knowledge Base, and bounded model simulator.

Slide 36 answers the question the PI will ask as soon as the screenshots appear:
how do I open this myself? The platform now runs as a supervised systemd service
bound to loopback and is published through a Tailscale Funnel TLS URL, with HTTP
Basic auth in front of the API, the interface, and the live run stream. Present the
two bottom cards together and do not soften them: the shared credential keeps
anonymous visitors out, but it identifies nobody, rate-limits nothing, caps no
spend, and the Funnel hostname is public in Certificate Transparency logs. That is
why exposure is temporary and why `reviewer_id` remains self-declared.

Keep the evaluation distinction explicit:

- Automated tests establish software behavior.
- Numerical regression establishes agreement with pinned references.
- Manual blind review evaluates traceability, missing-evidence visibility, preregistration, reproducibility, disclosure, and verification time.
- None of these alone is a facility-validation claim.

Current validation snapshot: 174 backend tests, 60 frontend tests, seven conceptual-model checks, a successful production build, a healthy environment doctor, and a quality-valid 18-case study.

### 39–41 · What should happen next

Prioritize deeper evidence before broader autonomy:

1. Replicate the benchmark and investigate the mover-power impulses.
2. Add uncertainty analysis and broader climate, load, and control scenarios.
3. Acquire facility data for calibration and held-out validation.
4. Run a prospective study with independent reviewers.

Close by asking for three decisions:

1. Should the next scientific objective optimize energy only, or formalize an energy/thermal-margin trade-off?
2. What facility data or collaborator can anchor calibration?
3. Which researchers should participate in the traceability and verification-time evaluation?

## Questions to anticipate

### Why use an LLM at all?

The LLM handles synthesis and framing where language and ambiguity are unavoidable. It does not compute the primary metrics, select arbitrary models, bypass bounds, approve its own plan, or overwrite results.

### Is DeepSeek required?

No. It is the current configured default. The client boundary is OpenAI-compatible and provider-agnostic; schemas and evidence rules are platform invariants.

### Does “library-validated” mean physically validated?

No. It means the wrappers agree with pinned upstream Buildings behavior. Physical validation requires calibration and comparison against measured facility data.

### Why screen HVAC-power samples?

The raw trajectories include isolated nonphysical mover-power impulses. The screen and repair rule were declared in the analysis protocol, affect less than 1% of samples in every case, and leave the raw diagnostic untouched. The appropriate next step is still to investigate their upstream numerical cause.

### Can I open the platform myself, and is it secure?

Yes to the first: a browser and the URL are enough, and the login is the browser's
own credential prompt rather than a page in the application. On the second, be
precise. Transport is TLS and every request is authenticated, but one shared
password is not identity, not rate limiting, and not a spending control. It is
appropriate for a short, supervised review window and is intended to be withdrawn
afterwards. `docs/DEPLOYMENT.md` records both the procedure and its limits.

### Can the result be generalized?

Not yet. The current result applies to the declared models, pinned versions, dry-cold weather profile, 24-hour horizon, three loads, and three chilled-water setpoints.

### What is the strongest current claim?

RCP is a tested prototype for supervised, reproducible computational studies. The milestone benchmark demonstrates that the platform can surface a scientifically interesting trade-off while preserving the plan, raw evidence, numerical caveat, analysis revision, and claim provenance.

## Regeneration

The editable deck is generated by `tools/create_pi_deck.py`. It reads the stored benchmark result and manifest, regenerates charts, and inserts current screenshots from `docs/presentation_assets/ui/`.

Authoring-only packages used for this delivered deck:

```bash
uv pip install --python .venv/bin/python python-pptx matplotlib
.venv/bin/python tools/create_pi_deck.py
```

These packages are not runtime dependencies of the RCP application.

The accompanying PDF is exported from the generated deck, not authored separately:

```bash
libreoffice --headless --convert-to pdf --outdir docs docs/RCP_Platform_PI_Review_Aug_2026.pptx
```

Test counts on the readiness slide and the date on the title and closing slides are
literals in the generator (`DECK_DATE`), not values read from the repository. Refresh
them deliberately when regenerating:

```bash
.venv/bin/python -m pytest -q          # backend count
cd webapp && npm test -- --run         # frontend count
```
