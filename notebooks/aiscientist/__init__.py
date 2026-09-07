"""Glue for notebook 04 (The AI Scientist, arXiv 2408.06292).

The vendored repository (``notebooks/vendor/AI-Scientist``) is used as-is wherever possible; this
module only supplies what a notebook run needs on top of it:

* ``make_client``          — the repo's own ``create_client("openrouter/<model>")`` wrapped so that
                             every call the vendored code makes lands in ``common.USAGE``.
* ``search_for_papers``    — drop-in replacement for the repo's Semantic Scholar helper with a
                             bounded retry budget, graceful 429 handling and a query log, so the
                             novelty check cannot hang the notebook.
* ``pi_experiment_loop``   — ``perform_experiments`` with the Aider coder replaced by a live pi
                             coding-agent session (``common.run_pi``); the prompts, the run
                             numbering, the "Run N completed..." feedback and the ``notes.txt``
                             convention all come from the repo.
* ``unified_diff``         — the edit a pi session made to ``experiment.py``.
* ``TEMPLATE_DIR``/``new_experiment_folder`` — the small CPU template written for this notebook and
                             the ``do_idea`` folder set-up (copy template, seed ``notes.txt``).
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

NB_DIR = Path(__file__).resolve().parent.parent
VENDOR = NB_DIR / "vendor" / "AI-Scientist"
TEMPLATE_DIR = Path(__file__).resolve().parent / "template"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

import common  # noqa: E402


# --------------------------------------------------------------------------- tracked LLM client
class _TrackedCompletions:
    def __init__(self, inner, holder):
        self._inner, self._holder = inner, holder

    def create(self, **kw):
        t0 = time.time()
        resp = self._inner.create(**kw)
        common.USAGE.add(getattr(resp, "usage", None), time.time() - t0, self._holder.tag)
        return resp


class TrackedClient:
    """Thin proxy around the OpenAI client the repo builds: counts calls into ``common.USAGE``.

    ``tag`` is mutable so a single client can be re-labelled per stage (ideation / novelty / review).
    """

    def __init__(self, inner, tag: str = "aiscientist"):
        self._inner = inner
        self.tag = tag
        self.chat = SimpleNamespace(completions=_TrackedCompletions(inner.chat.completions, self))

    def __getattr__(self, name):  # everything else (models, embeddings, ...) passes straight through
        return getattr(self._inner, name)


def make_client(tag: str = "aiscientist", max_tokens: int = 8192):
    """Build the repo's OpenRouter client for ``RCP_MODEL`` and wrap it for usage accounting."""
    e = common.env()
    os.environ.setdefault("OPENROUTER_API_KEY", e["api_key"])
    os.environ["MAX_NUM_TOKENS"] = str(max_tokens)  # read by the patched ai_scientist.llm
    from ai_scientist.llm import create_client

    inner, model = create_client("openrouter/" + e["model"])
    return TrackedClient(inner, tag), model


# --------------------------------------------------------------------------- Semantic Scholar
SEARCH_LOG: list[dict] = []


def search_for_papers(query, result_limit=10, engine="semanticscholar", max_tries=4, pause=2.0):
    """Same signature as ``ai_scientist.generate_ideas.search_for_papers``, but bounded.

    The repo decorates its version with an *unbounded* ``backoff.on_exception`` on ``HTTPError``,
    which on a 429 from the public Semantic Scholar endpoint can retry forever.  Here every query is
    retried at most ``max_tries`` times with linear back-off and then gives up with an empty result
    list (the repo returns ``None``, which its own ``check_idea_novelty`` then iterates over and
    crashes on).  Every attempt is appended to ``SEARCH_LOG`` so the notebook can show the rounds.
    """
    import requests

    if not query:
        return None
    entry = {"round": len(SEARCH_LOG) + 1, "query": query, "status": None, "n_results": 0, "tries": 0}
    SEARCH_LOG.append(entry)
    for attempt in range(max_tries):
        entry["tries"] = attempt + 1
        try:
            rsp = requests.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                headers={"X-API-KEY": os.getenv("S2_API_KEY")} if os.getenv("S2_API_KEY") else {},
                params={
                    "query": query,
                    "limit": result_limit,
                    "fields": "title,authors,venue,year,abstract,citationStyles,citationCount",
                },
                timeout=30,
            )
            entry["status"] = rsp.status_code
            if rsp.status_code in (429, 500, 502, 503, 504):
                time.sleep(pause * (attempt + 1))
                continue
            rsp.raise_for_status()
            results = rsp.json()
            papers = results.get("data", []) or []
            entry["n_results"] = len(papers)
            entry["titles"] = [p.get("title", "") for p in papers[:5]]
            time.sleep(1.0)  # the repo's own courtesy pause
            return papers
        except Exception as exc:  # noqa: BLE001
            entry["status"] = f"{type(exc).__name__}"
            time.sleep(pause * (attempt + 1))
    entry["gave_up"] = True
    return []


# --------------------------------------------------------------------------- experiment folder
def new_experiment_folder(dest: Path, idea: dict, baseline_results: dict) -> Path:
    """`launch_scientist.do_idea`: copy the template, then seed `notes.txt` with the baseline run."""
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(TEMPLATE_DIR, dest)
    with open(dest / "notes.txt", "w") as f:
        f.write(f"# Title: {idea['Title']}\n")
        f.write(f"# Experiment description: {idea['Experiment']}\n")
        f.write("## Run 0: Baseline\n")
        f.write(f"Results: {baseline_results}\n")
        f.write("Description: Baseline results.\n")
    return dest


def unified_diff(before: str | Path, after: str | Path, name: str = "experiment.py", n: int = 2) -> str:
    a = Path(before).read_text().splitlines(keepends=True)
    b = Path(after).read_text().splitlines(keepends=True)
    return "".join(difflib.unified_diff(a, b, f"a/{name}", f"b/{name}", n=n))


# --------------------------------------------------------------------------- pi in place of Aider
PI_ROLE = """You are the code-editing agent inside The AI Scientist's experiment loop -- the role \
Aider plays in the paper (Sec. 3, "Experiment Iteration").

You are already in the experiment directory: `experiment.py`, `plot.py`, `notes.txt` and the \
completed `run_*/` directories. Rules:
* Work fast and small. Implement ONE run per turn: the smallest edit to `experiment.py` that \
realises the next planned run, then stop and reply.
* Use the `edit` tool with short search/replace edits -- this is Aider's `diff` edit format. Never \
rewrite a whole file, never paste a file back in full.
* Do NOT execute `experiment.py` yourself. The harness runs `python experiment.py --out_dir=run_i` \
after your turn and reports the results back to you. Use `bash` only for quick read-only checks or \
to append to `notes.txt`, never to train.
* The edited script must still write `final_info.json` in `--out_dir` in the same \
`{dataset: {"means": {...}, "stderrs": {...}}}` format, must keep both datasets and all 3 seeds, \
must stay on the CPU and must finish in under 60 seconds.
* Keep the run cheap: no new dependencies, no downloads, no large sweeps.
* Append a short entry to `notes.txt` describing the run you just set up (experimental-journal \
style), and end your reply with a one-paragraph summary of the change.
"""


def _context_block(folder: Path) -> str:
    notes = (Path(folder) / "notes.txt").read_text()
    return f"\nThe experimental journal so far is:\n<notes.txt>\n{notes}</notes.txt>\n"


def _run_experiment_tolerant(run_experiment, folder: Path, run: int, timeout: int):
    """Call the repo's `run_experiment`; if the coder broke the `final_info.json` schema, turn the
    KeyError into the same kind of error feedback the repo sends for a crashed run, so the coder
    gets a chance to fix it instead of the harness dying."""
    import json as _json
    try:
        return run_experiment(folder, run, timeout=timeout)
    except (KeyError, TypeError, AttributeError, _json.JSONDecodeError) as e:
        path = Path(folder) / f"run_{run}" / "final_info.json"
        head = path.read_text()[:800] if path.exists() else "<missing>"
        feedback = (
            f"Run {run} executed, but final_info.json does not follow the required schema "
            f"({type(e).__name__}: {e}). It must be exactly {{dataset: {{'means': {{...}}, "
            f"'stderrs': {{...}}}}}} with the dataset names as top-level keys and no extra nesting.\n"
            f"Current file starts with:\n{head}\n\n"
            f"Fix experiment.py so that `python experiment.py --out_dir=run_{run}` writes the correct "
            f"schema, then reply. Do not run it yourself."
        )
        return 1, feedback


def pi_experiment_loop(
    folder: Path,
    idea: dict,
    baseline_results: dict,
    *,
    max_runs: int = 2,
    max_iters: int = 2,
    pi_timeout: int = 540,
    exp_timeout: int = 300,
    tag: str = "pi-experiment",
    tools: str = "read,bash,edit",
    show=None,
) -> list[dict]:
    """`perform_experiments` with `coder.run(...)` replaced by one ephemeral pi session per turn.

    Returns one record per turn: the pi session, the harness return code and the feedback prompt
    that the repo builds from `final_info.json` ("Run N completed. Here are the results: ...").
    """
    from ai_scientist.perform_experiments import coder_prompt, run_experiment

    folder = Path(folder)
    next_prompt = coder_prompt.format(
        title=idea["Title"], idea=idea["Experiment"], max_runs=max_runs, baseline_results=baseline_results
    )
    history: list[dict] = []
    run, current_iter = 1, 0
    while run < max_runs + 1:
        if current_iter >= max_iters:
            print("Max iterations reached")
            break
        # pi sessions are stateless, unlike Aider's persistent chat: re-supply the role and journal.
        prompt = PI_ROLE + _context_block(folder) + "\n" + next_prompt
        session = common.run_pi(prompt, cwd=folder, tools=tools, timeout=pi_timeout, tag=tag)
        rec = {"run": run, "session": session, "prompt": prompt}
        history.append(rec)
        if show is not None:
            show(session)
        if "ALL_COMPLETED" in session.final_text:
            rec["returncode"], rec["feedback"] = None, "ALL_COMPLETED"
            break
        returncode, next_prompt = _run_experiment_tolerant(run_experiment, folder, run, exp_timeout)
        rec["returncode"], rec["feedback"] = returncode, next_prompt
        if returncode == 0:
            run += 1
            current_iter = 0
        current_iter += 1
    return history


IMPROVEMENT_ROLE = """You are the writing agent inside The AI Scientist's improvement stage \
(`perform_improvement` in the repository, which hands the review to Aider with the instruction \
"Improve the text using the review."). LaTeX is not available in this environment, so the \
manuscript is the markdown file `writeup.md` in this directory and there is nothing to compile.
"""
