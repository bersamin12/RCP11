"""Run manager: executes workflow runs in background threads, tracks progress,
surfaces gate payloads, and accepts gate answers."""

import json
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langgraph.types import Command

from rcp.config import data_dir
from rcp.graph.build import build_graph
from rcp.graph.state import RCPState
from rcp.llm import capture_llm_usage
from rcp.objects import (
    ExperimentPlan,
    ExperimentResultSet,
    CheckpointHealth,
    ProtocolChanges,
    ResearchLineage,
    ResearchLineageItem,
    ResearchReview,
    ResearchTopic,
    ThesisIdea,
    ThesisProfile,
)
from rcp.provenance import write_manifest
from rcp.revisions import prepare_reanalysis_successor

NODE_ORDER = [
    "research_memory_build", "literature_triage", "gap_mining", "hypothesis_gen",
    "select_hypothesis", "spec_compile", "approve_spec", "run_modelica", "handle_run_failure",
    "analyze_results", "review_evidence", "draft_report",
]
GATE_NODES = {
    "literature_triage": "literature_triage",
    "hypothesis_selection": "select_hypothesis", "spec_approval": "approve_spec",
    "rollback_decision": "handle_run_failure",
}
ENTRY_NODES = {
    "research": "research_memory_build", "hypothesis": "hypothesis_gen",
    "spec": "spec_compile", "reanalysis": "analyze_results",
}


class CheckpointError(ValueError):
    pass


class RunManager:
    def __init__(self, graph=None, pool=None):
        self.graph = graph or build_graph()
        self.pool = pool or ThreadPoolExecutor(max_workers=4)
        self.lock = threading.Lock()
        self.runs: dict[str, dict[str, Any]] = {}
        self._load_existing()

    # ---------- lifecycle ----------

    def _run_dir(self, run_id: str):
        return data_dir() / "runs" / run_id

    def _load_existing(self) -> None:
        runs_root = data_dir() / "runs"
        if not runs_root.exists():
            return
        for d in sorted(runs_root.iterdir()):
            meta = d / "meta.json"
            if not meta.exists():
                continue
            try:
                rec = json.loads(meta.read_text())
            except (ValueError, OSError):
                continue
            if not rec.get("status"):
                rec["status"] = "done" if (d / "report.md").exists() else "stale"
            rec.setdefault("current_node", None)
            rec.setdefault("node_history", [])
            rec.setdefault("gate", None)
            rec.setdefault("error", "")
            rec.setdefault("version", 0)
            rec.setdefault("started_at", rec.get("created_at"))
            rec.setdefault("ended_at", None)
            rec.setdefault("auto", False)
            rec.setdefault("constraints", [])
            rec.setdefault("token_usage", {})
            rec.setdefault("archived_at", rec.get("created_at") if rec.get("status") == "stale" else None)
            rec.setdefault("retry_count", 0)
            rec.setdefault("retryable", False)
            rec.setdefault("entry_point", "research")
            rec.setdefault("root_run_id", rec["run_id"])
            rec.setdefault("parent_run_id", None)
            rec.setdefault("iteration", 0)
            rec.setdefault("revision_decision", None)
            rec.setdefault("revision_feedback", "")
            rec.setdefault("review", None)
            rec.setdefault("review_pending", False)
            rec.setdefault("checkpoint_health", None)
            self.runs[rec["run_id"]] = rec
        for run_id, rec in list(self.runs.items()):
            _state, health, next_nodes = self.checkpoint_snapshot(run_id, allow_empty=False)
            rec["checkpoint_health"] = health.model_dump(mode="json")
            active = rec["status"] in {"running", "resuming", "waiting_gate"}
            if active and health.status != "ok":
                rec.update({
                    "status": "failed", "current_node": None, "retryable": False,
                    "ended_at": time.time(),
                    "error": f"Checkpoint {health.status}: {health.detail}",
                })
                rec["version"] += 1
                self._persist(rec)
                continue
            if rec["status"] in {"running", "resuming"}:
                if next_nodes:
                    rec["status"] = "resuming"
                    rec["checkpoint_health"] = health.model_copy(update={"resumable": True}).model_dump(mode="json")
                    self._persist(rec)
                    self.pool.submit(self._worker, run_id, None)
                elif (self._run_dir(run_id) / "report.md").exists():
                    rec.update({"status": "done", "current_node": None, "retryable": False})
                    rec["ended_at"] = rec.get("ended_at") or time.time()
                    rec["version"] += 1
                    self._persist(rec)
                else:
                    rec.update({
                        "status": "failed", "current_node": None, "retryable": False,
                        "ended_at": time.time(),
                        "error": "Checkpoint completed without the required report artifact.",
                    })
                    rec["version"] += 1
                    self._persist(rec)

    def create(
        self, topic: str, constraints: list[str], auto: bool,
        thesis_idea: ThesisIdea | None = None, thesis_profile: ThesisProfile | None = None,
        memory_snapshot: str = "",
    ) -> str:
        run_id = uuid.uuid4().hex[:8]
        state = RCPState(
            run_id=run_id,
            topic=ResearchTopic(title=topic, constraints=constraints),
            auto=auto,
            thesis_idea=thesis_idea,
            thesis_profile=thesis_profile,
            memory_snapshot=memory_snapshot,
        )
        self._launch(run_id, state)
        return run_id

    def _launch(
        self, run_id: str, state: RCPState, *, root_run_id: str | None = None,
        parent_run_id: str | None = None, iteration: int = 0,
        revision_decision: str | None = None, revision_feedback: str = "",
    ) -> None:
        rec = {
            "run_id": run_id, "topic": state.topic.title,
            "constraints": state.topic.constraints, "auto": state.auto,
            "status": "running", "current_node": ENTRY_NODES[state.entry_point], "node_history": [],
            "gate": None, "error": "", "created_at": time.time(),
            "started_at": time.time(), "ended_at": None, "version": 0,
            "thesis_idea": state.thesis_idea.model_dump() if state.thesis_idea else None,
            "thesis_profile": state.thesis_profile.model_dump() if state.thesis_profile else None,
            "memory_snapshot": state.memory_snapshot,
            "token_usage": {},
            "archived_at": None, "retry_count": 0, "retryable": False,
            "entry_point": state.entry_point,
            "root_run_id": root_run_id or run_id, "parent_run_id": parent_run_id,
            "iteration": iteration, "revision_decision": revision_decision,
            "revision_feedback": revision_feedback, "review": None,
            "review_pending": False,
            "checkpoint_health": CheckpointHealth(
                status="empty", detail="The worker has not persisted its first checkpoint yet."
            ).model_dump(mode="json"),
        }
        with self.lock:
            self.runs[run_id] = rec
        d = self._run_dir(run_id)
        d.mkdir(parents=True, exist_ok=True)
        self._persist(rec)
        self.pool.submit(self._worker, run_id, state)

    def answer_gate(self, run_id: str, answer: str | dict) -> None:
        with self.lock:
            rec = self.runs[run_id]
            if rec["status"] != "waiting_gate":
                raise ValueError(f"run {run_id} is not waiting at a gate")
            rec["gate"] = None
            rec["status"] = "running"
            rec["version"] += 1
            self._persist(rec)
        self.pool.submit(self._worker, run_id, Command(resume=answer))

    # ---------- worker ----------

    def _persist(self, rec: dict[str, Any]) -> None:
        destination = self._run_dir(rec["run_id"]) / "meta.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(rec, indent=2))
        temporary.replace(destination)

    def _bump(self, run_id: str, **updates) -> None:
        with self.lock:
            rec = self.runs[run_id]
            rec.update(updates)
            rec["version"] += 1
            self._persist(rec)

    def _worker(self, run_id: str, graph_input) -> None:
        config = {"configurable": {"thread_id": run_id}}
        try:
            with capture_llm_usage(lambda usage: self._add_token_usage(run_id, usage)):
                for update in self.graph.stream(graph_input, config, stream_mode="updates"):
                    if "__interrupt__" in update:
                        payload = update["__interrupt__"][0].value
                        # An unknown gate used to be labelled "select_hypothesis",
                        # which pointed the stepper at the wrong node and made the
                        # run unanswerable. Hold position instead of guessing.
                        gate_name = payload.get("gate", "")
                        node = GATE_NODES.get(gate_name) or self.get(run_id).get("current_node") or NODE_ORDER[0]
                        self._bump(run_id, status="waiting_gate", gate=payload, current_node=node)
                        continue
                    node = next(iter(update))
                    with self.lock:
                        rec = self.runs[run_id]
                        rec["node_history"].append({"node": node, "at": time.time()})
                        done_idx = NODE_ORDER.index(node) if node in NODE_ORDER else -1
                        rec["current_node"] = (
                            NODE_ORDER[done_idx + 1] if 0 <= done_idx < len(NODE_ORDER) - 1 else node
                        )
                        rec["version"] += 1
                        self._persist(rec)
            snapshot = self.graph.get_state(config)
            if not snapshot.next:  # finished (not paused at a gate)
                _, checkpoint_health, _ = self.checkpoint_snapshot(run_id, allow_empty=False)
                self._bump(
                    run_id, status="done", ended_at=time.time(), current_node=None,
                    retryable=False,
                    checkpoint_health=checkpoint_health.model_dump(mode="json"),
                )
                self._refresh_manifest(run_id)
        except Exception as err:  # surface anything to the UI
            retryable = False
            try:
                snapshot = self.graph.get_state(config)
                retryable = bool(snapshot.next) and "run aborted" not in str(err).lower()
            except Exception:
                pass
            self._bump(
                run_id, status="failed", error=str(err)[:2000], ended_at=time.time(),
                retryable=retryable,
            )
            self._refresh_manifest(run_id)

    def _add_token_usage(self, run_id: str, usage: dict[str, int]) -> None:
        with self.lock:
            rec = self.runs[run_id]
            totals = rec.setdefault("token_usage", {})
            for name, value in usage.items():
                totals[name] = int(totals.get(name, 0)) + int(value)
            self._persist(rec)

    def _refresh_manifest(self, run_id: str) -> None:
        with self.lock:
            rec = dict(self.runs[run_id])
        timings: dict[str, float] = {}
        previous = float(rec.get("started_at") or rec.get("created_at") or time.time())
        for item in rec.get("node_history", []):
            ended = float(item.get("at") or previous)
            node = str(item.get("node") or "unknown")
            timings[node] = timings.get(node, 0.0) + max(0.0, ended - previous)
            previous = ended
        write_manifest(
            run_id, timings_seconds=timings,
            token_usage=rec.get("token_usage") or {},
            lineage={
                "root_run_id": rec.get("root_run_id"),
                "parent_run_id": rec.get("parent_run_id"),
                "iteration": rec.get("iteration", 0),
                "revision_decision": rec.get("revision_decision"),
            },
        )

    # ---------- queries ----------

    def list_runs(self) -> list[dict]:
        with self.lock:
            rows = [dict(r) for r in self.runs.values()]
        return sorted(rows, key=lambda r: r.get("created_at") or 0, reverse=True)

    def get(self, run_id: str) -> dict:
        with self.lock:
            if run_id not in self.runs:
                raise KeyError(run_id)
            return dict(self.runs[run_id])

    def set_archived(self, run_id: str, archived: bool) -> dict:
        with self.lock:
            rec = self.runs[run_id]
            if rec["status"] in {"running", "resuming", "waiting_gate"}:
                raise ValueError("only terminal runs can be archived")
            rec["archived_at"] = time.time() if archived else None
            rec["version"] += 1
            self._persist(rec)
            return dict(rec)

    def retry(self, run_id: str) -> dict:
        with self.lock:
            rec = self.runs[run_id]
            if rec["status"] != "failed":
                raise ValueError("only failed runs can be retried")
            if not rec.get("retryable"):
                raise ValueError("this failure has no resumable checkpoint")
            rec.update({
                "status": "resuming", "error": "", "ended_at": None,
                "current_node": rec.get("current_node") or NODE_ORDER[0],
                "retry_count": int(rec.get("retry_count") or 0) + 1,
                "retryable": False, "archived_at": None,
            })
            rec["version"] += 1
            self._persist(rec)
            result = dict(rec)
        self.pool.submit(self._worker, run_id, None)
        return result

    def checkpoint_snapshot(
        self, run_id: str, *, allow_empty: bool = True,
    ) -> tuple[dict, CheckpointHealth, tuple[str, ...]]:
        """Return validated state plus an explicit checkpoint-health classification."""
        config = {"configurable": {"thread_id": run_id}}
        try:
            snapshot = self.graph.get_state(config)
            values = snapshot.values
            if not values:
                status = "empty" if allow_empty else "missing"
                detail = (
                    "The worker has not persisted its first checkpoint yet."
                    if allow_empty else "No checkpoint state exists for this recorded run."
                )
                return {}, CheckpointHealth(status=status, detail=detail), ()
            try:
                state = RCPState.model_validate(values).model_dump(mode="json")
            except Exception as err:
                return {}, CheckpointHealth(
                    status="incompatible",
                    detail=f"Stored workflow state does not match the supported schema: {str(err)[:500]}",
                ), tuple(snapshot.next)
            next_nodes = tuple(snapshot.next)
            return state, CheckpointHealth(
                status="ok", detail="Checkpoint state validated successfully.",
                resumable=bool(next_nodes), schema_version=int(state.get("checkpoint_schema_version", 1)),
            ), next_nodes
        except sqlite3.DatabaseError as err:
            return {}, CheckpointHealth(
                status="corrupt", detail=f"Checkpoint database could not be read: {str(err)[:500]}",
            ), ()
        except Exception as err:
            return {}, CheckpointHealth(
                status="incompatible", detail=f"Checkpoint could not be deserialized: {str(err)[:500]}",
            ), ()

    def state_snapshot(self, run_id: str) -> dict:
        state, health, _ = self.checkpoint_snapshot(run_id)
        if health.status not in {"ok", "empty"}:
            raise CheckpointError(health.detail)
        return state

    def checkpoint_store_health(self) -> CheckpointHealth:
        _, health, _ = self.checkpoint_snapshot("__rcp_healthcheck__", allow_empty=False)
        if health.status == "missing":
            return CheckpointHealth(status="ok", detail="Checkpoint database is readable.")
        return health

    # ---------- supervisor review and immutable successors ----------

    def review(
        self, run_id: str, decision: str, feedback: str, expected_version: int,
        protocol_changes: ProtocolChanges | None = None,
    ) -> ResearchReview:
        with self.lock:
            rec = self.runs[run_id]
            if rec["status"] != "done":
                raise ValueError("only completed runs can receive a supervisor review")
            if int(rec["version"]) != expected_version:
                raise ValueError(f"run version conflict: expected {expected_version}, current {rec['version']}")
            if rec.get("review") or rec.get("review_pending"):
                raise ValueError("this research cycle already has a final review decision")
            if decision not in {"accept", "reanalyse", "revise_plan", "refine_hypothesis"}:
                raise ValueError(f"unknown review decision: {decision}")
            if decision != "accept" and not feedback.strip():
                raise ValueError("revision feedback must not be empty")
            rec["review_pending"] = True
            rec["version"] += 1
            self._persist(rec)

        try:
            successor_id = None
            if decision != "accept":
                parent_state = RCPState.model_validate(self.state_snapshot(run_id))
                successor_id = uuid.uuid4().hex[:8]
                child = parent_state.model_copy(deep=True)
                child.run_id = successor_id
                child.parent_run_id = run_id
                child.auto = False
                child.revision_feedback = feedback.strip()
                child.report_path = ""
                child.claim_bundle = None
                child.review_bundle = None
                child.review_attempts = 0
                child.rollback_action = ""

                if decision == "refine_hypothesis":
                    child.entry_point = "hypothesis"
                    child.hypotheses = []
                    child.selected_hypothesis = None
                    child.experiment_spec = None
                    child.experiment_plan = None
                    child.spec_attempts = 0
                    child.spec_feedback = ""
                    child.spec_approved = False
                    child.result_bundle = None
                    child.experiment_results = None
                elif decision == "revise_plan":
                    child.entry_point = "spec"
                    child.experiment_spec = None
                    child.experiment_plan = None
                    child.spec_attempts = 0
                    child.spec_feedback = feedback.strip()
                    child.spec_approved = False
                    child.result_bundle = None
                    child.experiment_results = None
                else:
                    if not child.experiment_plan or not child.experiment_results:
                        raise ValueError("reanalysis requires an approved plan and result set")
                    plan, results = prepare_reanalysis_successor(
                        run_id, successor_id,
                        ExperimentPlan.model_validate(child.experiment_plan),
                        ExperimentResultSet.model_validate(child.experiment_results),
                        protocol_changes or ProtocolChanges(),
                        int(self.get(run_id).get("iteration", 0)) + 1,
                    )
                    child.entry_point = "reanalysis"
                    child.experiment_plan = plan
                    child.experiment_results = results
                    child.result_bundle = next((item for item in results.cases if item.status == "ok"), None)

                parent = self.get(run_id)
                self._launch(
                    successor_id, child,
                    root_run_id=str(parent.get("root_run_id") or run_id),
                    parent_run_id=run_id, iteration=int(parent.get("iteration", 0)) + 1,
                    revision_decision=decision, revision_feedback=feedback.strip(),
                )

            review = ResearchReview(
                decision=decision, feedback=feedback.strip(), parent_version=expected_version,
                protocol_changes=(protocol_changes or ProtocolChanges()).model_dump(exclude_none=True),
                successor_run_id=successor_id,
            )
            destination = self._run_dir(run_id) / "review.json"
            temporary = destination.with_suffix(".json.tmp")
            temporary.write_text(review.model_dump_json(indent=2))
            temporary.replace(destination)
            with self.lock:
                rec = self.runs[run_id]
                rec["review"] = review.model_dump(mode="json")
                rec["review_pending"] = False
                rec["version"] += 1
                self._persist(rec)
            self._refresh_manifest(run_id)
            return review
        except Exception:
            with self.lock:
                rec = self.runs[run_id]
                rec["review_pending"] = False
                rec["version"] += 1
                self._persist(rec)
            raise

    def lineage(self, run_id: str) -> ResearchLineage:
        with self.lock:
            if run_id not in self.runs:
                raise KeyError(run_id)
            chain = []
            cursor: str | None = run_id
            seen = set()
            while cursor:
                if cursor in seen or cursor not in self.runs:
                    raise ValueError("run lineage is incomplete or cyclic")
                seen.add(cursor)
                rec = self.runs[cursor]
                chain.append(ResearchLineageItem(
                    run_id=cursor, topic=rec["topic"], status=rec["status"],
                    iteration=int(rec.get("iteration", 0)),
                    parent_run_id=rec.get("parent_run_id"),
                    revision_decision=rec.get("revision_decision"),
                    review=ResearchReview.model_validate(rec["review"]) if rec.get("review") else None,
                ))
                cursor = rec.get("parent_run_id")
            chain.reverse()
            root = str(self.runs[run_id].get("root_run_id") or chain[0].run_id)
        return ResearchLineage(root_run_id=root, current_run_id=run_id, runs=chain)
