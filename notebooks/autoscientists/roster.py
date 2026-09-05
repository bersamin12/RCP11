"""Self-organised team formation (paper Alg. 2, App. A.3) — the deterministic parts.

Agents post directions/rankings/critiques to a DISCUSSION-TRIGGER thread and vote
[DISCUSS-MORE] / [DISCUSS-DONE]. When a majority has voted DONE, the *alphabetically-last
analyst that participated* consolidates the proposals into a roster
R = {(T_k, axis_k, members_k)} and writes it to S. Reformation may create, merge, split,
retire or rebalance teams; structural changes need endorsement from affected teams.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Discussion:
    trigger_post: str
    participants: list[str] = field(default_factory=list)
    votes: dict[str, str] = field(default_factory=dict)     # agent -> "MORE" | "DONE"
    contributions: list[dict] = field(default_factory=list)

    def contribute(self, agent: str, post: dict, vote: str) -> None:
        assert vote in ("MORE", "DONE")
        if agent not in self.participants:
            self.participants.append(agent)
        self.contributions.append({"agent": agent, **post})
        self.votes[agent] = vote

    def done(self, n_agents: int) -> bool:
        """Majority of the crew has voted DISCUSS-DONE."""
        return sum(v == "DONE" for v in self.votes.values()) > n_agents / 2

    def consolidator(self, analysts: list[str]) -> str | None:
        """Alphabetically-last analyst who participated (a pure tie-break, A.3)."""
        eligible = sorted(a for a in self.participants if a in analysts)
        return eligible[-1] if eligible else None


def validate_roster(teams: dict[str, dict], experiment_agents: list[str], analysts: list[str]) -> list[str]:
    """Every working agent in exactly one team; each team has an axis and ≥1 experiment agent."""
    problems = []
    seen: dict[str, str] = {}
    for name, t in teams.items():
        if not t.get("axis"):
            problems.append(f"team {name} has no research axis")
        if not any(m in experiment_agents for m in t.get("members", [])):
            problems.append(f"team {name} has no experiment agent")
        for m in t.get("members", []):
            if m in seen:
                problems.append(f"{m} assigned to both {seen[m]} and {name}")
            seen[m] = name
    for a in experiment_agents + analysts:
        if a not in seen:
            problems.append(f"{a} is not on any team")
    return problems


def apply_reform(teams: dict[str, dict], ops: list[dict], endorsements: dict[str, set[str]] | None = None) -> dict[str, dict]:
    """Apply create/merge/split/retire/rebalance operations to a roster copy.

    ``endorsements`` maps op index -> set of teams that endorsed it; merge/split/retire of a team
    require that team's endorsement (A.3 "changes requiring endorsement from affected teams").
    """
    teams = {k: {**v, "members": list(v.get("members", []))} for k, v in teams.items()}
    endorsements = endorsements or {}
    for i, op in enumerate(ops):
        kind = op["op"]
        affected = op.get("teams") or ([op["team"]] if "team" in op else [])
        if kind in ("merge", "split", "retire"):
            missing = [t for t in affected if t not in endorsements.get(i, set())]
            if missing:
                raise PermissionError(f"op {i} ({kind}) lacks endorsement from {missing}")
        if kind == "create":
            teams[op["name"]] = {"axis": op["axis"], "members": list(op.get("members", [])), "hypothesis": op.get("hypothesis", "")}
        elif kind == "retire":
            teams.pop(op["team"])
        elif kind == "merge":
            members = [m for t in affected for m in teams[t]["members"]]
            for t in affected:
                teams.pop(t)
            teams[op["name"]] = {"axis": op["axis"], "members": members, "hypothesis": op.get("hypothesis", "")}
        elif kind == "split":
            src = teams.pop(op["team"])
            for part in op["into"]:
                teams[part["name"]] = {"axis": part["axis"], "members": list(part["members"]), "hypothesis": part.get("hypothesis", "")}
        elif kind == "rebalance":
            teams[op["from"]]["members"].remove(op["agent"])
            teams[op["to"]]["members"].append(op["agent"])
        else:
            raise ValueError(f"unknown op {kind}")
    return teams
