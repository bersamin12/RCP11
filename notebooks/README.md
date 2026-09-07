# Paper test notebooks

One Jupyter notebook per paper in [`../papers/`](../papers) (ten papers). Each notebook exercises the paper's
building blocks **one section at a time** (so a single mechanism can be run and inspected on its
own) and ends with a small end-to-end run. All LLM calls are real and go through the project's
OpenRouter configuration in the repo-root `.env` (`OPENROUTER_API_KEY`, `RCP_MODEL`, `RCP_BASE_URL`).

| Notebook | Paper | How the code is sourced |
|---|---|---|
| `01_autoscientists.ipynb` | AutoScientists: Self-Organizing Agent Teams for Long-Running Scientific Experimentation (arXiv 2605.28655) | **Standalone re-implementation** in `autoscientists/`. The authors' repo is a Claude Code prompt bundle (markdown roles + a bootstrap script) with no LLM abstraction, no tests, no toy task and no license; its algorithms are pseudocode inside markdown, used here as the spec. |
| `02_ideagent.ipynb` | IDEAgent: Agentic Quality-Diversity Search for Research Idea Generation (arXiv 2607.22375) | **Drives the authors' repo** (`declare-lab/IDEAgent` @ `1213761`), vendored into `vendor/IDEAgent` by the setup cell and patched with `patches/ideagent_openrouter.patch` (fixes a crashing kwarg in the runner, adds `base_url` so every role can use OpenRouter, controls hidden reasoning). Yield (Alg. 2) and topic selection (Alg. 1) are not in the repo and live in `ideagent_extras.py`. |
| `03_ktpo.ipynb` | KTPO: K-Step Test-Time Policy Optimization for Long-Horizon Discovery (COLM 2026) | **Standalone re-implementation** in `ktpo/` (the authors' GitHub repo was an empty placeholder when this was written). The Circle Packing seed program and validity checker are OpenEvolve's example (Apache-2.0, `vendor/openevolve_circle_packing/`). Includes a tiny real GRPO run with TRL on the local GPU. |
| `04_aiscientist.ipynb` | The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery (Lu et al., 2024, arXiv 2408.06292) | **Drives the authors' repo** (`SakanaAI/AI-Scientist` @ `1de1dbc`) with an OpenRouter patch; the Aider experiment loop is replaced by live pi sessions; LaTeX compilation skipped (no pdflatex). |
| `05_ideation_study.ipynb` | Can LLMs Generate Novel Research Ideas? A Large-Scale Human Study with 100+ NLP Researchers (Si, Yang, Hashimoto, ICLR 2025, arXiv 2409.04109) | **Drives the authors' repo** (`NoviScl/AI-Researcher` @ `e5dd05a`) with an OpenRouter patch: retrieval, grounded generation, embedding dedup, Swiss-tournament ranking, filtering. |
| `06_funsearch.ipynb` | Mathematical discoveries from program search with large language models (FunSearch, Romera-Paredes et al., Nature 2024) | **Drives the authors' `implementation/` package** (`google-deepmind/funsearch` @ `cc53f27`), adding the missing LLM sampler and sandbox in `funsearch/`. |
| `07_coscientist.ipynb` | Towards an AI co-scientist (Gottweis et al., Google, 2025, arXiv 2502.18864) | **Standalone re-implementation** in `coscientist/` (no public code): generate–debate–evolve, Elo tournament, reflection, proximity, meta-review; research goal from this platform's data-center domain. |
| `08_adas.ipynb` | Automated Design of Agentic Systems (Hu, Lu, Clune, ICLR 2025, arXiv 2408.08435) | **Drives the authors' repo** (`ShengranHu/ADAS` @ `2702bee`) with an OpenRouter patch: Meta Agent Search on a tiny task set. |
| `09_alphaevolve.ipynb` | AlphaEvolve: A coding agent for scientific and algorithmic discovery (Novikov et al., DeepMind, 2025, arXiv 2506.13131) | No official code; **drives OpenEvolve** (`algorithmicsuperintelligence/openevolve` @ `411fb59`), the open re-implementation, mapping each AlphaEvolve component to its class. |
| `10_aide.ipynb` | AIDE: AI-Driven Exploration in the Space of Code (Jiang et al., Weco AI, 2025, arXiv 2502.13138) | **Drives the authors' repo** (`WecoAI/aideml` @ `60b3978`) through its OpenRouter backend: solution tree, search policy, coding operators, summarisation. |

## Setup

```bash
# from the repo root, inside the project's virtualenv
uv pip install -r notebooks/requirements.txt          # jupyter, sklearn, torch (CUDA), transformers, trl, peft, IDEAgent deps
python -m ipykernel install --user --name rcp --display-name "Python (rcp)"
cp .env.example .env && $EDITOR .env                   # OPENROUTER_API_KEY, optional RCP_MODEL
npm install -g --ignore-scripts @earendil-works/pi-coding-agent   # `pi` CLI for the live coding-agent sessions (Node 22+)
cd notebooks && jupyter lab                            # open a notebook, kernel "Python (rcp)"
```

Every notebook contains one to three **live `pi` coding-agent sessions** (`common.run_pi`): an
ephemeral `pi -p` run on the same OpenRouter model with a tool allowlist, a working directory under
`notebooks/outputs/<slug>/`, a hard timeout, and a parsed transcript rendered in the notebook. They
appear wherever the paper itself uses a coding agent or code-editing loop (AutoScientists heartbeats,
the AI Scientist's Aider experiment loop, KTPO/FunSearch/AlphaEvolve program refinement, ADAS meta
agent, AIDE improve step) or where an agentic rendering of a role is instructive (IDEAgent critic
repair, co-scientist deep verification, the ideation study's pairwise judge).

Run the notebooks from the `notebooks/` directory (they `sys.path`-insert `.`). Headless:

```bash
cd notebooks
NB_QUICK=1 jupyter nbconvert --to notebook --execute --inplace --ExecutePreprocessor.timeout=3600 01_autoscientists.ipynb
```

Environment switches (all optional):

| Variable | Effect |
|---|---|
| `NB_QUICK=1` | smaller budgets everywhere (fewer cycles / seeds / iterations / GRPO steps) |
| `NB_REASONING` | `off` (default), `low`, `medium`, `high` — hidden reasoning effort for reasoning models via OpenRouter; reasoning tokens count against the completion budget, so `off` is safest for code generation |
| `NB_ABLATIONS` | ablations (01 §13 Sec. 4.5 variants, 03 §6b no-pool / no-eviction / k=1, 09 §7 AlphaEvolve ablations) run **by default** in full mode and are skipped in QUICK mode; `NB_ABLATIONS=0` disables them |
| `GRPO_FROM_POOL=1` | 03 §7 samples GRPO parents from the §6 search pool instead of the seed program |
| `NB_PI_MODEL` | model for the pi sessions (default `RCP_MODEL`) |
| `NB_MAX_TOKENS` | 08 ADAS per-call completion cap (default 4096); OpenRouter reserves credit for the whole cap per in-flight request |
| `AIDE_MAX_TOKENS`, `AIDE_DISABLE_REASONING`, `AIDE_PROMPT_AS_USER`, `AIDE_PACKAGES` | knobs added by `patches/aideml_openrouter.patch` (10 AIDE) |
| `OPENEVOLVE_OPENROUTER=1`, `OPENEVOLVE_USAGE_LOG` | knobs added by `patches/openevolve_openrouter.patch` (09 AlphaEvolve); set by the notebook |
| `S2_MIN_INTERVAL`, `S2_MAX_REFERENCES` | Semantic Scholar pacing for 05 (public API without a key is rate-limited; 04/07 fall back or back off on 429) |

## Layout

```
notebooks/
  common.py              .env loading, OpenRouter chat + JSON helpers, usage/cost tracker, vendoring + patching, run_pi()
  ideagent_extras.py     02: Yield (Alg. 2), CST, greedy max–min topics (Alg. 1), evaluator wrappers, Sequential-Memory / One-Shot baselines, lineage graph
  ideation_study.py      05: helpers around the vendored AI-Researcher modules (Swiss pairing checks, dedup sweep, human-study tables)
  adas_extras.py         08: helpers around the vendored ADAS search (fitness parsing, transfer set, pi workspace)
  autoscientists/        01: state.py queue.py gate.py priors.py stagnation.py roster.py agents.py heartbeat.py task/train.py
  ktpo/                  03: evaluator.py pool.py reward.py refine.py agent.py search.py viz.py grpo_train.py
  aiscientist/           04: OpenRouter client wrapper, pi experiment loop (replaces Aider), CPU template/
  funsearch/             06: package shim over vendor/funsearch + OpenRouter LLM, subprocess sandbox, cap-set / bin-packing specs
  coscientist/           07: standalone re-implementation (state, generation, reflection, ranking, proximity, evolution, metareview, supervisor)
  alphaevolve/           09: OpenEvolve wiring (config, circle-packing evaluator, ablation runner)
  patches/               *_openrouter.patch for IDEAgent, AI-Scientist, AI-Researcher, ADAS, OpenEvolve, aideml (GNU patch -p1, idempotent)
  vendor/                (gitignored) pinned clones re-created by each notebook's setup cell
  outputs/               (gitignored) run artifacts per notebook slug
```

## Cost and time (observed, `deepseek/deepseek-v4-flash`)

Measured on the executed notebooks committed here (single run each, 2026-09-05); the last cell of each notebook prints the exact numbers for that run.

| Notebook | Mode | LLM calls | Cost | Wall clock | Notes |
|---|---|---|---|---|---|
| 01 AutoScientists | full (12 cycles, 3 analysts + 4 experiment agents, 4 ablation crews, 2 pi heartbeats) | 343 | $0.107 | ≈71 min | CPU only; each experiment trains an sklearn MLP in ~0.2 s |
| 02 IDEAgent | full (2 topics, B=5, C_A=5, K_aux=2, M=5; Stateless / Sequential-Memory / One-Shot baselines; 1 pi repair session) | 575 | $0.219 | ≈50 min | mostly evaluator calls |
| 03 KTPO | full (T=8, B=2, N=2, k=3 search + 3 ablations + 40 GRPO steps + 1 pi refine session) | 388 | $0.279 | ≈68 min | GRPO runs in the background alongside the API search; falls back to 20 steps if <12 GB GPU free |
| 04 AI Scientist | full | 24 | $0.034 | ≈15 min | idea reflection, Semantic Scholar novelty, 2 pi experiment runs, reviewer ensemble; no LaTeX. In the committed run every S2 query got HTTP 429 (no `S2_API_KEY`), so the checker gave up and marked the idea not novel |
| 05 Ideation study | full | 88 | $0.053 | ≈78 min | retrieval → 20 seeds → dedup → proposals → Swiss tournament; human-study Tables 7–8 reproduced offline |
| 06 FunSearch | full | 65 | $0.030 | ≈16 min | ~40 samples, 4 islands, cap set n∈{3,4}; reached the known optimum 20 for n=4 in a pre-run |
| 07 Co-scientist | full | 278 | $0.087 | ≈52 min | ~250 calls; Elo tournament + evolution on the platform's PUE research goal |
| 08 ADAS | full | 751 | $0.069 | ≈39 min | Meta Agent Search on MGSM, 3 generations, tiny eval sets |
| 09 AlphaEvolve | full | 68 | $0.081 | ≈27 min | OpenEvolve, 16 iterations, 2 islands, 4 workers + ablations |
| 10 AIDE | full | 28 | $0.033 | ≈12 min | 9 agent steps on a breast-cancer tabular task, tree export, holdout metric |

## Caveats

* **Model.** The papers used frontier models (Claude Sonnet 4.6 as a coding agent; gpt-5.6 / gemini-3.x;
  Qwen3-4B/9B trained on 8×H100). The notebooks use one cheap OpenRouter model for every role, so
  absolute numbers differ from the papers; the mechanisms, not the scores, are what is being tested.
* **AutoScientists** has no LICENSE file; the notebook adapts its role prompts and pseudocode as a
  specification and cites it, but does not vendor the repository.
* **KTPO** code is unpublished; `ktpo/` follows Algorithm 1 and Appendix D of the paper. The GRPO run is
  a 1.5B LoRA model on one GPU — it demonstrates the pipeline and the shape of the curves, not the results.
  A short engineering hint is appended to the paper's prompt for the small model (`--no-hint` removes it),
  and the evaluator re-attaches the benchmark's fixed `run_packing()` entry point when a rewrite drops it.
* **IDEAgent's** shipped runner crashes on a stray constructor argument and has no OpenRouter/base_url
  support; the patch is ~100 lines and is re-applied idempotently by the notebook's setup cell.
* **AI Scientist (04)** ships under the AI Scientist Source Code License v1.0; the generated write-up carries the required machine-generated disclosure. Aider is replaced by pi sessions; LaTeX is not compiled (no `pdflatex`).
* **Ideation study (05)**: the repo's deduplication embedding is `all-MiniLM-L6-v2` (needs torch); the patch substitutes OpenRouter embeddings with a TF-IDF fallback, so the 0.8 threshold is not calibrated the same way. The ranker's 71.4 % validation set is not shipped, so it is quoted, not reproduced. The human-study tables are reproduced exactly from the shipped review data.
* **FunSearch (06)**: a chat model stands in for the paper's code-completion model; two quirks of the released `implementation/` (decorator placement in the preface, `version_generated` off by one) are documented rather than patched; `_reduce_score` uses the last input only.
* **Co-scientist (07)**: no public code; K=32 Elo, LLM-judged proximity, weighted-sampling supervisor are stated design choices. Semantic Scholar is rate-limited from this host; OpenAlex is the fallback.
* **ADAS (08)**: MGSM only (data ships in-repo); generated agent code is `exec`'d in the kernel, not containerised. One functional patch: predictions coerced to `str` before scoring.
* **AlphaEvolve (09)**: OpenEvolve never enforces EVOLVE-BLOCK markers and has no meta-prompt evolution, so two of the paper's ablations cannot be reproduced; a single model stands in for the LLM ensemble.
* **AIDE (10)**: 9 steps and 2 drafts instead of 20/5; the same model serves as code and feedback model; the patch caps `max_tokens`, disables reasoning and sends the prompt as a user message (needed for reliable code blocks on this model).
* Every notebook keeps its executed outputs, so the results can be read without re-running.
