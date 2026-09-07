"""MultiStepRefine run as a *coding agent* session instead of a raw k-step chat trajectory.

The paper's refine phase (Sec. 3.1) is a fixed loop: the policy emits a complete program, the
evaluator scores it, the App. D.4 feedback string is appended, repeat k times. This module keeps
the same evaluator-in-the-loop contract but hands the loop to a tool-using coding agent (pi):
the agent edits ``program.py`` in a scratch directory and calls ``evaluate.py`` (a CLI wrapper
around :func:`ktpo.evaluator.evaluate` that prints exactly the App. D.4 feedback line) whenever
it wants feedback. Every evaluation is appended to ``evals.jsonl`` so the notebook can recover
the same per-step trail (scores, s* = max over steps) the paper's trajectory produces.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .refine import OUTPUT_FORMAT, REWARD_RULES, TASK_CONTEXT

NB_DIR = Path(__file__).resolve().parents[1]

# The evaluator CLI the agent is told to run. It is deliberately tiny and prints the paper's
# App. D.4 feedback message verbatim (via ktpo.refine.feedback_message), so the text the agent
# reads between edits is the same text the frozen-policy trajectory of §5 receives.
CLI_TEMPLATE = '''#!/usr/bin/env python
"""KTPO evaluator CLI: score a candidate program and print the App. D.4 feedback line."""
import json, sys, time
from pathlib import Path

sys.path.insert(0, {nb_dir!r})
from ktpo.evaluator import evaluate
from ktpo.refine import feedback_message

PARENT_SCORE = {parent_score!r}
K = {k!r}
LOG = Path(__file__).resolve().parent / "evals.jsonl"

path = Path(sys.argv[1] if len(sys.argv) > 1 else "program.py")
src = path.read_text()
result = evaluate(src)
history = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()] if LOG.exists() else []
scores = [h["score"] for h in history] + [result.score]
step = len(scores)
# The App. D.4 feedback text, minus its closing "output a complete python code block" instruction
# (in the agentic setting the revised program is an edit of program.py, not a chat reply).
head, _, _ = feedback_message(min(step, K), K, result, PARENT_SCORE, scores).partition("\\n\\nThink about")
print(head)
print(f"Think about how to improve this solution further, then EDIT program.py and run this "
      f"evaluator again ({{max(0, K - step)}} attempts left).")
with LOG.open("a") as f:
    f.write(json.dumps({{"step": step, "score": result.score, "valid": result.valid,
                        "feedback": result.feedback, "error": result.error,
                        "src": src, "t": time.time()}}) + "\\n")
if step >= K:
    print(f"[budget] {{step}}/{{K}} evaluation attempts used - stop editing and make sure "
          f"program.py holds your best-scoring version.")
'''


def setup_workspace(cwd: str | Path, parent_src: str, parent_score: float, k: int = 3) -> Path:
    """Create the agent's scratch directory: program.py (the pool parent) + evaluate.py + clean log."""
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    (cwd / "program.py").write_text(parent_src)
    (cwd / "evaluate.py").write_text(
        CLI_TEMPLATE.format(nb_dir=str(NB_DIR), parent_score=float(parent_score), k=int(k))
    )
    (cwd / "evals.jsonl").unlink(missing_ok=True)
    return cwd


def agent_prompt(parent_score: float, k: int = 3, python: str | None = None) -> str:
    """App. D task context + reward rules, restated as an agent workflow over the two files."""
    python = python or sys.executable
    agent_rules = REWARD_RULES.replace(
        "You will get multiple refinement attempts. After each attempt, you will see your score and "
        "can try again.",
        f"You get at most {k} evaluation attempts. After each attempt you will see your score and can edit again.",
    )
    return (
        f"{TASK_CONTEXT}\n\n{agent_rules}\n\n"
        f"WORKING DIRECTORY (you are already in it):\n"
        f"  program.py   the reference program, score {parent_score:.4f} - EDIT THIS FILE IN PLACE\n"
        f"  evaluate.py  the KTPO evaluator CLI - DO NOT EDIT\n\n"
        f"Loop to follow, at most {k} times:\n"
        f"  1. read program.py (first time only);\n"
        f"  2. edit program.py into a better packing;\n"
        f"  3. run `{python} evaluate.py program.py` with the bash tool (it takes up to 60 s);\n"
        f"  4. read the feedback line (this_step score, validity, boundary_violations, overlaps, or error)\n"
        f"     and decide what to change next.\n\n"
        f"Rules: keep `construct_packing()` returning (centers, radii, sum_radii) and the fixed "
        f"`run_packing()` entry point; the program must finish in under 20 s. After your last "
        f"evaluation, program.py MUST contain the BEST-scoring version you produced - if a later "
        f"edit scored worse, restore the better one and re-run the evaluator to confirm. "
        f"Finish with one line: the best score you reached.\n\n"
        f"(Reminder about the output contract in the non-agentic setting: {OUTPUT_FORMAT})"
    )


def read_evals(cwd: str | Path) -> list[dict]:
    """The agent's evaluation trail (one record per evaluate.py call), i.e. its k-step trajectory."""
    log = Path(cwd) / "evals.jsonl"
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
