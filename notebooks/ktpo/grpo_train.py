"""Tiny KTPO Train phase (paper Sec. 3.2) with TRL's GRPOTrainer on one small GPU.

Paper setting: GRPO with the improvement reward r ∈ {+1, 0, −0.5} on B parent groups of N
children, DAPO clip-higher (ε ∈ [0.2, 0.28]), k-step rollouts on 8×H100 with Qwen3-4B.
Here (Appendix-B-style small run): Qwen2.5-Coder-1.5B-Instruct + LoRA, k = 1, one parent
group of N children per optimizer step, max ~1.3k completion tokens, ~20 steps on an RTX A4500.
The goal is to show the pipeline end to end and that reward / valid-rate move, not to reach 2.63.

Run:  python -m ktpo.grpo_train --steps 20 --num-generations 8 --out outputs/ktpo_grpo
Writes: <out>/metrics.jsonl (per step: reward mean, valid rate, best score, seconds),
        <out>/programs.jsonl (valid children discovered), <out>/adapter/ (LoRA weights).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa: E402  (extract_code_block)

from ktpo.evaluator import SEED_PROGRAM, evaluate  # noqa: E402
from ktpo.refine import SYSTEM_MESSAGE, initial_user_message  # noqa: E402
from ktpo.reward import INVALID_PENALTY, grpo_advantages, improvement_rate, reward  # noqa: E402


# Extra task context for the 1.5B model. The paper's per-task context message is free-form
# ("describes the packing problem, geometric insights, and the target score"); a small model
# needs the engineering constraints spelled out or it rewrites the fixed parts and crashes.
SMALL_MODEL_HINT = (
    "\n\nEngineering constraints for this attempt: keep `compute_max_radii(centers)` and "
    "`run_packing()` exactly as in the reference program and change ONLY how `construct_packing()` "
    "places the 26 centers (e.g. a different grid/ring/hexagonal layout, mixed radii via spacing, "
    "or a short numpy-only local search over center positions). Use only numpy. Do not use scipy. "
    "Return the full program in one ```python block and nothing else."
)


def build_dataset(pool: list[dict], n_prompts: int, rng: random.Random, hint: bool = True):
    """Uniformly sample parents from the pool (Alg. 1 line 7); one prompt row per parent draw."""
    from datasets import Dataset

    rows = []
    for _ in range(n_prompts):
        p = rng.choice(pool)
        user = initial_user_message(p["src"], p["score"], k=1) + (SMALL_MODEL_HINT if hint else "")
        rows.append({
            "prompt": [{"role": "system", "content": SYSTEM_MESSAGE}, {"role": "user", "content": user}],
            "parent_score": p["score"],
        })
    return Dataset.from_list(rows)


class KTPOReward:
    """Callable reward for TRL: evaluates each completion and applies equation (1)."""

    __name__ = "ktpo_improvement_reward"

    def __init__(self, out_dir: Path, workers: int = 8):
        self.out_dir = out_dir
        self.workers = workers
        self.step = 0
        self.t0 = time.time()
        self.best = 0.0
        (out_dir / "metrics.jsonl").write_text("")
        (out_dir / "programs.jsonl").write_text("")

    def _score_one(self, text: str):
        src = common.extract_code_block(text)
        if src is None:
            return 0.0, False, "no code block"
        r = evaluate(src)
        return r.score, r.valid, r.feedback

    def __call__(self, prompts, completions, parent_score, **kwargs):
        texts = [c[0]["content"] if isinstance(c, list) else c for c in completions]
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            results = list(ex.map(self._score_one, texts))
        rewards = [reward(score, ps, valid) for (score, valid, _), ps in zip(results, parent_score)]
        scores = [s for s, _, _ in results]
        valid = [v for _, v, _ in results]
        self.step += 1
        self.best = max(self.best, max(scores))
        rec = {"step": self.step, "reward_mean": sum(rewards) / len(rewards), "valid_rate": sum(valid) / len(valid),
               "improve_rate": improvement_rate(scores, parent_score[0]), "best_in_batch": max(scores),
               "best_so_far": self.best, "parent_score": parent_score[0], "rewards": rewards,
               "advantages": grpo_advantages(rewards), "seconds": round(time.time() - self.t0, 1),
               "mean_completion_chars": sum(len(t) for t in texts) / len(texts)}
        with (self.out_dir / "metrics.jsonl").open("a") as f:
            f.write(json.dumps(rec) + "\n")
        with (self.out_dir / "programs.jsonl").open("a") as f:
            for text, (score, ok, _) in zip(texts, results):
                if ok:
                    f.write(json.dumps({"step": self.step, "score": score, "src": common.extract_code_block(text)}) + "\n")
        print(f"[reward] step {self.step}: reward_mean={rec['reward_mean']:+.3f} valid={rec['valid_rate']:.2f} "
              f"best_in_batch={rec['best_in_batch']:.4f} best_so_far={self.best:.4f} ({rec['seconds']:.0f}s)", flush=True)
        return rewards


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-1.5B-Instruct")
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--num-generations", type=int, default=8)
    ap.add_argument("--max-completion-length", type=int, default=1280)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--pool", default=None, help="JSONL of {src, score} parents (default: seed program only)")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "outputs" / "ktpo_grpo"))
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-hint", action="store_true", help="drop the small-model engineering hint")
    args = ap.parse_args()

    import os

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from peft import LoraConfig
    from trl import GRPOConfig, GRPOTrainer

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    if args.pool:
        pool = [json.loads(l) for l in Path(args.pool).read_text().splitlines() if l.strip()]
    else:
        pool = [{"src": SEED_PROGRAM, "score": evaluate(SEED_PROGRAM).score}]
    print(f"pool: {len(pool)} parents, scores {[round(p['score'], 3) for p in pool][:10]}")
    dataset = build_dataset(pool, n_prompts=args.steps, rng=rng, hint=not args.no_hint)

    cfg = GRPOConfig(
        output_dir=str(out / "trainer"),
        max_steps=args.steps,
        # One parent group (N children) per optimizer step. The N completions are generated together
        # (generation_batch_size = N) but the loss is computed in micro-batches of N/2 so the per-token
        # logits (N x ~3k tokens x 152k vocab) fit next to other jobs on a 20 GB GPU.
        per_device_train_batch_size=max(1, args.num_generations // 2) if args.num_generations > 4 else args.num_generations,
        gradient_accumulation_steps=2 if args.num_generations > 4 else 1,
        num_generations=args.num_generations,
        max_completion_length=args.max_completion_length,
        learning_rate=args.lr,
        lr_scheduler_type="constant",
        warmup_steps=0,
        beta=0.0,                     # no KL term (paper does not use one)
        epsilon=0.2, epsilon_high=0.28,  # DAPO clip-higher as in the paper
        loss_type="grpo",
        temperature=1.0, top_p=1.0,
        bf16=True,
        gradient_checkpointing=True,
        logging_steps=1,
        save_strategy="no",
        report_to="none",
        shuffle_dataset=False,
        log_completions=False,
        seed=args.seed,
        model_init_kwargs={"dtype": torch.bfloat16},
    )
    lora = LoraConfig(r=args.lora_r, lora_alpha=2 * args.lora_r, lora_dropout=0.0, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    reward_fn = KTPOReward(out)
    trainer = GRPOTrainer(model=args.model, reward_funcs=reward_fn, args=cfg, train_dataset=dataset, peft_config=lora)
    t0 = time.time()
    trainer.train()
    trainer.model.save_pretrained(out / "adapter")
    (out / "train_log.json").write_text(json.dumps(trainer.state.log_history, indent=1))
    print(f"done in {time.time() - t0:.0f}s; adapter saved to {out / 'adapter'}")


if __name__ == "__main__":
    main()
