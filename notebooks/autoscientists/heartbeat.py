"""Heartbeat dispatch (paper Alg. 1) and the experiment / analyst cycles (Alg. 3 / Alg. 4).

``Crew.run_cycles`` executes the paper's loop for a fixed number of heartbeats: every cycle,
each agent wakes once, reads S, acts according to its role, writes back, and exits. Ablation
flags reproduce Sec. 4.5: ``no_analyst``, ``no_cross_agent``, ``no_self_org``, ``independent``.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import agents as llm
from .gate import NoiseFloor, promote
from .priors import axis_priors, coverage_audit, rank_queue
from .roster import Discussion
from .stagnation import check_stagnation
from .state import Experiment, SharedState, code_hash

TASK_DIR = Path(__file__).resolve().parent / "task"


def run_train(src: str, seed: int, workdir: Path) -> float:
    """Train a candidate script once and return its metric (subprocess, ~1 s)."""
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / f"cand_{code_hash(src)}.py"
    path.write_text(src)
    out = subprocess.run([sys.executable, str(path), "--seed", str(seed)], capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(out.stderr[-800:])
    return float(json.loads(out.stdout.strip().splitlines()[-1])["metric"])


@dataclass
class Flags:
    no_analyst: bool = False      # experiment agents propose for themselves
    no_cross_agent: bool = False  # only [PROPOSAL]/[RESULT] posts; no critique, no re-discussion
    no_self_org: bool = False     # roster fixed after bootstrap
    independent: bool = False     # no shared state at all: each agent keeps a private champion/log


@dataclass
class Crew:
    state: SharedState
    analysts: list[str]
    experiment_agents: list[str]
    noise: NoiseFloor
    flags: Flags = field(default_factory=Flags)
    seed_counter: int = 100
    max_discussion_rounds: int = 3    # each agent posts at most this many times per trigger
    cycle: int = 0
    log: list[str] = field(default_factory=list)
    private: dict = field(default_factory=dict)   # for the `independent` ablation

    # ------------------------------------------------------------------ helpers
    def _say(self, msg: str) -> None:
        self.log.append(f"[cycle {self.cycle}] {msg}")
        print(self.log[-1])

    def _next_seed(self) -> int:
        self.seed_counter += 1
        return self.seed_counter

    @property
    def crew(self) -> list[str]:
        """Fixed heartbeat rotation; analysts first so the queues are filled before experiment agents wake."""
        return ([] if self.flags.no_analyst else self.analysts) + self.experiment_agents

    # ------------------------------------------------------------------ Alg. 1 dispatch
    def heartbeat(self, agent: str) -> str:
        s = self.state
        roster = s.roster
        trigger = self._open_trigger()
        if trigger is not None or not roster["teams"]:
            if self.flags.no_self_org and roster["teams"]:
                return "no-self-org: ignoring trigger"
            return self.discussion_branch(agent, trigger)
        if s.team_of(agent) is None:
            return "no-team exit"
        if agent in self.analysts:
            return self.analyst_cycle(agent)
        return self.experiment_cycle(agent)

    def _open_trigger(self) -> dict | None:
        triggers = self.state.forum("[DISCUSSION-TRIGGER]")
        if not triggers:
            return None
        t = triggers[-1]
        return None if t["meta"].get("resolved") else t

    # ------------------------------------------------------------------ Alg. 2 discussion
    def discussion_branch(self, agent: str, trigger: dict | None) -> str:
        s = self.state
        if trigger is None:  # cold-start bootstrap: post the trigger
            tid = s.post("[DISCUSSION-TRIGGER]", "bootstrap", "Cold start: propose research directions and form teams.", reason="bootstrap")
            trigger = s.forum("[DISCUSSION-TRIGGER]")[-1]
        tid = trigger["id"]
        thread = [p for p in s.forum(thread=tid) if p["tag"] == "[DISCUSSION]"]
        n = len(self.crew)
        # Termination check first: if a majority has already voted DONE and *I* am the designated
        # consolidator (alphabetically-last participating analyst), write the roster now (A.3).
        disc = self._discussion(tid)
        if disc.done(n) and disc.consolidator(self.analysts or self.crew) == agent:
            return self._consolidate(agent, tid, disc, n)
        my_posts = [p for p in thread if p["author"] == agent]
        rnd = len(my_posts) + 1                      # this agent's discussion round
        if rnd > self.max_discussion_rounds:
            return "discussion round limit reached"
        if my_posts and not any(p["t"] > my_posts[-1]["t"] and p["author"] != agent for p in thread):
            return "waiting for other agents' posts"  # nothing new to react to yet
        exps = s.experiments()
        summary = f"{len(exps)} experiments, {sum(e['outcome']=='KEEP' for e in exps)} KEEPs; " + ", ".join(
            f"{e['axis']}:{e['outcome']}" for e in exps[-6:]) if exps else "no experiments yet"
        role = "analyst" if agent in self.analysts else "experiment agent"
        reply = llm.discuss(agent=agent, role=role, champion_src=s.champion_src, champion_metric=s.champion["metric"],
                            prior_posts=thread, experiments_summary=summary, trigger_reason=trigger["meta"].get("reason", ""),
                            round_no=rnd, max_rounds=self.max_discussion_rounds)
        body = json.dumps({k: reply[k] for k in ("directions", "ranking", "critique")}, indent=1)
        s.post("[DISCUSSION]", agent, body, thread=tid, vote=reply["vote"])
        s.post("[DISCUSS-DONE]" if reply["vote"] == "DONE" else "[DISCUSS-MORE]", agent, "", thread=tid)
        disc = self._discussion(tid)
        msg = f"{agent} (round {rnd}) posted directions, voted {reply['vote']} ({sum(v=='DONE' for v in disc.votes.values())}/{n} DONE)"
        if disc.done(n) and disc.consolidator(self.analysts or self.crew) == agent:
            msg += " → " + self._consolidate(agent, tid, disc, n)
        return msg

    def _consolidate(self, agent: str, tid: str, disc: Discussion, n: int) -> str:
        s = self.state
        roster = llm.consolidate_roster(agent=agent, posts=[p for p in s.forum(thread=tid) if p["tag"] == "[DISCUSSION]"],
                                        experiment_agents=self.experiment_agents,
                                        analysts=self.analysts if not self.flags.no_analyst else [])
        s.write_roster(roster["teams"], author=agent)
        self._resolve_trigger(tid)
        s.post("[TEAM-REFORMED]", agent, json.dumps(roster["teams"], indent=1), thread=tid)
        return f"{agent} consolidated the roster ({sum(v=='DONE' for v in disc.votes.values())}/{n} DONE) → teams {list(roster['teams'])}"

    def _discussion(self, tid: str) -> Discussion:
        d = Discussion(tid)
        for p in self.state.forum(thread=tid):
            if p["tag"] == "[DISCUSSION]":
                d.contribute(p["author"], {"body": p["body"]}, p["meta"]["vote"])
        return d

    def _resolve_trigger(self, tid: str) -> None:
        # mark resolved by appending a resolution marker post referencing the trigger
        posts = self.state._read_jsonl("logs/forum.jsonl")
        for p in posts:
            if p["id"] == tid:
                p["meta"]["resolved"] = True
        (self.state.root / "logs" / "forum.jsonl").write_text("".join(json.dumps(p) + "\n" for p in posts))

    # ------------------------------------------------------------------ Alg. 4 analyst
    def analyst_cycle(self, agent: str) -> str:
        s = self.state
        team = s.team_of(agent)
        exps = s.experiments()
        # line 1-2: stagnation check → DISCUSSION-TRIGGER
        if not self.flags.no_self_org and not self.flags.no_cross_agent and exps:
            fired = check_stagnation(exps, self.cycle)
            if fired and self.cycle > 2:
                s.post("[DISCUSSION-TRIGGER]", agent, f"Stagnation: {'; '.join(fired)}", reason="; ".join(fired))
                return f"{agent} detected stagnation ({fired[0]}) → posted [DISCUSSION-TRIGGER]"
        return self._propose(agent, team)

    def _propose(self, agent: str, team: str) -> str:
        s = self.state
        exps = s.experiments()
        champ = s.champion
        priors = axis_priors(exps, self.noise.sigma)
        coverage = coverage_audit(s.champion_src, exps)
        keeps = [e for e in exps if e["outcome"] == "KEEP"]
        tinfo = s.roster["teams"][team]
        out = llm.analyst_propose(
            agent=agent, team=team, hypothesis=tinfo.get("hypothesis", tinfo.get("axis", "")),
            champion_src=s.champion_src, champion_metric=champ["metric"], priors=priors, coverage=coverage,
            dead_ends=s.dead_ends(team) if self.flags.no_cross_agent else s.all_dead_ends(),
            recent_experiments=exps, last_keep=keeps[-1] if keeps else None, sigma=self.noise.sigma,
        )
        items = []
        # Cross-team dedup (Sec. 3.2 "share successes and failures to reduce redundant exploration"):
        # a proposal already pending or claimed in ANOTHER team's queue is not queued again.
        pending_elsewhere = set()
        for other in s.roster["teams"]:
            if other == team or not self.flags.no_cross_agent:
                pending_elsewhere |= {(it["axis"], it["direction"]) for it in s.queue(other).snapshot()["pending"]}
        for p in out["proposals"]:
            if (p["axis"], p["direction"]) in pending_elsewhere:
                s.post("[DISCUSSION]", agent, f"skipping duplicate proposal {p['axis']}/{p['direction']}: already queued", dedup=True)
                continue
            exp_id = f"e{uuid.uuid4().hex[:6]}"
            post_id = s.post("[PROPOSAL]", agent, f"{p['axis']} {p['direction']}: {p['change']} — {p['rationale']}", exp_id=exp_id, bold=p.get("bold", False))
            items.append({"exp_id": exp_id, "axis": p["axis"], "direction": p["direction"], "change": p["change"],
                          "proposer": agent, "post_id": post_id, "bold": p.get("bold", False), "priority": 0})
        if out.get("exempt_reason"):
            s.post("[EXEMPT]", agent, out["exempt_reason"])
        q = s.queue(team)
        q.append(items)
        ranked = rank_queue(q.snapshot()["pending"], priors)
        q.reorder([it["exp_id"] for it in ranked])
        return f"{agent} queued {[f'{i['axis']}/{i['direction']}' for i in items]} on {team}" + (" (EXEMPT)" if out.get("exempt_reason") else "")

    # ------------------------------------------------------------------ Alg. 3 experiment agent
    def experiment_cycle(self, agent: str) -> str:
        s = self.state
        team = s.team_of(agent)
        q = s.queue(team)
        item = q.claim(agent)
        if item is None:
            if self.flags.no_analyst:      # ablation: experiment agents propose for themselves
                self._propose(agent, team)
                item = q.claim(agent)
            if item is None:
                return f"{agent}: queue empty"
        champ = s.champion
        champ_src = s.champion_src
        try:
            src, diff = llm.experiment_apply(champ_src, item)
            seed = self._next_seed()
            metric = run_train(src, seed, s.root / "runs")
        except Exception as exc:  # invalid candidate
            q.release(item["exp_id"], agent, "INVALID")
            s.log_experiment(Experiment(item["exp_id"], team, agent, item["axis"], item["direction"], item["change"],
                                        champ["metric"], float("nan"), float("nan"), "INVALID", -1, self.cycle,
                                        parent_hash=champ["code_hash"], proposal_post=item["post_id"]))
            return f"{agent}: {item['axis']} INVALID ({str(exc)[:80]})"
        decision = promote(metric, champ["metric"], self.noise, confirm=lambda: run_train(src, self._next_seed(), s.root / "runs"))
        if decision.branch == "confirm":
            s.add_noise_pair(metric, decision.second_metric, code_hash(src))
            if self.noise.locked_sigma is not None and s.noise_pairs()["locked_sigma"] is None:
                s.lock_sigma(self.noise.locked_sigma)
        outcome = "KEEP" if decision.promote else ("NEAR-MISS" if decision.branch == "confirm" else "DISCARD")
        exp = Experiment(item["exp_id"], team, agent, item["axis"], item["direction"], item["change"], champ["metric"],
                         metric, decision.delta, outcome, seed, self.cycle, decision.second_metric,
                         champ["code_hash"], code_hash(src), item["post_id"])
        s.log_experiment(exp)
        q.release(item["exp_id"], agent, outcome)
        if decision.promote:
            s.promote(src, metric, seed, agent, item["exp_id"])
            s.post("[RESULT]", agent, f"KEEP {item['axis']} {item['direction']}: {decision.detail}\n{diff}", thread=item["post_id"], outcome=outcome, delta=decision.delta)
            s.post("[KEEP]", agent, item["change"], exp_id=item["exp_id"], delta=decision.delta)
        else:
            s.post("[NEAR-MISS]" if outcome == "NEAR-MISS" else "[RESULT]", agent,
                   f"{outcome} {item['axis']} {item['direction']}: {decision.detail}", thread=item["post_id"], outcome=outcome, delta=decision.delta)
            s.add_dead_end(team, item["axis"], item["direction"], item["change"], decision.delta, decision.detail)
        return f"{agent}: {item['axis']}/{item['direction']} metric={metric:.4f} Δ={decision.delta:+.4f} [{decision.branch}] → {outcome}"

    # ------------------------------------------------------------------ driver
    def run_cycles(self, n: int) -> None:
        for _ in range(n):
            self.cycle += 1
            for agent in self.crew:
                self._say(self.heartbeat(agent))
            # keep discussing (extra rounds within the same cycle) until a roster exists
            rounds = 0
            while (self._open_trigger() is not None or not self.state.roster["teams"]) and rounds < self.max_discussion_rounds + 1:
                rounds += 1
                for agent in self.crew:
                    self._say(self.heartbeat(agent))
