"""Helpers for notebook ``05_ideation_study.ipynb`` (Si, Yang & Hashimoto, ICLR 2025).

The agent itself lives in the vendored repository ``notebooks/vendor/AI-Researcher``
(``github.com/NoviScl/AI-Researcher`` @ ``e5dd05a``, MIT licence) patched by
``notebooks/patches/ai_researcher_openrouter.patch``. This module only holds the glue the
notebook needs on top of it: path/usage wiring, small parallel drivers, plotting, the
human-study statistics, and a pure-Python check of the Swiss pairing rule.
"""
from __future__ import annotations

import json
import os
import random
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import common

# The seven topics of the study, verbatim from Appendix A.
TOPICS = {
    "Bias": "novel prompting methods to reduce social biases and stereotypes of large language models",
    "Coding": "novel prompting methods for large language models to improve code generation",
    "Safety": "novel prompting methods to improve large language models' robustness against adversarial attacks or improve their security or privacy",
    "Multilingual": "novel prompting methods to improve large language models' performance on multilingual tasks or low-resource languages and vernacular languages",
    "Factuality": "novel prompting methods that can improve factuality and reduce hallucination of large language models",
    "Math": "novel prompting methods for large language models to improve mathematical problem solving",
    "Uncertainty": "novel prompting methods that can better quantify uncertainty or calibrate the confidence of large language models",
}

SEED_IDEA_FIELDS = ["Problem", "Existing Methods", "Motivation", "Proposed Method", "Experiment Plan"]
# Appendix B project-proposal template (the keys the generator is asked to produce).
PROPOSAL_FIELDS = ["Title", "Problem Statement", "Motivation", "Proposed Method",
                   "Step-by-Step Experiment Plan", "Test Case Examples", "Fallback Plan"]


# --------------------------------------------------------------------------- wiring
def setup(vendor: str | Path) -> Path:
    """Put the repo's ``src`` on ``sys.path`` and route its cost tracker into ``common.USAGE``.

    The repo's modules import each other by bare name (``from utils import call_api``), so the
    ``src`` directory itself has to be on the path, not the package root.
    """
    src = Path(vendor) / "ai_researcher" / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    common.env()  # exports OPENROUTER_API_KEY / RCP_MODEL / RCP_BASE_URL, which the patch reads
    import utils

    utils.RCP_USAGE_HOOK = lambda usage, seconds, tag: common.USAGE.add(usage, seconds, tag)
    return src


def set_tag(tag: str) -> None:
    """Label the calls the vendored code makes next, so ``USAGE.by_tag`` is readable."""
    import utils

    utils.RCP_TAG = tag


def prompts_dir(vendor: str | Path) -> Path:
    return Path(vendor) / "ai_researcher" / "prompts"


# --------------------------------------------------------------------------- retrieval
def paper_rows(paper_bank: list[dict], n: int = 10) -> list[dict]:
    return [
        {
            "score": p.get("score"),
            "year": p.get("year"),
            "cites": p.get("citationCount"),
            "title": (p.get("title") or "")[:80],
        }
        for p in paper_bank[:n]
    ]


def _salvage_json_pairs(text: str) -> dict:
    """Recover the complete ``"name": "description"`` pairs from a truncated JSON dict."""
    import re
    out = {}
    for m in re.finditer(r'"((?:[^"\\]|\\.)+)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*(?=,|\})', text):
        try:
            out[json.loads('"' + m.group(1) + '"')] = json.loads('"' + m.group(2) + '"')
        except json.JSONDecodeError:
            continue
    print(f"[idea_gen] salvaged {len(out)} complete ideas from truncated output")
    return out


# --------------------------------------------------------------------------- generation
def generate_seed_ideas(paper_bank, examples, topic_description, *, n_batches: int, ideas_n: int,
                        rag_schedule=None, grounding_k: int = 10, max_tokens: int = 8000,
                        temperature: float = 1.0, workers: int = 4):
    """Run the repo's ``idea_generation`` ``n_batches`` times and flatten the results.

    Sec. 3.2 generates 4000 seed ideas per topic in small batches, re-seeding each batch and
    appending the titles of everything generated so far so the model is asked not to repeat
    itself; retrieval augmentation is used for half the batches (Appendix F). Batches are run
    in parallel here, so the "previously generated ideas" list is per-wave rather than strictly
    incremental -- see the notebook for what that costs in duplication.
    """
    from grounded_idea_gen import idea_generation

    rag_schedule = rag_schedule or [i % 2 == 0 for i in range(n_batches)]
    batches: list[dict] = []
    existing: list[str] = []

    def one(args):
        seed, rag = args
        random.seed(seed)
        prev = "; ".join(sorted(set(existing))) if existing else None
        budget, last = max_tokens, None
        for attempt in range(3):
            _, response, _ = idea_generation(
                "prompting", prev, paper_bank, grounding_k, examples, ideas_n, topic_description,
                None, "rcp", seed + 100 * attempt, temperature, 1.0, budget, RAG="True" if rag else "False")
            try:
                return json.loads(response.strip())
            except json.JSONDecodeError:
                # The model overran max_tokens mid-JSON (the repo uses 30k by default): retry
                # with a doubled budget, then fall back to salvaging the complete pairs.
                last = response
                print(f"[idea_gen] batch {seed}: truncated JSON at {budget} tokens, retrying with {budget * 2}")
                budget *= 2
        return _salvage_json_pairs(last)

    args = [(seed, rag_schedule[seed - 1]) for seed in range(1, n_batches + 1)]
    with ThreadPoolExecutor(max_workers=min(workers, len(args))) as ex:
        for out in ex.map(one, args):
            batches.append(out)
            existing.extend(out.keys())
    return batches


def flatten_ideas(batches: list[dict]) -> tuple[list[str], list]:
    names, values = [], []
    for batch in batches:
        for k, v in batch.items():
            names.append(k)
            values.append(v)
    return names, values


def generate_proposals(ideas: dict, demo_examples: str, topic_description: str, *,
                       workers: int = 4, seed: int = 2024):
    """Expand seed ideas into Appendix-B project proposals (``experiment_plan_gen``), in parallel."""
    from experiment_plan_gen import plan_generation_method

    items = list(ideas.items())

    def one(item):
        name, idea = item
        try:
            _, response, _ = plan_generation_method("prompting", idea, demo_examples,
                                                    topic_description, None, "rcp", seed)
            plan = json.loads(response.strip())
            # Some samples wrap the proposal under its idea name ({"<name>": {"Title": ...}}).
            if isinstance(plan, dict) and len(plan) == 1:
                inner = next(iter(plan.values()))
                if isinstance(inner, dict) and any(k in inner for k in PROPOSAL_FIELDS):
                    plan = inner
            return name, plan
        except Exception as exc:  # noqa: BLE001
            print(f"  [proposal failed for {name!r}: {type(exc).__name__}: {str(exc)[:120]}]")
            return name, None

    out = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as ex:
        for name, plan in ex.map(one, items):
            if plan:
                out[name] = plan
    return out


def concat_ideas(names, values):
    """Render seed ideas with the repo's ``concatenate_idea`` -> (texts, names, values, dropped).

    ``concatenate_idea`` indexes the five seed-idea fields directly, so an idea that came back
    missing one (the model does drop ``Experiment Plan`` occasionally) raises ``KeyError``. The
    repo's ``__main__`` wraps the call in ``try/except: continue`` and silently discards those;
    this mirrors that behaviour but also reports which ideas were lost.
    """
    from dedup_ideas import concatenate_idea

    texts, keep_names, keep_values, dropped = [], [], [], []
    for name, value in zip(names, values):
        try:
            texts.append(concatenate_idea(name, value))
            keep_names.append(name)
            keep_values.append(value)
        except Exception:  # noqa: BLE001  (the repo uses a bare `except: continue` here)
            dropped.append(name)
    return texts, keep_names, keep_values, dropped


# --------------------------------------------------------------------------- deduplication
def plot_similarity(sim: np.ndarray, threshold: float = 0.8, title: str = "") -> None:
    """Heatmap of the pairwise cosine matrix plus the histogram of upper-triangle values."""
    import matplotlib.pyplot as plt

    iu = np.triu_indices(len(sim), k=1)
    vals = sim[iu]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    im = axes[0].imshow(sim, cmap="magma", vmin=0, vmax=1)
    fig.colorbar(im, ax=axes[0], label="cosine similarity")
    axes[0].set(title=f"pairwise similarity {title}", xlabel="idea j", ylabel="idea i")
    axes[1].hist(vals, bins=30, color="#4878a8", edgecolor="white")
    axes[1].axvline(threshold, color="crimson", ls="--", label=f"threshold {threshold}")
    axes[1].set(title=f"upper-triangle similarities (n={len(vals)})", xlabel="cosine similarity",
                ylabel="# pairs")
    axes[1].legend()
    plt.tight_layout()
    plt.show()


def threshold_sweep(names, values, texts, sim, thresholds) -> list[dict]:
    """How many ideas survive the repo's greedy filter at each similarity threshold."""
    from dedup_ideas import dedup_ideas

    rows = []
    for t in thresholds:
        kept, _ = dedup_ideas(texts, names, values, sim, similarity_threshold=t)
        rows.append({"threshold": t, "#kept": len(kept), "#removed": len(texts) - len(kept)})
    return rows


# --------------------------------------------------------------------------- ranking
def swiss_pairing_check() -> list[dict]:
    """Pure-Python probe of the Swiss pairing rule on hand-built scores (no LLM involved).

    Checks the two properties Sec. 3.3 relies on: pairs are score-matched (neighbours in the
    score-sorted order) and, with an odd field, exactly one proposal gets a free point.
    """
    from tournament_ranking import swiss_pairs

    cases = [
        ("even, all tied", {"a": 0, "b": 0, "c": 0, "d": 0}),
        ("even, distinct scores", {"a": 3, "b": 2, "c": 1, "d": 0}),
        ("even, two score groups", {"a": 2, "b": 2, "c": 1, "d": 1}),
        ("odd -> bye for the last", {"a": 3, "b": 2, "c": 1, "d": 1, "e": 0}),
        ("single proposal", {"a": 1}),
    ]
    rows = []
    for label, scores in cases:
        pairs, bye = swiss_pairs(list(scores), lambda i: scores[i])
        gaps = [abs(scores[x] - scores[y]) for x, y in pairs]
        rows.append({
            "case": label,
            "scores": scores,
            "pairs": [f"{x}-{y}" for x, y in pairs],
            "bye": bye,
            "max |score gap| in a pair": max(gaps) if gaps else None,
            "everyone plays once": sorted([p for pr in pairs for p in pr] + ([bye] if bye else [])) == sorted(scores),
        })
    return rows


def simulate_tournament(true_quality: list[float], rounds: int = 5, noise: float = 0.25,
                        trials: int = 200, seed: int = 0) -> dict:
    """Swiss tournament with a synthetic noisy judge -- does the pairing rule recover the order?

    Uses the repo's ``swiss_pairs``; the judge picks the higher-quality proposal with a
    probability set by a logistic on the quality gap. No LLM calls.
    """
    from tournament_ranking import swiss_pairs

    rng = random.Random(seed)
    n = len(true_quality)
    top1, spearman = 0, []
    for _ in range(trials):
        scores = {i: 1 for i in range(n)}
        order = list(range(n))
        rng.shuffle(order)
        for r in range(rounds):
            pairs, bye = swiss_pairs(order, lambda i: scores[i])
            if bye is not None:
                scores[bye] += 1
            for i, j in pairs:
                gap = (true_quality[i] - true_quality[j]) / max(noise, 1e-6)
                p = 1.0 / (1.0 + np.exp(-gap))
                scores[i if rng.random() < p else j] += 1
        # break score ties at random: the index order correlates with true quality here, so an
        # index tie-break would credit the tournament with information it never received.
        ranked = sorted(range(n), key=lambda i: (-scores[i], rng.random()))
        top1 += int(true_quality[ranked[0]] == max(true_quality))
        final = np.array([scores[i] for i in range(n)], dtype=float)
        spearman.append(_spearman(final, np.array(true_quality)))
    return {"rounds": rounds, "judge noise": noise, "top-1 hit rate": top1 / trials,
            "mean Spearman rho": float(np.mean(spearman))}


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    from scipy import stats

    rho = stats.spearmanr(a, b).statistic
    return 0.0 if np.isnan(rho) else float(rho)   # all-tied scores give an undefined correlation


def judge_pair(idea_1, idea_2, seed: int = 2024):
    """One zero-shot pairwise judgment (``tournament_ranking.better_idea``) -> (raw, parsed)."""
    from tournament_ranking import better_idea, parse_choice

    _, result, _ = better_idea(idea_1, idea_2, "zero_shot", None, "rcp", seed)
    return result, parse_choice(result)


def position_consistency(pairs, seed: int = 2024, workers: int = 4) -> list[dict]:
    """Run each pair in both orders; the judge is self-consistent when the same proposal wins.

    §7.2 reports that this ranker only reaches 53.3% balanced accuracy against expert reviews,
    below the 56.1% inter-reviewer consistency; the ICLR accept/reject validation set of §3.3 is
    not shipped with the repo, so position consistency is the reliability probe available here.
    """
    def one(args):
        label, a, b = args
        raw_ab, c_ab = judge_pair(a, b, seed)
        raw_ba, c_ba = judge_pair(b, a, seed)
        winner_ab = {"1": "A", "2": "B"}.get(c_ab)
        winner_ba = {"1": "B", "2": "A"}.get(c_ba)
        return {"pair": label, "raw (A,B)": raw_ab[:20], "raw (B,A)": raw_ba[:20],
                "winner (A,B)": winner_ab, "winner (B,A)": winner_ba,
                "consistent": winner_ab is not None and winner_ab == winner_ba}

    with ThreadPoolExecutor(max_workers=min(workers, len(pairs))) as ex:
        return list(ex.map(one, pairs))


def yes_no(response: str) -> bool:
    """The repo's verdict convention: the last token of the reply is 'yes' or 'no'."""
    tokens = (response or "").lower().replace("*", "").strip().strip(".").split()
    return bool(tokens) and tokens[-1].strip(".") == "yes"


# --------------------------------------------------------------------------- human study data
def human_study_frame(vendor: str | Path):
    import pandas as pd

    path = Path(vendor) / "reviews_ideation" / "data_points_all_anonymized.json"
    return pd.DataFrame(json.load(open(path)))


METRICS = ["novelty_score", "excitement_score", "feasibility_score", "effectiveness_score", "overall_score"]


def welch_table(df, metrics=None, label: str = "") -> list[dict]:
    """Welch's t-tests vs the Human condition with Bonferroni correction over the 5 metrics.

    This is ``reviews_ideation/stats_overall.py`` with ``statsmodels.multipletests(method=
    'bonferroni')`` written out as ``min(p*m, 1)`` so the notebook needs no extra dependency.
    """
    from scipy import stats

    metrics = metrics or METRICS
    m = len(metrics)
    ai, human, rr = df[df.condition == "AI"], df[df.condition == "Human"], df[df.condition == "AI_Rerank"]
    rows = []
    for metric in metrics:
        t_ai, p_ai = stats.ttest_ind(ai[metric], human[metric], equal_var=False)
        t_rr, p_rr = stats.ttest_ind(rr[metric], human[metric], equal_var=False)
        rows.append({
            "metric": metric.replace("_score", ""),
            f"Human ({len(human)})": f"{human[metric].mean():.2f} ± {human[metric].std(ddof=0):.2f}",
            f"AI ({len(ai)})": f"{ai[metric].mean():.2f} ± {ai[metric].std(ddof=0):.2f}",
            f"AI+Rerank ({len(rr)})": f"{rr[metric].mean():.2f} ± {rr[metric].std(ddof=0):.2f}",
            "p (AI vs Human)": round(min(p_ai * m, 1.0), 4),
            "p (Rerank vs Human)": round(min(p_rr * m, 1.0), 4),
        })
    return rows


def plot_novelty(df) -> None:
    import matplotlib.pyplot as plt

    conds = [("Human", "Human Ideas"), ("AI", "AI Ideas"), ("AI_Rerank", "AI + Human Rerank")]
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.8))
    means = [df[df.condition == c]["novelty_score"].mean() for c, _ in conds]
    errs = [df[df.condition == c]["novelty_score"].sem() for c, _ in conds]
    axes[0].bar([n for _, n in conds], means, yerr=errs, capsize=5,
                color=["#8c8c8c", "#4878a8", "#3a6b3a"])
    axes[0].set(ylabel="novelty score (1-10)", ylim=(0, 7), title="Novelty by condition (cf. Fig. 1)")
    for i, v in enumerate(means):
        axes[0].text(i, v + 0.25, f"{v:.2f}", ha="center")
    bins = np.arange(0.5, 11.5, 1)
    for (c, n), col in zip(conds, ["#8c8c8c", "#4878a8", "#3a6b3a"]):
        axes[1].hist(df[df.condition == c]["novelty_score"], bins=bins, histtype="step", lw=2,
                     label=n, color=col, density=True)
    axes[1].set(xlabel="novelty score", ylabel="density", title="Novelty score distribution")
    axes[1].legend(fontsize=8)
    plt.tight_layout()
    plt.show()
