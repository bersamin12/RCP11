"""A bounded, single-process driver for the vendored FunSearch pipeline.

`implementation/funsearch.py:main` wires the four components together and then
calls `Sampler.sample()`, which is a `while True:` loop meant to run on 15
sampler machines against 140 evaluator machines for days.  `run_funsearch`
below is the same wiring with (a) a sample budget, (b) a concrete sandbox and
LLM, and (c) a history log for the plots.  The only structural change is that
one *round* collects `num_samplers` prompts and issues all their LLM calls
concurrently before evaluating them, which is the batched stand-in for the
paper's asynchronous distributed setup.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Sequence

import numpy as np

from funsearch.implementation import code_manipulation
from funsearch.implementation import funsearch as funsearch_lib
from funsearch.implementation import programs_database as pdb
from funsearch.sandbox import RecordingEvaluator


def best_program(database: pdb.ProgramsDatabase):
    """Highest-scoring program held by the database, across islands."""
    island_id = int(np.argmax(database._best_score_per_island))
    return {
        "island": island_id,
        "score": database._best_score_per_island[island_id],
        "function": database._best_program_per_island[island_id],
        "scores_per_test": database._best_scores_per_test_per_island[island_id],
    }


def island_stats(database: pdb.ProgramsDatabase) -> dict[str, list]:
    return {
        "programs": [island._num_programs for island in database._islands],
        "clusters": [len(island._clusters) for island in database._islands],
        "best": [s for s in database._best_score_per_island],
    }


def run_funsearch(
    specification: str,
    inputs: Sequence[Any],
    *,
    config,
    llm,
    sandbox,
    max_samples: int,
    num_samplers: int = 2,
    timeout_seconds: int = 30,
    seed: int | None = 0,
    verbose: bool = True,
) -> dict[str, Any]:
    """Runs the FunSearch loop for at most `max_samples` LLM samples."""
    if seed is not None:
        np.random.seed(seed)
    t_start = time.time()

    # --- exactly the wiring of implementation/funsearch.py:main ---------------
    function_to_evolve, function_to_run = funsearch_lib._extract_function_names(specification)
    template = code_manipulation.text_to_program(specification)
    database = pdb.ProgramsDatabase(config.programs_database, template, function_to_evolve)
    evaluator = RecordingEvaluator(database, template, function_to_evolve,
                                   function_to_run, inputs,
                                   timeout_seconds=timeout_seconds, sandbox=sandbox)
    initial = template.get_function(function_to_evolve).body
    seed_record = evaluator.analyse(initial, island_id=None, version_generated=None)
    if not seed_record["accepted"]:
        raise RuntimeError("the specification's own seed program failed to evaluate")
    # -------------------------------------------------------------------------

    history: list[dict[str, Any]] = []
    n_samples = 0
    round_index = 0
    while n_samples < max_samples:
        round_index += 1
        prompts = [database.get_prompt() for _ in range(num_samplers)]
        with ThreadPoolExecutor(max_workers=num_samplers) as pool:
            batches = list(pool.map(lambda p: llm.draw_samples(p.code), prompts))
        for prompt, samples in zip(prompts, batches):
            for sample in samples:
                if n_samples >= max_samples:
                    break
                record = evaluator.analyse(sample, prompt.island_id, prompt.version_generated)
                n_samples += 1
                score = (pdb._reduce_score(record["scores_per_test"])
                         if record["accepted"] else None)
                stats = island_stats(database)
                history.append({
                    "sample": n_samples, "round": round_index,
                    "island": prompt.island_id, "accepted": record["accepted"],
                    "score": score, "best": max(stats["best"]),
                    "programs_per_island": stats["programs"],
                    "clusters_per_island": stats["clusters"],
                    "seconds": round(time.time() - t_start, 1),
                })
        if verbose:
            b = best_program(database)
            print(f"round {round_index:2d} | {n_samples:3d} samples | "
                  f"accepted {sum(h['accepted'] for h in history):3d} | "
                  f"best {b['score']:.4g} | {time.time() - t_start:5.0f}s")
    return {"database": database, "evaluator": evaluator, "history": history,
            "template": template, "function_to_evolve": function_to_evolve,
            "function_to_run": function_to_run, "seconds": time.time() - t_start,
            "seed_score": pdb._reduce_score(seed_record["scores_per_test"])}
