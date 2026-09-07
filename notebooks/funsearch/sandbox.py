"""A concrete `Sandbox` and a recording `Evaluator` for the vendored FunSearch.

`implementation/evaluator.py` ships an abstract `Sandbox` whose `run` raises
NotImplementedError ("Must provide a sandbox for executing untrusted code") --
DeepMind used an internal one.  `SubprocessSandbox` below runs the assembled
program in a *fresh interpreter* with a hard wall-clock timeout, so a sample
that loops forever, crashes, or eats memory only costs one dead subprocess.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from funsearch.implementation import evaluator as evaluator_lib

PKG_DIR = Path(__file__).resolve().parent          # provides utils_capset / utils_packing
NB_DIR = PKG_DIR.parent                            # provides the `funsearch` shim package

_RUNNER = '''\
import json, math, sys, traceback
sys.path[:0] = {paths!r}
import funsearch  # supplies the identity @funsearch.run / @funsearch.evolve decorators

PROGRAM = {program!r}
TEST_INPUT = {test_input!r}
namespace = {{"funsearch": funsearch, "__name__": "__funsearch_sandbox__"}}
try:
    exec(compile(PROGRAM, "<program>", "exec"), namespace)
{resolve}
    output = namespace[{function_to_run!r}](argument)
except BaseException:
    sys.stderr.write(traceback.format_exc())
    sys.stdout.write(json.dumps({{"ok": False}}))
else:
    if output is None:
        sys.stdout.write(json.dumps({{"ok": True, "output": None}}))
    elif (isinstance(output, bool) or not isinstance(output, (int, float))
          or not math.isfinite(output)):
        sys.stderr.write("run function returned %r, not a finite int/float score" % (output,))
        sys.stdout.write(json.dumps({{"ok": False}}))
    else:
        sys.stdout.write(json.dumps({{"ok": True, "output": float(output)}}))
'''


class SubprocessSandbox(evaluator_lib.Sandbox):
    """Executes `function_to_run(test_input)` in a separate, time-limited process.

    Args:
      resolve: source line(s) building `argument` from `TEST_INPUT`.  The cap set
        specification takes the dimension `n` directly; the bin packing one takes a
        `Problem` object, which is rebuilt inside the subprocess from its name.
    """

    def __init__(self, resolve: str = "argument = TEST_INPUT", memory_mb: int | None = 2048):
        self.resolve = resolve
        self.memory_mb = memory_mb
        self.log: list[dict[str, Any]] = []

    def run(self, program: str, function_to_run: str, test_input: Any,
            timeout_seconds: int) -> tuple[Any, bool]:
        script = _RUNNER.format(
            paths=[str(PKG_DIR), str(NB_DIR)],
            program=program,
            test_input=test_input,
            function_to_run=function_to_run,
            resolve="\n".join("    " + line for line in self.resolve.splitlines()),
        )
        t0 = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_sample.py"
            path.write_text(script)
            try:
                proc = subprocess.run(
                    [sys.executable, str(path)], capture_output=True, text=True,
                    timeout=timeout_seconds, cwd=tmp)
                stdout, stderr, timed_out = proc.stdout, proc.stderr, False
            except subprocess.TimeoutExpired:
                stdout, stderr, timed_out = "", f"timeout after {timeout_seconds}s", True
        output, ok = None, False
        if not timed_out:
            try:
                payload = json.loads(stdout or "{}")
                ok = bool(payload.get("ok"))
                output = payload.get("output")
            except json.JSONDecodeError:
                ok, output = False, None
        self.log.append({"input": test_input, "ok": ok, "output": output,
                         "seconds": round(time.time() - t0, 3),
                         "error": (stderr.strip().splitlines() or [""])[-1][:200]})
        return output, ok


class RecordingEvaluator(evaluator_lib.Evaluator):
    """`Evaluator` with the vendored `analyse` logic plus a per-sample record.

    The body of `analyse` is the vendored one line for line (compare
    `show_source(evaluator.Evaluator.analyse)`); the only additions are the
    `record` dict and returning it, so the notebook can display what happened to
    a sample that was discarded.
    """

    def __init__(self, *args, sandbox: evaluator_lib.Sandbox | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if sandbox is not None:
            self._sandbox = sandbox
        self.records: list[dict[str, Any]] = []

    def analyse(self, sample: str, island_id: int | None,
                version_generated: int | None) -> dict[str, Any]:
        new_function, program = evaluator_lib._sample_to_program(
            sample, version_generated, self._template, self._function_to_evolve)
        calls_ancestor = evaluator_lib._calls_ancestor(program, self._function_to_evolve)
        record: dict[str, Any] = {
            "island": island_id, "version": version_generated,
            "body": new_function.body, "program": program,
            "calls_ancestor": calls_ancestor, "failures": [],
        }

        scores_per_test = {}
        for current_input in self._inputs:
            test_output, runs_ok = self._sandbox.run(
                program, self._function_to_run, current_input, self._timeout_seconds)
            if runs_ok and not calls_ancestor and test_output is not None:
                if not isinstance(test_output, (int, float)):
                    raise ValueError('@function.run did not return an int/float score.')
                scores_per_test[current_input] = test_output
            else:
                reason = ("calls an ancestor" if calls_ancestor else
                          "sandbox error" if not runs_ok else "returned None (invalid solution)")
                record["failures"].append({"input": current_input, "reason": reason,
                                           "error": self._sandbox.log[-1]["error"]
                                           if getattr(self._sandbox, "log", None) else ""})
        record["scores_per_test"] = scores_per_test
        record["accepted"] = bool(scores_per_test)
        self.records.append(record)
        if scores_per_test:
            self._database.register_program(new_function, island_id, scores_per_test)
        return record
