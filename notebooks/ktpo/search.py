"""KTPO Algorithm 1 in inference-only mode (frozen API model): Refine → (Train skipped) → Update pool.

``ktpo_search`` runs T iterations of: sample B parents uniformly from P; for each parent run
N k-step refinements; add valid intermediate programs to P; compute β_i, record mastered parents
in the rolling buffer, and evict programs below s̄. Ablation switches: ``use_pool=False``
(always start from p0) and ``use_eviction=False`` (never evict).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .pool import Program, ProgramPool
from .refine import multistep_refine
from .reward import EvictionTracker, grpo_advantages, improvement_rate, mastery_threshold, reward


@dataclass
class IterationLog:
    t: int
    tau_t: float
    parents: list[dict] = field(default_factory=list)   # {pid, score, beta, mastered, rewards, advantages, best_children}
    threshold: float | None = None
    evicted: int = 0
    pool_size: int = 0
    best: float = 0.0
    avg_best_of_k: float = 0.0    # paper Fig. 2b/3a: mean over children of s*
    llm_calls: int = 0
    seconds: float = 0.0
    # --- instrumentation for the notebook's mechanism walkthrough (not part of Alg. 1) ---
    buffer: list[float] = field(default_factory=list)      # rolling window R after this iteration
    top: list[dict] = field(default_factory=list)          # top-5 pool snapshot after eviction
    evicted_scores: list[float] = field(default_factory=list)
    added: int = 0                                          # programs added by line 11 this iteration


def ktpo_search(seed_src: str, seed_score: float, *, T: int, B: int, N: int, k: int,
                tau0: float = 0.3, tauT: float = 0.0, W: int = 10, use_pool: bool = True,
                use_eviction: bool = True, rng_seed: int = 0, verbose: bool = True,
                temperature: float = 1.0, workers: int = 8) -> tuple[ProgramPool, list[IterationLog]]:
    rng = random.Random(rng_seed)
    pool = ProgramPool.from_seed(seed_src, seed_score)
    tracker = EvictionTracker(window=W)
    logs: list[IterationLog] = []
    seed_prog = pool.best
    for t in range(1, T + 1):
        t0 = time.time()
        tau_t = mastery_threshold(t, T, tau0, tauT)
        log = IterationLog(t=t, tau_t=tau_t)
        parents = pool.sample(rng, B) if use_pool else [seed_prog] * B
        all_best = []
        # The B·N trajectories of one iteration are independent (the paper runs them as a batch);
        # run them concurrently so wall-clock is dominated by one k-step trajectory, not B·N of them.
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=max(1, min(workers, B * N))) as ex:
            futures = {p.pid: [ex.submit(multistep_refine, p.src, p.score, k, temperature=temperature, tag=f"refine_t{t}") for _ in range(N)] for p in parents}
            all_trajs = {pid: [f.result() for f in fs] for pid, fs in futures.items()}
        for p in parents:
            trajs = all_trajs[p.pid]
            rewards = [reward(tr.best_score, p.score, tr.any_valid) for tr in trajs]
            best_children = [tr.best_score for tr in trajs]
            all_best += best_children
            for tr in trajs:                        # line 11: add valid intermediate programs
                for s in tr.valid_children:
                    log.added += pool.add(Program(s["src"], s["result"].score, parent=p.pid, iteration=t, origin="child"))
            beta = improvement_rate(best_children, p.score)
            mastered = tracker.record_if_mastered(beta, p.score, tau_t) if use_eviction else False
            log.parents.append({"pid": p.pid, "score": p.score, "beta": beta, "mastered": mastered,
                                "rewards": rewards, "advantages": grpo_advantages(rewards), "best_children": best_children,
                                "traj_scores": [[st["result"].score for st in tr.steps] for tr in trajs],
                                "traj_valid": [[st["result"].valid for st in tr.steps] for tr in trajs]})
            log.llm_calls += N * k
        if use_eviction and tracker.threshold is not None:
            log.threshold = tracker.threshold
            evicted = pool.evict(tracker.threshold)
            log.evicted, log.evicted_scores = len(evicted), sorted((round(e.score, 4) for e in evicted), reverse=True)
        log.buffer = list(tracker.mastered)
        log.top = [{"pid": q.pid, "score": round(q.score, 4), "origin": q.origin, "born_at": q.iteration}
                   for q in sorted(pool.programs.values(), key=lambda q: -q.score)[:5]]
        log.pool_size, log.best = len(pool), pool.best.score
        log.avg_best_of_k = sum(all_best) / len(all_best)
        log.seconds = time.time() - t0
        pool.record(t, log.evicted, log.threshold)
        logs.append(log)
        if verbose:
            print(f"iter {t}: τ={tau_t:.2f} best={log.best:.4f} avg_best_of_k={log.avg_best_of_k:.3f} "
                  f"pool={log.pool_size} evicted={log.evicted} s̄={log.threshold and round(log.threshold, 4)} "
                  f"β={[round(x['beta'], 2) for x in log.parents]} ({log.seconds:.0f}s)")
    return pool, logs
