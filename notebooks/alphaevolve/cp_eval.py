"""Evaluation file for the circle-packing task (AlphaEvolve Sec. 2.1 "Evaluation").

This is *not* a re-implementation: it loads OpenEvolve's own
``examples/circle_packing/evaluator.py`` and re-exports its ``evaluate`` /
``evaluate_stage1`` / ``evaluate_stage2`` unchanged.  Two notebook-only shims:

* the example runs the candidate in a subprocess with a 600 s timeout - far too
  long for a notebook budget, so the timeout is capped (``CP_TIMEOUT`` seconds);
* the example prints its diagnostics with ``print``; a module-global ``print`` is
  installed that appends to :data:`LOG` instead, so a cell that evaluates a
  program does not flood the notebook.  ``last_log()`` shows the diagnostics.

OpenEvolve's ``Evaluator`` loads this file by path and calls the three functions
below, so the real cascade / timeout / retry machinery is exercised.
"""
from __future__ import annotations

import importlib.util
import os
import traceback as _traceback
import types as _types
from pathlib import Path

CP_DIR = Path(__file__).resolve().parents[1] / "vendor" / "openevolve" / "examples" / "circle_packing"
CP_TIMEOUT = int(os.environ.get("CP_EVAL_TIMEOUT", "20"))

_spec = importlib.util.spec_from_file_location("cp_evaluator_upstream", CP_DIR / "evaluator.py")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)

LOG: list[str] = []
_base.print = lambda *a, **k: LOG.append(" ".join(str(x) for x in a))  # module-global shadows builtin
# the upstream evaluator also dumps tracebacks straight to stderr; route them to LOG as well
_base.traceback = _types.SimpleNamespace(
    print_exc=lambda *a, **k: LOG.append(_traceback.format_exc()),
    format_exc=_traceback.format_exc,
)

_run_with_timeout = _base.run_with_timeout
_base.run_with_timeout = lambda path, timeout_seconds=CP_TIMEOUT: _run_with_timeout(
    path, timeout_seconds=min(timeout_seconds, CP_TIMEOUT)
)

validate_packing = _base.validate_packing
evaluate = _base.evaluate
evaluate_stage1 = _base.evaluate_stage1
evaluate_stage2 = _base.evaluate_stage2
upstream = _base


def last_log(n: int = 6) -> str:
    """Diagnostics printed by the upstream evaluator during the last call(s)."""
    return "\n".join(LOG[-n:])


def clear_log() -> None:
    LOG.clear()


def evaluate_source(source: str, *, stage: str = "full") -> dict:
    """Convenience: evaluate a program given as a string (writes a temp file)."""
    import tempfile

    fn = {"full": evaluate, "stage1": evaluate_stage1, "stage2": evaluate_stage2}[stage]
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(source)
        path = fh.name
    try:
        return fn(path)
    finally:
        os.unlink(path)
