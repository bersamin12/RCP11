"""Deterministic evaluator s(·) for Circle Packing n=26, wrapping OpenEvolve's example.

``evaluate(src)`` writes the program to a temp file, runs OpenEvolve's ``evaluator.evaluate``
(itself a subprocess with a timeout), and returns a ``Result`` with the score (sum of radii,
0.0 if invalid), validity, and the diagnostic feedback string the refine loop shows the model
(paper App. D.4: score, validity, boundary/overlap counts, or the error traceback).
"""
from __future__ import annotations

import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "openevolve_circle_packing"
sys.path.insert(0, str(VENDOR))
import evaluator as _oe  # noqa: E402  (OpenEvolve's evaluator.py)

# OpenEvolve's helper prints subprocess stdout/stderr for debugging. Silence it at module level
# (thread-safe) instead of contextlib.redirect_stdout, which swaps the process-wide sys.stdout and
# corrupts notebook output when evaluations run concurrently in threads.
_oe.print = lambda *a, **k: None

SEED_PROGRAM_FULL = (VENDOR / "initial_program.py").read_text()


def _compact(src: str) -> str:
    """OpenEvolve's seed minus the matplotlib `visualize()` helper and `__main__` block.

    Those parts are never executed by the evaluator; dropping them keeps the program the model
    must reproduce at ~70 lines, which matters for a 1.5B model with a 1-2k token budget.
    """
    head, _, _ = src.partition("\n\ndef visualize(")
    return head.rstrip() + "\n"


SEED_PROGRAM = _compact(SEED_PROGRAM_FULL)
# OpenEvolve marks `run_packing()` (after EVOLVE-BLOCK-END) as the fixed, non-evolved entry point.
FIXED_TAIL = SEED_PROGRAM.split("# EVOLVE-BLOCK-END", 1)[1]
TIMEOUT_S = 60


def with_fixed_tail(src: str) -> str:
    """Re-attach the benchmark's fixed entry point if a full-program rewrite dropped it."""
    if "def run_packing" in src:
        return src
    return src.rstrip() + "\n\n# EVOLVE-BLOCK-END" + FIXED_TAIL


@dataclass
class Result:
    score: float          # s(p): sum of radii if valid else 0.0
    valid: bool
    feedback: str         # diagnostics shown to the model at the next refinement step
    sum_radii_raw: float = 0.0
    boundary_violations: int = 0
    overlaps: int = 0
    error: str | None = None


def _diagnostics(centers: np.ndarray, radii: np.ndarray) -> tuple[int, int]:
    n = len(radii)
    boundary = int(sum(1 for (x, y), r in zip(centers, radii)
                       if x - r < -1e-6 or x + r > 1 + 1e-6 or y - r < -1e-6 or y + r > 1 + 1e-6))
    overlaps = 0
    for i in range(n):
        for j in range(i + 1, n):
            if np.linalg.norm(centers[i] - centers[j]) < radii[i] + radii[j] - 1e-6:
                overlaps += 1
    return boundary, overlaps


def evaluate(src: str, timeout_s: int = TIMEOUT_S) -> Result:
    src = with_fixed_tail(src)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        try:
            centers, radii, reported = _oe.run_with_timeout(path, timeout_seconds=timeout_s)
        except Exception as exc:  # program crashed / timed out / returned garbage
            msg = str(exc)
            m = re.search(r"Program execution failed: (.*)", msg)
            lines = (m.group(1) if m else msg).strip().splitlines()
            err = (lines[-1] if lines else f"{type(exc).__name__} with no message (crash or timeout)")[:300]
            return Result(0.0, False, f"error={err}", error=err)
        centers = np.asarray(centers, dtype=float)
        radii = np.asarray(radii, dtype=float)
        if centers.shape != (26, 2) or radii.shape != (26,):
            err = f"invalid shapes centers={centers.shape} radii={radii.shape}, expected (26,2) and (26,)"
            return Result(0.0, False, f"error={err}", error=err)
        if np.isnan(centers).any() or np.isnan(radii).any() or (radii < 0).any():
            err = "NaN or negative radius in solution"
            return Result(0.0, False, f"error={err}", error=err)
        boundary, overlaps = _diagnostics(centers, radii)
        raw = float(radii.sum())
        valid = boundary == 0 and overlaps == 0
        score = raw if valid else 0.0
        fb = f"this_step={score:.4f} validity={valid} boundary_violations={boundary} overlaps={overlaps}"
        if not valid:
            fb += f" (raw sum_radii={raw:.4f}, score set to 0 because the packing is invalid)"
        return Result(score, valid, fb, raw, boundary, overlaps)
    finally:
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    r = evaluate(SEED_PROGRAM)
    print(r)
