"""Pieces of the IDEAgent paper that the public repository does not ship, plus thin wrappers.

* ``yield_count``            — Algorithm 2: Yield(NB ≥ k, S ≥ l, C ≥ m, D ≥ τ) via the vendored exact
                               maximum-clique routine (``ideagent.diversity_metrics._maximum_clique``).
* ``successful_topics``, ``cst`` — the successful-topic indicator and Cost per Successful Topic (eq. 7).
* ``greedy_maxmin_topics``   — Algorithm 1: greedy max–min topic selection over sentence embeddings.
* ``make_client``            — OpenRouter-backed role client through the patched ``build_client``.
* ``external_quality``, ``pairwise_diversity`` — the paper's post-hoc evaluation protocol (Sec. 5) run
                               with the repo's own ``QualityEvaluator`` / ``TopicalDiversityEvaluator``.
* ``stateless_baseline``     — the Stateless baseline (Sec. 6.2): B independent Ideator calls.
* ``sequential_memory_baseline`` — the Sequential-Memory baseline (Sec. 6.2), run through the repo's
                               own ``ideagent.sequential_memory_baseline.run_sequential_memory_baseline``.
* ``one_shot_baseline``      — the One-Shot baseline (Sec. 6.2) with the repo's own single-shot
                               directive and JSON schema (``baselines/simple/pipeline.py``).
* ``run_topics_parallel``    — run several ``GenerationLoop.run_topic`` searches concurrently with
                               topic-tagged, thread-safe progress lines.
* ``score_idea_set``, ``table1``, ``yield_surface_by_method`` — the paper's Table 1 / Fig. 2 views.
* ``stage_flow_diagram``, ``lineage_graph`` — Fig. 1 (left) control flow and Fig. 1 (right) lineage
                               evolution, drawn from the run's own ``candidates_<topic>.jsonl``.
"""
from __future__ import annotations

import json
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

NB_DIR = Path(__file__).resolve().parent
VENDOR = NB_DIR / "vendor" / "IDEAgent"
if str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))

import common  # noqa: E402
from ideagent.agents import IdeatorAgent  # noqa: E402
from ideagent.clients import build_client  # noqa: E402
from ideagent.diversity_eval import TopicalDiversityEvaluator  # noqa: E402
from ideagent.diversity_metrics import _maximum_clique  # noqa: E402
from ideagent.prompts import op_free_baseline  # noqa: E402
from ideagent.quality_eval import QualityEvaluator  # noqa: E402


# ----------------------------------------------------------------------------- Algorithm 2: Yield
def yield_count(nb: list[float], s: list[float], c: list[float], pair_scores: dict[tuple[int, int], int],
                *, k: float, l: float, m: float, tau: int) -> tuple[int, list[int]]:
    """Yield(NB ≥ k, S ≥ l, C ≥ m, D ≥ τ): size of the largest mutually-distinct subset of the ideas
    that individually pass all three quality thresholds (paper Alg. 2). Returns (count, indices)."""
    eligible = [i for i in range(len(nb)) if nb[i] >= k and s[i] >= l and c[i] >= m]

    def compatible(i: int, j: int) -> bool:
        return pair_scores.get((min(i, j), max(i, j)), -1) >= tau

    best = _maximum_clique(eligible, compatible)
    return len(best), best


def yield_surface(nb, s, c, pair_scores, *, k_values, l_values, m: float, tau: int) -> np.ndarray:
    """Yield over a grid of (non-obviousness k, soundness l) thresholds (paper Fig. 2 / Fig. 4)."""
    return np.array([[yield_count(nb, s, c, pair_scores, k=k, l=l, m=m, tau=tau)[0] for k in k_values] for l in l_values])


def successful_topics(yields: list[int], phi: int) -> float:
    """Proportion of topics with Yield ≥ Φ (Sec. 5 'Successful Topics')."""
    return sum(y >= phi for y in yields) / len(yields) if yields else float("nan")


def cst(costs: list[float], yields: list[int], phi: int) -> float | None:
    """Cost per Successful Topic (eq. 7): total generation cost / number of topics with Yield ≥ Φ."""
    n_success = sum(y >= phi for y in yields)
    return None if n_success == 0 else sum(costs) / n_success


# ----------------------------------------------------------------------------- Algorithm 1: topic selection
def greedy_maxmin_topics(embeddings: np.ndarray, budget: int) -> list[int]:
    """Greedy max–min selection over cosine similarities (paper Alg. 1).

    Seed = the most isolated topic (lowest mean similarity to the others); then repeatedly add the
    topic whose maximum similarity to the selected set is smallest."""
    E = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
    S = E @ E.T
    n = len(S)
    mean_sim = (S.sum(1) - 1.0) / (n - 1)
    selected = [int(np.argmin(mean_sim))]
    remaining = set(range(n)) - set(selected)
    while len(selected) < min(budget, n):
        i_star = min(remaining, key=lambda i: max(S[i, j] for j in selected))
        selected.append(int(i_star))
        remaining.remove(i_star)
    return selected


def tfidf_embed(texts: list[str]) -> np.ndarray:
    from sklearn.feature_extraction.text import TfidfVectorizer

    return TfidfVectorizer(ngram_range=(1, 2), stop_words="english").fit_transform(texts).toarray()


def openrouter_embed(texts: list[str], model: str = "openai/text-embedding-3-small") -> np.ndarray | None:
    """Sentence embeddings through OpenRouter's embeddings endpoint; None if unavailable."""
    try:
        resp = common.client().embeddings.create(model=model, input=texts)
        return np.array([d.embedding for d in resp.data])
    except Exception as exc:  # noqa: BLE001
        print(f"(embeddings unavailable via OpenRouter: {str(exc)[:120]}) → falling back to TF-IDF")
        return None


# ----------------------------------------------------------------------------- clients
# OpenRouter rejects a request whose *reserved* max_tokens exceeds the account's remaining credit
# ("402 ... in_flight_budget_exhausted" / "can only afford N tokens"). That is transient whenever the
# competing in-flight requests are someone else's, so back off and retry instead of failing the notebook.
_TRANSIENT = ("in_flight", "in-flight", "429", "rate limit", "rate_limit", "overloaded", "timed out")
_FATAL = ("requires more credits",)   # an exhausted account: retrying only wastes wall-clock
_RETRY_SLEEPS = (20, 45, 90, 180)


def _retry_transient(fn, *args, **kwargs):
    for wait in (*_RETRY_SLEEPS, None):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            if wait is None or any(f in msg for f in _FATAL) or not any(t in msg for t in _TRANSIENT):
                raise
            print(f"  (transient API error, retrying in {wait}s: {str(exc)[:110]})", flush=True)
            time.sleep(wait)


class TrackedClient:
    """Delegating wrapper that records every call of a vendored IDEAgent client in ``common.USAGE``
    and retries transient gateway failures (402 in-flight-budget / 429 rate limit) with backoff."""

    def __init__(self, inner, tag: str):
        self._inner, self._tag = inner, tag

    def _record(self, t0: float) -> None:
        meta = self._inner.get_last_response_metadata() or {}
        usage = meta.get("usage") or {}
        from types import SimpleNamespace

        common.USAGE.add(SimpleNamespace(prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0),
                                         cost=usage.get("cost", 0.0)), time.time() - t0, self._tag)

    def generate(self, messages, **kw):
        t0 = time.time(); out = _retry_transient(self._inner.generate, messages, **kw); self._record(t0); return out

    def generate_many(self, messages, *, n=1, **kw):
        t0 = time.time(); out = _retry_transient(self._inner.generate_many, messages, n=n, **kw); self._record(t0); return out

    async def generate_async(self, messages, **kw):
        t0 = time.time(); out = await self._inner.generate_async(messages, **kw); self._record(t0); return out

    def __getattr__(self, name):
        return getattr(self._inner, name)


def make_client(*, max_new_tokens: int, thinking: bool = False, effort: str = "low", temperature: float = 1.0, tag: str = "ideagent"):
    """(client, gen_kwargs) for one IDEAgent role, routed to OpenRouter with the project model."""
    e = common.env()
    client = build_client(model_id=e["model"], api_key_env="OPENROUTER_API_KEY", request_timeout=600, base_url=e["base_url"])
    gen_kwargs = {"max_new_tokens": max_new_tokens, "enable_thinking": thinking, "thinking_effort": effort,
                  "temperature": temperature, "top_p": 0.95}
    return TrackedClient(client, tag), gen_kwargs


# ----------------------------------------------------------------------------- post-hoc evaluation (Sec. 5)
def external_quality(idea_texts: list[str], client, gen_kwargs, *, topic_id: str = "topic", workers: int = 6) -> dict[int, dict[str, int]]:
    """Per-idea 0–9 scores on the five quality rubrics (Tables 6–10) using the repo's evaluator."""
    ev = QualityEvaluator(client=client, gen_kwargs=gen_kwargs, max_workers=workers)
    report = ev.evaluate(topic_id=topic_id, ideas=[{"idx": i, "text": t} for i, t in enumerate(idea_texts)])
    out: dict[int, dict[str, int]] = {i: {} for i in range(len(idea_texts))}
    for sc in (report.scores if report else []):
        out[sc.idea_idx][sc.metric] = sc.score
    return out


def pairwise_diversity(idea_texts: list[str], client, gen_kwargs, *, topic_id: str = "topic", workers: int = 6):
    """Eight-axis pairwise distinctness D_ij ∈ {0..9} (Table 4 / Table 11) via the repo's evaluator.
    Returns (GroupReport, {(i,j): score})."""
    ev = TopicalDiversityEvaluator(client=client, gen_kwargs=gen_kwargs, max_workers=workers, axis_call_mode="joint_axes")
    report = ev.evaluate(topic_id=topic_id, ideas=[{"idx": i, "idea_text": t} for i, t in enumerate(idea_texts)])
    pairs = {(min(p.idea_i, p.idea_j), max(p.idea_i, p.idea_j)): p.score for p in (report.pairwise_scores if report else [])}
    return report, pairs


# ----------------------------------------------------------------------------- Stateless baseline (Sec. 6.2)
def stateless_baseline(background: str, B: int, client, gen_kwargs, workers: int = 4) -> list[str]:
    """B ideas generated independently and in parallel with no knowledge of one another."""
    def one(_):
        ag = IdeatorAgent(role="ideator", client=client, gen_kwargs=gen_kwargs)
        return ag.open(background=background, prior_cores_block=None, critic_opening_challenge=op_free_baseline([]))

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(one, range(B)))


# ----------------------------------------------------------------------------- Sequential-Memory baseline (Sec. 6.2)
def sequential_memory_baseline(
    *, input_jsonl: str | Path, topic_idx: int, B: int, client, gen_kwargs, steno_client,
    steno_gen_kwargs, out_dir: str | Path, max_background_tokens: int | None = 12000,
    min_idea_chars: int = 200, signature_char_cap: int = 240,
) -> list[str]:
    """Sequential-Memory (SM): B ideas, one generator call each, carrying forward the compact
    signatures σ(i) of every earlier idea (Sec. 6.2). Runs the repo's own
    ``run_sequential_memory_baseline`` on a single topic slice, so the prompt lineage
    (``IDEATOR_SYSTEM_PROMPT`` + ``op_free_baseline``) is byte-identical to the paper's."""
    from ideagent.sequential_memory_baseline import (
        SequentialMemoryBaselineConfig,
        run_sequential_memory_baseline,
    )

    out_dir = Path(out_dir)
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = SequentialMemoryBaselineConfig(
        n_ideas=B, resume=True, init_topic_idx=topic_idx, end_topic_idx=topic_idx + 1,
        max_background_tokens=max_background_tokens, min_idea_chars=min_idea_chars,
        signature_char_cap=signature_char_cap,
    )
    records = run_sequential_memory_baseline(
        input_jsonl=str(input_jsonl), output_dir=out_dir, generator=client, gen_kwargs=gen_kwargs,
        config=cfg, steno_client=steno_client, steno_gen_kwargs=steno_gen_kwargs,
    )
    return [item["idea_text"] for rec in records for item in rec["items"]]


# ----------------------------------------------------------------------------- One-Shot baseline (Sec. 6.2)
def one_shot_baseline(background: str, B: int, client, gen_kwargs, *, min_idea_chars: int = 200,
                      retries: int = 1) -> tuple[list[str], str]:
    """One-Shot (OS): all B ideas in ONE generator call, using the repo's own single-shot directive
    and ``minItems == maxItems == B`` JSON schema (``baselines/simple/pipeline.py``). Returns
    (ideas, note); an unusable batch response yields an empty list, which is itself the paper's
    finding for this baseline (Table 1: One-Shot Yield 0.000)."""
    from baselines.simple.pipeline import single_shot_directive, split_single_shot_response
    from ideagent.agent_prompts import IDEATOR_SYSTEM_PROMPT, build_ideator_opening_user_message
    from ideagent.single_shot_baseline import single_shot_response_format

    messages = [
        {"role": "system", "content": IDEATOR_SYSTEM_PROMPT},
        {"role": "user", "content": build_ideator_opening_user_message(
            background, None, single_shot_directive(B))},
    ]
    raw, note = "", ""
    for attempt in range(retries + 1):
        use_schema = attempt == 0
        try:
            kw = dict(gen_kwargs)
            if use_schema:
                kw["response_format"] = single_shot_response_format(B)
            raw = client.generate(messages, **kw)
        except Exception as exc:  # noqa: BLE001  (schema unsupported / gateway error)
            note = f"generate failed ({type(exc).__name__}: {str(exc)[:120]})"
            continue
        try:
            return split_single_shot_response(raw, n_ideas=B, min_idea_chars=min_idea_chars), "schema-parsed" if use_schema else "reparsed"
        except ValueError as exc:
            note = str(exc)[:160]
    try:  # salvage a partial batch rather than throwing the whole call away
        data = common.extract_json(raw)
        ideas = [str(i.get("idea_text", "")).strip() for i in (data or {}).get("ideas", [])]
        ideas = [i for i in ideas if len(i) >= min_idea_chars]
        return ideas, f"salvaged {len(ideas)}/{B} ({note})"
    except Exception:  # noqa: BLE001
        return [], f"unusable ({note})"


# ----------------------------------------------------------------------------- concurrent topic searches
def run_topics_parallel(jobs: list[dict], *, workers: int = 2) -> dict[str, tuple]:
    """Run several ``GenerationLoop.run_topic`` searches at once (one thread per topic).

    ``jobs`` = [{"topic_id", "loop", "background", "out_dir"}]. The search *inside* one topic stays
    strictly sequential (eq. 3); only the independent topics overlap. Per-candidate progress lines
    are prefixed with the topic id and serialised behind a lock, and rich colouring is disabled for
    the duration because rich renders through IPython's display machinery, which must not be driven
    from worker threads. Returns {topic_id: (Archive, seconds)}."""
    from ideagent import console as _console
    from ideagent import generation_loop as _gl

    orig_print, orig_console = _gl.print_candidate_result, _console.Console
    tl, lock = threading.local(), threading.Lock()

    def tagged(**kw):
        tag = getattr(tl, "tag", "")
        if tag:
            kw["step"] = f"{tag} {kw.get('step', '')}"
        with lock:
            orig_print(**kw)

    def one(job: dict):
        tl.tag = job["topic_id"]
        out = Path(job["out_dir"])
        out.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        arch = job["loop"].run_topic(
            topic_id=job["topic_id"], background=job["background"], out_dir=out)
        return job["topic_id"], arch, time.time() - t0

    _gl.print_candidate_result = tagged
    _console.Console = None       # console.rich_available() -> False: plain, thread-safe print()
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(one, jobs))
    finally:
        _gl.print_candidate_result = orig_print
        _console.Console = orig_console
    return {tid: (arch, secs) for tid, arch, secs in results}


# ----------------------------------------------------------------------------- Table 1 / Fig. 2 views
QUALITY_METRICS = ("nonobviousness", "soundness", "mechanism_clarity_specificity", "feasibility", "significance")


def score_idea_set(name: str, topic_id: str, ideas: list[str], qc, qkw, jc, jkw, *, workers: int = 4) -> dict:
    """Post-hoc evaluation of one method's idea set for one topic (Sec. 5): five 0–9 quality
    rubrics per idea and the eight-axis pairwise distinctness D_ij."""
    q = external_quality(ideas, qc, qkw, topic_id=f"{topic_id}-{name}", workers=workers) if ideas else {}
    rep, pairs = (
        pairwise_diversity(ideas, jc, jkw, topic_id=f"{topic_id}-{name}", workers=workers)
        if len(ideas) > 1 else (None, {})
    )
    return {"method": name, "topic_id": topic_id, "n": len(ideas), "quality": q, "pairs": pairs,
            "avg_pairwise": (rep.avg_pairwise_score if rep is not None else float("nan")),
            "ideas": ideas}


def _vec(res: dict, metric: str) -> list[float]:
    return [res["quality"].get(i, {}).get(metric, 0) for i in range(res["n"])]


def topic_yield(res: dict, *, k: float, l: float, m: float, tau: int) -> int:
    """Yield(NB ≥ k, S ≥ l, C ≥ m, D ≥ τ) for one method on one topic (Alg. 2)."""
    if res["n"] == 0:
        return 0
    if res["n"] == 1:
        q = res["quality"].get(0, {})
        return int(q.get("nonobviousness", 0) >= k and q.get("soundness", 0) >= l
                   and q.get("mechanism_clarity_specificity", 0) >= m)
    return yield_count(_vec(res, "nonobviousness"), _vec(res, "soundness"),
                       _vec(res, "mechanism_clarity_specificity"), res["pairs"],
                       k=k, l=l, m=m, tau=tau)[0]


def table1(results: dict[str, list[dict]], costs: dict[str, float], *, ks=(7, 6), l: float = 7,
           m: float = 6, tau: int = 7, phis=(1, 2)) -> list[dict]:
    """The paper's Table 1 for the methods evaluated here: Yield at two non-obviousness gates,
    successful-topic counts at Φ, the five quality rubrics, pairwise diversity, and CST (eq. 7)."""
    rows: list[dict] = []
    methods = list(results)
    ys = {mm: {k: [topic_yield(r, k=k, l=l, m=m, tau=tau) for r in results[mm]] for k in ks} for mm in methods}
    n_topics = max((len(results[mm]) for mm in methods), default=0)
    for k in ks:
        rows.append({"metric": f"Yield(NB≥{k}, gate)", **{mm: round(float(np.mean(ys[mm][k])), 3) for mm in methods}})
    for k in ks:
        for phi in phis:
            rows.append({"metric": f"Successful topics Yield(NB≥{k})≥{phi}",
                         **{mm: f"{sum(y >= phi for y in ys[mm][k])}/{n_topics}" for mm in methods}})
    labels = {"nonobviousness": "Non-obviousness", "soundness": "Soundness",
              "mechanism_clarity_specificity": "Mechanism clarity", "feasibility": "Feasibility",
              "significance": "Significance"}
    for metric, label in labels.items():
        rows.append({"metric": label, **{
            mm: (round(float(np.mean([v for r in results[mm] for v in _vec(r, metric)])), 3)
                 if any(r["n"] for r in results[mm]) else float("nan")) for mm in methods}})
    rows.append({"metric": "Pairwise diversity", **{
        mm: round(float(np.nanmean([r["avg_pairwise"] for r in results[mm]])), 3)
        if any(not np.isnan(r["avg_pairwise"]) for r in results[mm]) else float("nan") for mm in methods}})
    rows.append({"metric": "Ideas returned (total)", **{mm: sum(r["n"] for r in results[mm]) for mm in methods}})
    rows.append({"metric": "Generation cost $", **{mm: round(costs.get(mm, float("nan")), 4) for mm in methods}})
    for k in ks:
        for phi in phis:
            rows.append({"metric": f"CST(NB≥{k}, Φ={phi}) $", **{
                mm: (lambda c: "NA" if c is None else round(c, 4))(cst([costs.get(mm, 0.0)], ys[mm][k], phi))
                for mm in methods}})
    return rows


def yield_surface_by_method(results: dict[str, list[dict]], *, k_values, l_values, m: float = 6,
                            tau: int = 7) -> dict[str, np.ndarray]:
    """Mean Yield surface over topics for each method (paper Fig. 2 / Fig. 4)."""
    out: dict[str, np.ndarray] = {}
    for method, res_list in results.items():
        grids = []
        for res in res_list:
            grids.append(np.array([[topic_yield(res, k=k, l=l, m=m, tau=tau) for k in k_values]
                                   for l in l_values], dtype=float))
        out[method] = np.mean(grids, axis=0) if grids else np.zeros((len(list(l_values)), len(list(k_values))))
    return out


# ----------------------------------------------------------------------------- diagrams
def stage_flow_diagram(thresholds=None, *, figsize=(13.5, 6.2)):
    """Fig. 1 (left) as a flow chart: Stage I generate & assess → Stage II route/repair →
    Stage III refine, with the gate G (eq. 4) and the four routing cases."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(0, 104); ax.set_ylim(0, 62); ax.axis("off")

    def box(x, y, w, h, text, fc, fs=8):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.6", fc=fc, ec="#37474f", lw=1.0))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, zorder=3)
        return (x, y, w, h)

    def arrow(a, b, *, side="right", label="", color="#455a64", style="-|>"):
        if side == "right":
            xy0, xy1 = (a[0] + a[2], a[1] + a[3] / 2), (b[0], b[1] + b[3] / 2)
        else:
            xy0, xy1 = (a[0] + a[2] / 2, a[1]), (b[0] + b[2] / 2, b[1] + b[3])
        ax.add_patch(FancyArrowPatch(xy0, xy1, arrowstyle=style, mutation_scale=11, color=color,
                                     lw=1.1, connectionstyle="arc3,rad=0.0"))
        if label:
            ax.text((xy0[0] + xy1[0]) / 2, (xy0[1] + xy1[1]) / 2 + 1.2, label, ha="center",
                    fontsize=7, color=color)

    t = thresholds
    tau = (f"thresholds: NB≥{t.nb_min}, S≥{t.soundness_floor:.0f}, C≥{t.clarity_min}, D≥{t.diversity_D}"
           if t is not None else "thresholds: NB≥60, S≥60, C≥60, D≥60")
    ax.text(0, 60, "Stage I · generate and assess", fontsize=10, weight="bold", color="#1565c0")
    ax.text(34, 60, "Stage II · route and repair", fontsize=10, weight="bold", color="#ef6c00")
    ax.text(74, 60, "Stage III · refine accepted", fontsize=10, weight="bold", color="#2e7d32")

    seed = box(1, 47, 26, 7, "seed $I_b^{(0)}$ ← Ideator(X, A, H, R)\nop_free / op_pivot", "#e3f2fd")
    steno = box(1, 37, 26, 6.5, "Stenographer  σ(I)=(p,m,v,a,e)   eq. (1)", "#e3f2fd")
    evals = box(1, 22, 26, 12,
                "Quality: NB$_I$, C$_I$, F$_I$ ∈ [0,100]\n"
                "Soundness panel: $S_I=\\frac{100}{9M}\\sum_j S_I^j$  eq. (2)\n"
                "Diversity judge: $D_I$ ∈ [0,100] + duplicates", "#e3f2fd")
    gate = box(1, 10, 26, 8, "gate  $G(I)=\\mathbb{1}[N \\geq \\tau_N \\wedge S \\geq \\tau_S \\wedge "
                             "C \\geq \\tau_C \\wedge \\neg$invalid$ \\wedge \\neg$disputed$]$\neq. (4)\n" + tau, "#fff8e1")

    c1 = box(34, 48, 30, 6, "case 1 · historical / multi-active duplicate → reject", "#ffebee", 7.5)
    c2 = box(34, 39.5, 30, 6.5, "case 2 · exactly one active duplicate →\nreplace if $Q_b$ higher, else reject", "#fff3e0", 7.5)
    c3 = box(34, 31, 30, 6, "case 3 · $D_I<\\tau_D$ → reject (not distinct)", "#ffebee", 7.5)
    c4 = box(34, 22.5, 30, 6.5, "case 4 · $G=1$ and $D_I\\geq\\tau_D$ →\naccept into A ($Q_b$ eq. (5))", "#e8f5e9", 7.5)
    rep = box(34, 11, 30, 8.5, "within δ=20 of τ and not invalid →\nCritic challenge → Ideator repair\n(same lineage, ≤1 attempt)", "#fff8e1", 7.5)
    stores = box(34, 1.5, 30, 7, "stores: A active · Q repair · H historical · R rejected patterns", "#eceff1", 7.5)

    polish = box(70, 40, 29, 8, "soft targets $N<90$, $S<80$, $C<80$\n→ Critic → same-lineage child", "#e8f5e9", 7.5)
    blind = box(70, 27, 29, 9.5, "child replaces parent iff\n$G=1$, $D\\geq\\tau_D$ (foreign), $Q_b$ ↑, and\nblinded NB comparison ×2 (positions swapped)", "#e8f5e9", 7.5)
    nxt = box(70, 12, 29, 7, "$I_b^{(0)} \\to$ [Repair] $\\to$ [Refine] $\\to I_{b+1}^{(0)}$\neq. (3): next seed, b ← b+1", "#e3f2fd", 7.5)

    arrow(seed, steno, side="down"); arrow(steno, evals, side="down"); arrow(evals, gate, side="down")
    arrow(gate, stores, side="right")
    for c in (c1, c2, c3, c4, rep):
        ax.add_patch(FancyArrowPatch((27.5, 14), (33.5, c[1] + c[3] / 2), arrowstyle="-|>",
                                     mutation_scale=10, color="#90a4ae", lw=0.9,
                                     connectionstyle="arc3,rad=-0.18"))
    arrow(c4, polish, side="right", label="accepted")
    arrow(polish, blind, side="down")
    arrow(blind, nxt, side="down")
    ax.plot([102, 102, 14, 14], [18.5, 57.5, 57.5, 55.5], color="#1565c0", lw=1.1, zorder=1)
    ax.add_patch(FancyArrowPatch((14, 56.5), (14, 54), arrowstyle="-|>", mutation_scale=11,
                                 color="#1565c0", lw=1.1))
    ax.text(49, 58.2, "next seed b ← b+1  (discovery budget B)", fontsize=7.5, color="#1565c0", ha="center")
    plt.tight_layout()
    return fig


OUTCOME_COLORS = {
    "accepted": "#2e7d32", "replaced": "#43a047", "repair_queued": "#f9a825",
    "repair_retained": "#fbc02d", "keep_accepted": "#78909c", "qualified_retired": "#b0bec5",
    "reject_duplicate": "#ef6c00", "reject_unsound": "#c62828", "reject_eval_fail": "#6a1b9a",
}


def lineage_graph(paths: list[str | Path], titles: list[str] | None = None, *, figsize=(14, 5.2)):
    """Fig. 1 (right): the evolution of the ideas of one run. Nodes are the candidates written to
    ``candidates_<topic>.jsonl`` (x = search step, y = lineage), edges are parent → child
    (repair / refinement), colour = the archive outcome, label = NB score."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    runs = [[json.loads(line) for line in Path(p).read_text().splitlines() if line.strip()] for p in paths]
    fig, axes = plt.subplots(1, len(runs), figsize=figsize, squeeze=False)
    seen: list[str] = []
    for ax, rows, title in zip(axes[0], runs, titles or [str(p) for p in paths]):
        lineages: list[str] = []
        for r in rows:
            if r["lineage_id"] not in lineages:
                lineages.append(r["lineage_id"])
        pos = {r["id"]: (i, lineages.index(r["lineage_id"])) for i, r in enumerate(rows)}
        for r in rows:
            if r.get("parent_id") in pos:
                (x0, y0), (x1, y1) = pos[r["parent_id"]], pos[r["id"]]
                ax.annotate("", xy=(x1, y1), xytext=(x0, y0),
                            arrowprops=dict(arrowstyle="-|>", color="#90a4ae", lw=1.1,
                                            shrinkA=11, shrinkB=11,
                                            connectionstyle="arc3,rad=0.16"))
        for r in rows:
            x, y = pos[r["id"]]
            colour = OUTCOME_COLORS.get(r["outcome"], "#607d8b")
            if r["outcome"] not in seen:
                seen.append(r["outcome"])
            ax.scatter([x], [y], s=460, color=colour, zorder=3, edgecolors="white", linewidths=1.4)
            ax.text(x, y, str(r["non_obviousness"]), ha="center", va="center", color="white",
                    fontsize=7.5, zorder=4, weight="bold")
            ax.text(x, y + 0.30, r["id"], ha="center", va="bottom", fontsize=6.2, color="#37474f")
            ax.text(x, y - 0.30, r["operator"], ha="center", va="top", fontsize=6.2, color="#78909c")
        ax.set_yticks(range(len(lineages))); ax.set_yticklabels(lineages, fontsize=7)
        ax.set_xticks(range(len(rows))); ax.set_xticklabels([str(i + 1) for i in range(len(rows))], fontsize=7)
        ax.set_xlabel("search step (order in candidates_*.jsonl)", fontsize=8)
        ax.set_ylabel("lineage $\\ell_I$", fontsize=8)
        ax.set_ylim(-0.8, len(lineages) - 0.2); ax.set_xlim(-0.7, len(rows) - 0.3)
        ax.set_title(title, fontsize=9)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
    fig.legend(handles=[Line2D([], [], marker="o", ls="", color=OUTCOME_COLORS.get(o, "#607d8b"), label=o)
                        for o in seen], loc="lower center", ncol=min(5, max(1, len(seen))), fontsize=7.5,
               frameon=False, bbox_to_anchor=(0.5, -0.06))
    plt.tight_layout()
    return fig
