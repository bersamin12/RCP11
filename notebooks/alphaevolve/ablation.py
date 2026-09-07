"""The paper's "No evolution" ablation (Sec. 4), built from real OpenEvolve parts.

AlphaEvolve's ablation "repeatedly feeds the same initial program to the language
model" instead of resurfacing evolved programs from the database.  OpenEvolve has no
flag for that, because the database *is* the loop, so this module unrolls one
controller iteration - exactly the sequence in
``openevolve.process_parallel._run_iteration_worker`` - and pins the parent to p0.

Everything that does work here is the library's: ``PromptSampler.build_prompt``,
``LLMEnsemble.generate_with_context``, ``code_utils.extract_diffs/apply_diff/
parse_full_rewrite`` and ``Evaluator.evaluate_program``.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any


async def generate_child(
    ensemble,
    sampler,
    evaluator,
    parent_code: str,
    parent_metrics: dict,
    *,
    diff_based: bool = True,
    previous_programs: list | None = None,
    top_programs: list | None = None,
    inspirations: list | None = None,
    artifacts: dict | None = None,
    feature_dimensions: list[str] | None = None,
    round_: int = 1,
) -> dict[str, Any]:
    """One unrolled controller iteration: prompt -> LLM -> apply -> evaluate."""
    from openevolve.utils.code_utils import (
        apply_diff,
        extract_diffs,
        format_diff_summary,
        parse_full_rewrite,
    )

    t0 = time.time()
    prompt = sampler.build_prompt(
        current_program=parent_code,
        parent_program=parent_code,
        program_metrics=parent_metrics,
        previous_programs=previous_programs or [],
        top_programs=top_programs or [],
        inspirations=inspirations or [],
        language="python",
        evolution_round=round_,
        diff_based_evolution=diff_based,
        program_artifacts=artifacts,
        feature_dimensions=feature_dimensions or [],
    )
    response = await ensemble.generate_with_context(
        system_message=prompt["system"], messages=[{"role": "user", "content": prompt["user"]}]
    )
    out: dict[str, Any] = {"prompt": prompt, "response": response, "seconds": time.time() - t0}
    if diff_based:
        blocks = extract_diffs(response)
        out["diff_blocks"] = blocks
        if not blocks:
            out["error"] = "No valid diffs found in response"
            out["metrics"] = {}
            return out
        out["child_code"] = apply_diff(parent_code, response)
        out["changes"] = format_diff_summary(blocks)
    else:
        code = parse_full_rewrite(response, "python")
        if not code:
            out["error"] = "No valid code found in response"
            out["metrics"] = {}
            return out
        out["child_code"] = code
        out["changes"] = "Full rewrite"
    out["metrics"] = await evaluator.evaluate_program(out["child_code"], str(uuid.uuid4()))
    out["seconds"] = time.time() - t0
    return out


async def no_evolution_run(
    ensemble, sampler, evaluator, seed_code: str, seed_metrics: dict, n: int, *, concurrency: int = 4
) -> list[dict[str, Any]]:
    """Paper Sec. 4 "No evolution": n independent proposals, all from p0, no context."""
    sem = asyncio.Semaphore(concurrency)

    async def guarded(i: int) -> dict[str, Any]:
        async with sem:
            try:
                return await generate_child(
                    ensemble, sampler, evaluator, seed_code, seed_metrics,
                    diff_based=True, round_=i + 1,
                )
            except Exception as exc:  # a failed sample is a failed iteration
                return {"error": f"{type(exc).__name__}: {exc}", "metrics": {}}

    return await asyncio.gather(*(guarded(i) for i in range(n)))
