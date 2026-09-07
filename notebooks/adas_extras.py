"""Helpers for notebook 08 (ADAS / Meta Agent Search, arXiv 2408.08435).

The vendored authors' repository (``notebooks/vendor/ADAS``, patched with
``patches/adas_openrouter.patch``) provides everything the paper describes: the agent DSL
(``Info`` / ``LLMAgentBase`` / ``AgentSystem``), the seed archive and meta-agent prompts
(``mgsm_prompt``), the search loop (``search``), the evaluation function
(``evaluate_forward_fn``) and the fitness statistic (``bootstrap_confidence_interval``).

This module only adds the notebook-side scaffolding that the repo has no reason to ship:
usage accounting, an argparse-free ``args`` object, parsing of the fitness strings so they can
be tabulated/plotted, an example-set override so the *same* ``evaluate_forward_fn`` can score an
agent on a transfer domain (Sec. 4.3), a re-usable copy of ``search()``'s inner debug loop, and
the small workspace handed to the ``pi`` coding-agent session that plays the meta agent.
"""
from __future__ import annotations

import json
import random
import re
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

# --------------------------------------------------------------------------- plumbing

#: defaults of ``_mgsm/search.py``'s argparse, so the notebook can build ``args`` without a CLI
ARG_DEFAULTS = dict(
    valid_size=128, test_size=800, shuffle_seed=0, n_repreat=1, multiprocessing=True,
    max_workers=48, debug=True, save_dir="results/", expr_name="mgsm_gpt3.5_results",
    n_generation=30, debug_max=3, model="gpt-4o-2024-05-13",
)


def make_args(**overrides) -> SimpleNamespace:
    """The repo's argparse namespace, with notebook-sized budgets patched in."""
    cfg = dict(ARG_DEFAULTS)
    cfg.update(overrides)
    return SimpleNamespace(**cfg)


def install_usage_hook(search_mod, usage) -> None:
    """Route every OpenAI-compatible call made inside the vendored repo into ``common.USAGE``.

    The patch adds a single ``USAGE_HOOK`` call site in each of the repo's two request
    functions; ``tag`` is ``"meta"`` for meta-agent calls and ``"agent"`` for the calls made by
    ``LLMAgentBase`` inside a candidate agent's ``forward()``.
    """
    def hook(response, tag, seconds):
        usage.add(getattr(response, "usage", None), seconds, tag)

    search_mod.USAGE_HOOK = hook


# --------------------------------------------------------------------------- fitness strings
FITNESS_RE = re.compile(
    r"Confidence Interval: \(([\d.]+)%, ([\d.]+)%\), Median: ([\d.]+)%"
)


def parse_fitness(fitness_str: str | None) -> dict[str, float] | None:
    """Parse the repo's fitness string into ``{lo, med, hi}`` percentages.

    The string produced by ``bootstrap_confidence_interval`` is exactly what the paper reports
    as ``median ± half-width`` (Tables 1-6): the median of the bootstrap means and the 95%
    bootstrap confidence interval of the accuracy on the evaluation set.
    """
    if not fitness_str:
        return None
    m = FITNESS_RE.search(fitness_str)
    if not m:
        return None
    lo, hi, med = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return {"lo": lo, "med": med, "hi": hi}


def fitness_pm(fitness_str: str | None) -> str:
    """Render a fitness string in the paper's ``median ± half-width`` table format."""
    f = parse_fitness(fitness_str)
    return "—" if f is None else f"{f['med']:.1f} ± {(f['hi'] - f['lo']) / 2:.1f}"


def archive_rows(archive: list[dict], key: str = "fitness") -> list[dict]:
    """One row per archive entry: generation, name, median fitness, CI."""
    rows = []
    for i, sol in enumerate(archive):
        f = parse_fitness(sol.get(key))
        rows.append({
            "idx": i,
            "generation": sol.get("generation", ""),
            "name": sol.get("name", ""),
            "median %": None if f is None else f["med"],
            "95% CI": None if f is None else f"({f['lo']:.1f}, {f['hi']:.1f})",
            "median ± CI/2": fitness_pm(sol.get(key)),
            "code lines": len(sol.get("code", "").splitlines()),
        })
    return rows


def best_so_far(medians: Iterable[float]) -> list[float]:
    """Cumulative max, the quantity plotted as the Meta Agent Search curve in Fig. 3a."""
    out, cur = [], float("-inf")
    for m in medians:
        cur = max(cur, m)
        out.append(cur)
    return out


# --------------------------------------------------------------------------- archive files
def save_archive(path: str | Path, archive: list[dict]) -> Path:
    """Write the archive in the repo's ``results/<expr_name>_run_archive.json`` format."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(archive, indent=4))
    return path


def load_archive(path: str | Path) -> list[dict]:
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------------- evaluation sets
@contextmanager
def examples_override(search_mod, examples: list[dict]):
    """Temporarily swap the domain's example loader used by ``evaluate_forward_fn``.

    ``evaluate_forward_fn`` reads its questions from ``get_all_examples()`` in the search
    module's globals, so overriding that name lets the *unmodified* evaluation path score an
    agent on a different task set — this is how Sec. 4.3's transfer experiments are run here.
    """
    original = search_mod.get_all_examples
    search_mod.get_all_examples = lambda: list(examples)
    try:
        yield
    finally:
        search_mod.get_all_examples = original


def svamp_examples(repo: str | Path, n: int, seed: int = 0) -> list[dict]:
    """SVAMP (Patel et al., 2021) formatted like the repo's MGSM examples.

    Uses the authors' own transfer-domain formatting from ``_transfer_math/SVAMP_utils.py``:
    ``"Solve this math problem:\\n" + Body + "\\n" + Question`` with the numeric answer as target.
    """
    data = json.loads((Path(repo) / "dataset" / "SVAMP.json").read_text())
    rng = random.Random(seed)
    rng.shuffle(data)
    out = []
    for ex in data[:n]:
        out.append({
            "inputs": "Solve this math problem:\n" + ex["Body"] + "\n" + ex["Question"],
            "targets": str(ex["Answer"]).rstrip("0").rstrip("."),
            "lang": "svamp",
        })
    return out


def mgsm_examples(search_mod, args, split: str = "valid") -> list[dict]:
    """The exact question split ``evaluate_forward_fn`` would use (repo shuffle + slicing)."""
    examples = search_mod.get_all_examples()
    random.seed(args.shuffle_seed)
    random.shuffle(examples)
    if split == "valid":
        return examples[: args.valid_size]
    return examples[args.valid_size: args.valid_size + args.test_size]


# --------------------------------------------------------------------------- meta-agent cycle
def meta_propose(search_mod, prompts_mod, archive: list[dict], model: str,
                 prev_example: dict | None = None) -> tuple[list[dict], list[dict]]:
    """One meta-agent proposal followed by the paper's two reflection rounds (Appendix B).

    Returns ``(solutions, msg_list)`` where ``solutions`` is ``[proposal, after_reflexion_1,
    after_reflexion_2]`` so the notebook can diff them, and ``msg_list`` is the running chat
    that ``search()`` also feeds to the error-driven debug reflection.
    """
    system_prompt, prompt = prompts_mod.get_prompt(archive)
    msg_list = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
    sol = search_mod.get_json_response_from_gpt_reflect(msg_list, model)
    solutions = [dict(sol)]
    r1, r2 = prompts_mod.get_reflexion_prompt(prev_example)
    for reflexion_prompt in (r1, r2):
        msg_list.append({"role": "assistant", "content": str(sol)})
        msg_list.append({"role": "user", "content": reflexion_prompt})
        sol = search_mod.get_json_response_from_gpt_reflect(msg_list, model)
        solutions.append(dict(sol))
    return solutions, msg_list


def evaluate_with_debug(search_mod, args, solution: dict, msg_list: list[dict],
                        on_error: Callable[[int, str], None] | None = None,
                        ) -> tuple[list[int], dict, list[str]]:
    """``search()``'s inner evaluation + error-reflection loop, lifted out so it can be shown.

    Identical control flow to ``search()``: try ``evaluate_forward_fn``; on an exception (or an
    all-zero accuracy, which the repo also treats as a failure while searching) append the error
    to the meta agent's chat, ask it to debug, and retry up to ``args.debug_max`` times.
    """
    acc_list: list[int] = []
    errors: list[str] = []
    for attempt in range(args.debug_max):
        try:
            acc_list = search_mod.evaluate_forward_fn(args, solution["code"])
            if sum(acc_list) / max(len(acc_list), 1) < 0.01 and search_mod.SEARCHING_MODE:
                raise Exception("All 0 accuracy")
            break
        except Exception as exc:  # noqa: BLE001 — mirrors the repo
            errors.append(f"{type(exc).__name__}: {exc}")
            if on_error is not None:
                on_error(attempt, errors[-1])
            msg_list.append({"role": "assistant", "content": str(solution)})
            msg_list.append({"role": "user", "content":
                             f"Error during evaluation:\n{exc}\nCarefully consider where you went wrong in your "
                             "latest implementation. Using insights from previous attempts, try to debug the current "
                             "code to implement the same thought. Repeat your previous thought in 'thought', and put "
                             "your thinking for debugging in 'debug_thought'"})
            solution = search_mod.get_json_response_from_gpt_reflect(msg_list, args.model)
            acc_list = []
    return acc_list, solution, errors


def finalize(solution: dict, acc_list: list[int], search_mod, generation: Any) -> dict:
    """Attach fitness + generation and drop the scratch fields, exactly as ``search()`` does."""
    solution = dict(solution)
    solution["fitness"] = search_mod.bootstrap_confidence_interval(acc_list)
    solution["generation"] = generation
    solution.pop("debug_thought", None)
    solution.pop("reflection", None)
    return solution


# --------------------------------------------------------------------------- pi workspace
EVAL_SCRIPT = '''"""Score one candidate agent on {n} MGSM questions (ADAS, arXiv 2408.08435).

Usage:  python evaluate_agent.py <file.py>

<file.py> must contain exactly one top-level function, `forward(self, taskInfo)`, written
against the DSL documented in FRAMEWORK.md. The script installs it on the repo's AgentSystem
and scores it with the authors' own evaluate_forward_fn / bootstrap_confidence_interval.
"""
import os, sys
os.environ.setdefault("TQDM_DISABLE", "1")
sys.path.insert(0, {repo!r} + "/_mgsm")
sys.path.insert(0, {nbdir!r})
from dotenv import load_dotenv
load_dotenv({envfile!r}, override=False)
from types import SimpleNamespace
import search as S

args = SimpleNamespace(valid_size={n}, test_size={n}, shuffle_seed={seed}, n_repreat=1,
                       multiprocessing=True, max_workers={n}, debug=True, debug_max=1,
                       save_dir="results/", expr_name="pi", n_generation=1, model=S.RCP_MODEL)

code = open(sys.argv[1]).read()
acc_list = S.evaluate_forward_fn(args, code)
print("accuracy per question:", acc_list)
print("FITNESS:", S.bootstrap_confidence_interval(acc_list))
'''


def write_pi_workspace(directory: str | Path, *, repo: str | Path, nb_dir: str | Path,
                       env_file: str | Path, archive: list[dict], framework_code: str,
                       n_questions: int = 5, seed: int = 0) -> dict[str, Path]:
    """Lay out the sandbox the pi coding-agent session works in.

    The meta agent in the paper sees three things: the framework/DSL, the archive of previously
    discovered agents with their fitness, and the instruction to emit a new ``forward()``. Here
    the first two are files and the third is the session prompt; the agent writes code to disk
    and runs the evaluation script itself.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    lines = ["# Archive of discovered agents", "",
             "Each entry was scored on the same MGSM validation questions; `fitness` is the median",
             "and 95% bootstrap confidence interval of the accuracy. Maximise the median.", ""]
    for sol in archive:
        lines += [f"## {sol['name']}  (generation {sol.get('generation', '?')})",
                  f"fitness: {sol.get('fitness', 'not evaluated')}", "",
                  "thought: " + " ".join(str(sol.get("thought", "")).split())[:600], "",
                  "```python", sol["code"].strip(), "```", ""]
    archive_md = directory / "ARCHIVE.md"
    archive_md.write_text("\n".join(lines))

    framework_md = directory / "FRAMEWORK.md"
    framework_md.write_text(
        "# The agent framework you must program against\n\n"
        "Your new agent is a single top-level function `forward(self, taskInfo)`. It receives the\n"
        "question as an `Info` namedtuple and must return the answer (an `Info`, or a string).\n"
        "`Info`, `LLMAgentBase` and `random_id` already exist in the execution namespace — do NOT\n"
        "import or redefine them, do not construct `Info` objects yourself, and do not print.\n\n"
        "```python\n" + framework_code.strip() + "\n```\n"
    )

    eval_py = directory / "evaluate_agent.py"
    eval_py.write_text(EVAL_SCRIPT.format(repo=str(repo), nbdir=str(nb_dir),
                                          envfile=str(env_file), n=n_questions, seed=seed))
    return {"archive": archive_md, "framework": framework_md, "evaluate": eval_py}


def read_pi_fitness(text: str) -> str | None:
    """Pull the ``FITNESS:`` line the evaluation script prints out of a pi transcript."""
    m = re.search(r"FITNESS: (95% Bootstrap[^\n]*)", text)
    return m.group(1) if m else None
