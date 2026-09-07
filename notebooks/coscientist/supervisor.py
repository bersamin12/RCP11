"""Supervisor agent — research plan configuration, system statistics, weighted agent sampling,
and the asynchronous task-execution loop of Supplementary Note 8.

  "A dedicated Supervisor agent manages the worker task queue, assigns specialized agents to these
   processes, and allocates resources." ... "Periodically, the Supervisor agent calculates a
   comprehensive set of summary statistics, reflecting the system's state and progress ... Based on
   these statistics, the Supervisor agent then orchestrates subsequent system operations ... by
   strategically weighting and sampling the specialized agents for execution via the worker
   processes."  (Methods, Overview of Co-Scientist architecture)

The statistics, the weighting rule and the queue are pure Python and can be exercised without any
model call (``DryRunAgents``); ``LiveAgents`` wires the same loop to the real agents.
"""
from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import common

from . import evolution, generation, metareview, proximity, ranking, reflection
from .literature import search_many
from .state import Hypothesis, Match, Memory, ResearchPlan, Task, TaskQueue

AGENTS = ["generation", "reflection", "ranking", "proximity", "evolution", "metareview"]


# --------------------------------------------------------------------------- research plan config
PLAN_PROMPT = """You are the Supervisor agent of an AI co-scientist. Parse the scientist's natural-language research goal into a research plan configuration that will guide every downstream agent.

Scientist research goal:
{goal}

Return JSON:
{{"preferences": ["what the scientist wants emphasised, e.g. novelty, mechanism detail, deployability"],
  "attributes": ["the desired attributes of a proposal, e.g. Novelty, Feasibility"],
  "constraints": ["hard constraints the output must satisfy, taken from the goal"],
  "idea_attributes": "a short adjective phrase used inside other agents' prompts, e.g. 'novel and feasible'",
  "evaluation_criteria": ["the criteria the auto-evaluation and tournament debates should apply"],
  "notes": "one or two sentences of guidance for the generation agents"}}"""


def parse_research_plan(goal: str) -> ResearchPlan:
    obj = common.chat_json(PLAN_PROMPT.format(goal=goal),
                           "You configure a multi-agent scientific discovery system.",
                           tag="sup.plan", max_tokens=1200,
                           validate=lambda o: o["preferences"] and o["constraints"])
    prefs = [str(p) for p in obj["preferences"]] + [str(c) for c in obj.get("evaluation_criteria", [])]
    return ResearchPlan(goal=goal, preferences=prefs,
                        attributes=[str(a) for a in obj.get("attributes", [])],
                        constraints=[str(c) for c in obj["constraints"]],
                        idea_attributes=str(obj.get("idea_attributes", "novel and feasible")),
                        notes=str(obj.get("notes", "")))


# --------------------------------------------------------------------------- statistics & weights
@dataclass
class SupervisorConfig:
    max_ideas: int = 16
    target_matches_per_idea: float = 3.0
    slots_per_round: int = 4          # worker processes filled per round
    min_sampled: int = 2              # the Supervisor always samples this many agents per round
    matches_per_round: int = 6
    evolve_top_n: int = 3
    metareview_period: int = 2
    stall_tol: float = 8.0            # Elo gain below this counts as "quality stopped improving"
    workers: int = 4


@dataclass
class SystemStatistics:
    round: int = 0
    n_hypotheses: int = 0
    n_active: int = 0
    n_unreviewed: int = 0
    n_in_tournament: int = 0
    matches_per_idea: float = 0.0
    top_elo: float = 1200.0
    mean_elo: float = 1200.0
    top_elo_gain: float = 0.0
    rounds_since_metareview: int = 99
    missing_edges: int = 0
    gen_win_rate: float = 0.0
    evo_win_rate: float = 0.0

    def row(self) -> dict:
        return {"round": self.round, "hyps": self.n_hypotheses, "active": self.n_active,
                "unreviewed": self.n_unreviewed, "in tournament": self.n_in_tournament,
                "matches/idea": round(self.matches_per_idea, 2), "top Elo": round(self.top_elo, 1),
                "ΔtopElo": round(self.top_elo_gain, 1), "missing edges": self.missing_edges,
                "since meta": self.rounds_since_metareview,
                "evo win%": round(100 * self.evo_win_rate), "gen win%": round(100 * self.gen_win_rate)}


def compute_stats(memory: Memory, rnd: int, last_metareview: int, prev_top: float) -> SystemStatistics:
    active = memory.active()
    ids = [h.hid for h in active]
    in_t = [h for h in active if h.hid in memory.elo.ratings]
    played = sum(memory.elo.games.get(h, 0) for h in ids)
    ratings = [memory.elo.rating(h) for h in ids] or [1200.0]
    wins = {"evo": [0, 0], "gen": [0, 0]}
    for m in memory.matches:
        for hid in (m.a, m.b):
            if hid not in memory.hypotheses:
                continue
            key = "evo" if memory.get(hid).strategy.startswith("evo") else "gen"
            wins[key][1] += 1
            wins[key][0] += int(m.winner == hid)
    n_pairs = len(ids) * (len(ids) - 1) // 2
    return SystemStatistics(
        round=rnd,
        n_hypotheses=len(memory.hypotheses),
        n_active=len(active),
        n_unreviewed=sum(1 for h in active if h.status == "new"),
        n_in_tournament=len(in_t),
        matches_per_idea=(played / len(ids)) if ids else 0.0,
        top_elo=max(ratings), mean_elo=sum(ratings) / len(ratings),
        top_elo_gain=max(ratings) - prev_top,
        rounds_since_metareview=min(99, rnd - last_metareview),
        missing_edges=max(0, n_pairs - len(memory.proximity)),
        gen_win_rate=(wins["gen"][0] / wins["gen"][1]) if wins["gen"][1] else 0.0,
        evo_win_rate=(wins["evo"][0] / wins["evo"][1]) if wins["evo"][1] else 0.0,
    )


def agent_weights(s: SystemStatistics, cfg: SupervisorConfig) -> dict[str, float]:
    """Turn the statistics into sampling weights for the specialised agents.

    Encodes DecideNextSteps of Supplementary Note 8 as a soft policy rather than a hard if-chain:
      * reflection scales with the unreviewed backlog (nothing enters the tournament unreviewed);
      * ranking scales with the deficit of matches per idea ("keep the tournament running");
      * generation decays as the population approaches MaxIdeas;
      * evolution turns on when the top Elo has stopped improving ("if scores are stable, try to
        improve top ideas") and is boosted when evolved ideas are winning their matches;
      * proximity turns on when the graph is stale (missing edges);
      * meta-review fires periodically ("if enough time has passed").
    """
    room = max(0.0, 1.0 - s.n_hypotheses / max(1, cfg.max_ideas))
    deficit = max(0.0, 1.0 - s.matches_per_idea / cfg.target_matches_per_idea)
    stalled = 1.0 if (s.round > 0 and s.top_elo_gain < cfg.stall_tol) else 0.0
    w = {
        "generation": 0.15 + 1.8 * room,
        "reflection": 0.05 + 1.5 * min(1.0, s.n_unreviewed / 3.0),
        "ranking": 0.20 + 2.0 * deficit,
        "proximity": 0.05 + 1.2 * min(1.0, s.missing_edges / 6.0),
        "evolution": 0.10 + 1.4 * stalled * (0.6 + s.evo_win_rate) * (1.0 if s.n_in_tournament >= 2 else 0.0),
        "metareview": 1.2 if s.rounds_since_metareview >= cfg.metareview_period and s.n_active >= 2 else 0.05,
    }
    return {k: round(v, 3) for k, v in w.items()}


def sample_agents(weights: dict[str, float], n: int, rng: random.Random) -> list[str]:
    names, ws = list(weights), [max(1e-6, weights[k]) for k in weights]
    return rng.choices(names, weights=ws, k=n)


# --------------------------------------------------------------------------- task results
@dataclass
class TaskResult:
    kind: str                       # NewHypothesisCreated | ReviewCompleted | TournamentBatch | ...
    targets: list[str] = field(default_factory=list)
    info: str = ""


DEFAULT_ACTION = {
    "generation": "GenerateHypothesis",
    "reflection": "ReviewHypothesis",
    "ranking": "RunTournamentBatch",
    "proximity": "UpdateProximityGraph",
    "evolution": "EvolveTopHypotheses",
    "metareview": "GenerateSystemFeedback",
}


# --------------------------------------------------------------------------- the loop
class Supervisor:
    def __init__(self, memory: Memory, plan: ResearchPlan, agents, cfg: SupervisorConfig | None = None,
                 seed: int = 0, verbose: bool = True):
        self.memory, self.plan, self.agents = memory, plan, agents
        self.cfg = cfg or SupervisorConfig()
        self.queue = TaskQueue()
        self.rng = random.Random(seed)
        self.round = 0
        self.last_metareview = -self.cfg.metareview_period
        self.prev_top = 1200.0
        self.log: list[dict] = []
        self.verbose = verbose

    # -- ManageFollowUpTasks (Supp. Note 8)
    def manage_followups(self, res: TaskResult) -> None:
        if res.kind == "NewHypothesisCreated":
            for t in res.targets:
                self.queue.push("reflection", "ReviewHypothesis", t, priority=1, created_round=self.round)
        elif res.kind == "ReviewCompleted":
            for t in res.targets:
                self.queue.push("ranking", "AddToTournament", t, priority=2, created_round=self.round)

    # -- DecideNextSteps (Supp. Note 8) via weighted agent sampling
    def fill_queue(self, stats: SystemStatistics) -> list[str]:
        weights = agent_weights(stats, self.cfg)
        # DecideNextSteps opens with an unconditional "keep the tournament running to refine scores"
        if stats.n_in_tournament >= 2 and not any(
                t.agent == "ranking" and t.action == "RunTournamentBatch" for t in self.queue.pending()):
            self.queue.push("ranking", "RunTournamentBatch", priority=4, created_round=self.round)
        capacity = max(0, 2 * self.cfg.slots_per_round - len(self.queue))
        need = min(capacity, max(self.cfg.min_sampled, self.cfg.slots_per_round - len(self.queue)))
        sampled = sample_agents(weights, need, self.rng) if need else []
        for a in sampled:
            self.queue.push(a, DEFAULT_ACTION[a], priority=5, created_round=self.round)
        return sampled

    def step(self) -> dict:
        stats = compute_stats(self.memory, self.round, self.last_metareview, self.prev_top)
        weights = agent_weights(stats, self.cfg)
        sampled = self.fill_queue(stats)
        # AddToTournament is O(1) bookkeeping (Supp. Note 8) and does not occupy a worker slot
        batch, cheap = [], []
        while len(batch) < self.cfg.slots_per_round:
            t = self.queue.pop()
            if t is None:
                break
            (cheap if t.action == "AddToTournament" else batch).append(t)
        for t in cheap:
            self.agents.execute(self, t)
            self.queue.completed.append(t)
        if self.verbose and batch:
            print(f"round {self.round}: running {[t.label() for t in batch]}")

        def run(t: Task):
            try:
                return t, self.agents.execute(self, t)
            except Exception as exc:                      # a failing worker must not kill the loop
                return t, TaskResult("Failed", [], f"{type(exc).__name__}: {exc}")

        with ThreadPoolExecutor(max_workers=self.cfg.workers) as ex:
            done = list(ex.map(run, batch))
        for t, res in done:
            self.queue.completed.append(t)
            if res.kind == "Failed" and self.verbose:
                print(f"  ! {t.label()} failed: {res.info[:200]}")
            self.manage_followups(res)
            if t.agent == "metareview" and res.kind != "Failed":
                self.last_metareview = self.round
        self.prev_top = stats.top_elo
        rec = {**stats.row(), "weights": weights, "sampled": sampled,
               "executed": [t.label() for t in batch] + [f"·{t.label()}" for t in cheap],
               "queue after": self.queue.counts(), "queue len": len(self.queue)}
        self.log.append(rec)
        self.round += 1
        return rec

    def run(self, rounds: int) -> list[dict]:
        for _ in range(rounds):
            self.step()
        return self.log


# --------------------------------------------------------------------------- dry-run agents (no LLM)
class DryRunAgents:
    """Deterministic stand-ins used to exercise the queue/statistics/weighting logic without spending
    any model calls. They mutate the same Memory/Elo objects the live agents use."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def _fake(self, sup: Supervisor, strategy: str) -> Hypothesis:
        m = sup.memory
        h = Hypothesis(hid=m.new_id(), title=f"synthetic idea ({strategy})", category="synthetic",
                       summary="", statement="", rationale="", experiment="", strategy=strategy,
                       round=sup.round)
        return m.add(h)

    def execute(self, sup: Supervisor, t: Task) -> TaskResult:
        m = sup.memory
        if t.agent == "generation":
            hs = [self._fake(sup, "literature"), self._fake(sup, "debate")] if t.action == "CreateInitialHypotheses" \
                else [self._fake(sup, self.rng.choice(["literature", "debate", "assumptions", "expansion"]))]
            return TaskResult("NewHypothesisCreated", [h.hid for h in hs])
        if t.agent == "reflection":
            targets = [t.target] if t.target else [h.hid for h in m.active() if h.status == "new"][:1]
            out = []
            for hid in targets:
                if hid is None or hid not in m.hypotheses:
                    continue
                if self.rng.random() < 0.2:
                    m.get(hid).status, m.get(hid).reject_reason = "rejected", "synthetic reject"
                else:
                    m.get(hid).status = "reviewed"
                    out.append(hid)
            return TaskResult("ReviewCompleted", out)
        if t.agent == "ranking":
            if t.action == "AddToTournament" and t.target:
                m.elo.add(t.target)
                return TaskResult("AddedToTournament", [t.target])
            hyps = [h for h in m.active() if h.status == "reviewed"]
            for h in hyps:
                m.elo.add(h.hid)
            pairs = ranking.choose_pairs(m, hyps, sup.cfg.matches_per_round, sup.round, self.rng)
            for a, b in pairs:
                w, l = (a, b) if self.rng.random() < 0.5 + 0.05 * (m.get(a).strategy.startswith("evo")) else (b, a)
                m.elo.update(w, l)
                m.matches.append(Match(a, b, w, "dry-run", "", 1, sup.round))
            m.elo.snapshot(f"round {sup.round}")
            return TaskResult("TournamentBatch", [], f"{len(pairs)} matches")
        if t.agent == "proximity":
            ids = [h.hid for h in m.active()]
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    m.proximity.setdefault((a, b), round(self.rng.random(), 2))
            return TaskResult("ProximityUpdated", [])
        if t.agent == "evolution":
            top = [h for h, _ in m.elo.top(sup.cfg.evolve_top_n, among=[x.hid for x in m.active()])]
            if not top:
                return TaskResult("NoOp", [], "no ranked hypotheses yet")
            hs = [self._fake(sup, "evo:combination")]
            for h in hs:
                h.parents = top[:2]
            return TaskResult("NewHypothesisCreated", [h.hid for h in hs])
        if t.agent == "metareview":
            m.feedback = f"(synthetic meta-review after round {sup.round})"
            return TaskResult("FeedbackUpdated", [])
        return TaskResult("NoOp", [])


# --------------------------------------------------------------------------- live agents
class LiveAgents:
    """Wires the Supervisor's task actions to the real Generation/Reflection/Ranking/Proximity/
    Evolution/Meta-review agents. Every action here makes real model calls."""

    def __init__(self, quick: bool = False, debate_turns: int = 3, gen_debate_turns: int = 3,
                 n_articles: int = 4, verbose: bool = True):
        self.quick = quick
        self.debate_turns = debate_turns
        self.gen_debate_turns = gen_debate_turns
        self.n_articles = n_articles
        self.verbose = verbose
        self._strategies = ["literature", "debate", "assumptions", "expansion"]
        self._i = 0

    def execute(self, sup: Supervisor, t: Task) -> TaskResult:
        m, plan, rnd = sup.memory, sup.plan, sup.round
        if t.agent == "generation":
            strat = t.payload.get("strategy") or self._strategies[self._i % len(self._strategies)]
            self._i += 1
            if strat == "literature":
                qs = generation.search_queries(plan, 2, m)
                arts = search_many(qs, limit=2)
                m.articles += [{"title": a.title, "year": a.year, "source": a.source} for a in arts]
                h = generation.from_literature(m, plan, arts[:self.n_articles], rnd=rnd)
            elif strat == "debate":
                h, _ = generation.simulated_debate(m, plan, max_turns=self.gen_debate_turns, rnd=rnd,
                                                   reviews_overview=m.feedback[:1500])
            elif strat == "assumptions":
                chain = generation.assumption_hops(plan, m, hops=1 if self.quick else 2, n=3)
                h = generation.from_assumptions(m, plan, chain, rnd=rnd)
            else:
                h, _ = generation.research_expansion(m, plan, rnd=rnd)
            return TaskResult("NewHypothesisCreated", [h.hid], strat)

        if t.agent == "reflection":
            pending = [h for h in m.active() if h.status == "new"]
            targets = [m.get(t.target)] if (t.target and t.target in m.hypotheses) else pending[:2]
            targets = [h for h in targets if h.status == "new"]
            if not targets:
                return TaskResult("NoOp", [], "nothing to review")
            reflection.screen(m, plan, targets, full=not self.quick)
            return TaskResult("ReviewCompleted", [h.hid for h in targets if h.status == "reviewed"])

        if t.agent == "ranking":
            if t.action == "AddToTournament" and t.target:
                added = m.elo.add(t.target)
                return TaskResult("AddedToTournament", [t.target], "added" if added else "already present")
            ms = ranking.run_round(m, plan, n_matches=sup.cfg.matches_per_round, current_round=rnd,
                                   top_k=3, debate_turns=self.debate_turns, workers=sup.cfg.workers,
                                   verbose=self.verbose)
            return TaskResult("TournamentBatch", [], f"{len(ms)} matches")

        if t.agent == "proximity":
            proximity.build_graph(m, plan, workers=6)
            return TaskResult("ProximityUpdated", [], f"{len(m.proximity)} edges")

        if t.agent == "evolution":
            strategies = ["combination", "simplification"] if self.quick else \
                ["inspiration", "combination", "simplification", "out-of-the-box"]
            hs = evolution.evolve_top(m, plan, top_n=sup.cfg.evolve_top_n, rnd=rnd,
                                      strategies=[self._pick(strategies, rnd)], workers=2)
            return TaskResult("NewHypothesisCreated", [h.hid for h in hs])

        if t.agent == "metareview":
            if t.action == "GenerateFinalResearchOverview":
                metareview.research_overview(m, plan)
                return TaskResult("OverviewGenerated", [])
            metareview.synthesize(m, plan)
            return TaskResult("FeedbackUpdated", [], f"{len(m.feedback)} chars")
        return TaskResult("NoOp", [])

    @staticmethod
    def _pick(strategies: list[str], rnd: int) -> str:
        return strategies[rnd % len(strategies)]
