"""MultiStepRefine (paper Sec. 3.1, App. D prompt templates).

For one parent p_i the model produces k sequential revisions c^(1..k). Each step conditions on
the previous attempt and the evaluator's structured feedback (step number, remaining attempts,
score/validity/diagnostics or error, reference score, scores so far). Output must be a complete
program in a single ```python block; s* is the best score across the trajectory.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402

from .evaluator import Result, evaluate  # noqa: E402

# ---- App. D.1 system message (verbatim from the paper) ----
SYSTEM_MESSAGE = (
    "You are an expert software developer tasked with iteratively improving a codebase. "
    "Your job is to analyze the current program and suggest improvements based on feedback "
    "from previous attempts. Focus on making targeted changes that will increase the "
    "program's performance metrics."
)

# ---- task context injected into the user prompt (paper: "describes the packing problem, geometric insights, target") ----
TASK_CONTEXT = """Problem: place n=26 non-overlapping circles inside the unit square [0,1]^2 to MAXIMISE the
sum of radii. The program must define `construct_packing()` returning (centers, radii, sum_radii)
with centers shape (26,2) and radii shape (26,), and keep the fixed `run_packing()` entry point.
A packing is valid only if every circle lies inside the square and no two circles overlap
(tolerance 1e-6); invalid packings score 0. The best known sum of radii is ≈2.635 (AlphaEvolve).
Useful ideas: mixed radii (a few large circles plus small gap-fillers), hexagonal/staggered
layouts, and numerical optimisation (scipy.optimize with overlap/boundary penalties, or iterative
radius growth) starting from a good initial layout. Keep runtime under ~20 seconds."""

# ---- App. D.2 output format instructions (verbatim) ----
OUTPUT_FORMAT = (
    "Output the COMPLETE, SELF-CONTAINED program as a single ```python code block. "
    "Your code block MUST include ALL imports, ALL helper functions, and the main entry-point "
    "function. Do NOT output partial snippets, diffs, or incomplete code — every code block you "
    "produce will be executed as a standalone program."
)

# ---- App. D.3 reward rules (verbatim) ----
REWARD_RULES = (
    "You will get multiple refinement attempts. After each attempt, you will see your score and "
    "can try again. Your reward is based on the BEST score you achieve across all attempts minus "
    "your starting score. You get PENALIZED for producing INVALID programs (syntax errors, runtime "
    "errors, or constraint violations). You get PENALIZED for producing the SAME score as your "
    "previous attempt (lazy repetition). Therefore: always aim to improve, avoid generating broken "
    "code, and do not repeat the same solution."
)


def initial_user_message(parent_src: str, parent_score: float, k: int) -> str:
    return (
        f"{TASK_CONTEXT}\n\n{REWARD_RULES}\n\nYou have {k} refinement attempts.\n\n"
        f"Reference program (score {parent_score:.4f}):\n```python\n{parent_src}\n```\n\n"
        f"Improve this program. {OUTPUT_FORMAT}"
    )


def feedback_message(step: int, k: int, result: Result, reference_score: float, scores_so_far: list[float]) -> str:
    """App. D.4 multi-step feedback (success and error variants)."""
    trail = " ".join(f"{s:.4f}" for s in scores_so_far[:-1])
    last = f"{scores_so_far[-1]:.4f}"
    trail_txt = f"{trail} → {last} (this step)" if trail else f"{last} (this step)"
    if result.error:
        head = f"[Step {step}/{k}, {k - step} remaining] this_step={result.score:.4f} error={result.error}"
    else:
        head = f"[Step {step}/{k}, {k - step} remaining] {result.feedback}"
    return (
        f"{head}\nReference program score: {reference_score:.4f}\nYour scores so far:    {trail_txt}\n\n"
        f"Think about how to improve this solution further. Output your COMPLETE revised program as a "
        f"single ```python code block."
    )


@dataclass
class Trajectory:
    parent_score: float
    steps: list[dict] = field(default_factory=list)   # {step, src, result}

    @property
    def best_score(self) -> float:            # s* = max_l s(c^(l))
        return max((s["result"].score for s in self.steps), default=0.0)

    @property
    def best_src(self) -> str | None:
        valid = [s for s in self.steps if s["result"].valid]
        return max(valid, key=lambda s: s["result"].score)["src"] if valid else None

    @property
    def any_valid(self) -> bool:
        return any(s["result"].valid for s in self.steps)

    @property
    def valid_children(self) -> list[dict]:
        return [s for s in self.steps if s["result"].valid]


def multistep_refine(parent_src: str, parent_score: float, k: int, *, temperature: float = 1.0,
                     max_tokens: int = 8000, verbose: bool = False, tag: str = "refine") -> Trajectory:
    """Run k sequential refinement steps with an API model; returns the full trajectory."""
    messages = [{"role": "system", "content": SYSTEM_MESSAGE},
                {"role": "user", "content": initial_user_message(parent_src, parent_score, k)}]
    traj = Trajectory(parent_score)
    scores: list[float] = []
    for step in range(1, k + 1):
        reply = common.chat("", messages=messages, temperature=temperature, max_tokens=max_tokens, tag=tag)
        src = common.extract_code_block(reply)
        if src is None:
            result = Result(0.0, False, "error=no python code block emitted", error="no ```python code block emitted")
            src = ""
        else:
            result = evaluate(src)
        scores.append(result.score)
        traj.steps.append({"step": step, "src": src, "result": result})
        fb = feedback_message(step, k, result, parent_score, scores)
        if verbose:
            print(fb.splitlines()[0])
        messages.append({"role": "assistant", "content": reply})
        messages.append({"role": "user", "content": fb})
    return traj
