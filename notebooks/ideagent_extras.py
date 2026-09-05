"""Pieces of the IDEAgent paper that the public repository does not ship, plus thin wrappers.

* ``yield_count``            — Algorithm 2: Yield(NB ≥ k, S ≥ l, C ≥ m, D ≥ τ) via the vendored exact
                               maximum-clique routine (``ideagent.diversity_metrics._maximum_clique``).
* ``successful_topics``, ``cst`` — the successful-topic indicator and Cost per Successful Topic (eq. 7).
* ``greedy_maxmin_topics``   — Algorithm 1: greedy max–min topic selection over sentence embeddings.
* ``make_client``            — OpenRouter-backed role client through the patched ``build_client``.
* ``external_quality``, ``pairwise_diversity`` — the paper's post-hoc evaluation protocol (Sec. 5) run
                               with the repo's own ``QualityEvaluator`` / ``TopicalDiversityEvaluator``.
* ``stateless_baseline``     — the Stateless baseline (Sec. 6.2): B independent Ideator calls.
"""
from __future__ import annotations

import sys
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
class TrackedClient:
    """Delegating wrapper that records every call of a vendored IDEAgent client in ``common.USAGE``."""

    def __init__(self, inner, tag: str):
        self._inner, self._tag = inner, tag

    def _record(self, t0: float) -> None:
        meta = self._inner.get_last_response_metadata() or {}
        usage = meta.get("usage") or {}
        from types import SimpleNamespace

        common.USAGE.add(SimpleNamespace(prompt_tokens=usage.get("prompt_tokens", 0), completion_tokens=usage.get("completion_tokens", 0),
                                         cost=usage.get("cost", 0.0)), time.time() - t0, self._tag)

    def generate(self, messages, **kw):
        t0 = time.time(); out = self._inner.generate(messages, **kw); self._record(t0); return out

    def generate_many(self, messages, *, n=1, **kw):
        t0 = time.time(); out = self._inner.generate_many(messages, n=n, **kw); self._record(t0); return out

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
