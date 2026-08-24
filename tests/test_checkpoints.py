import json
import sqlite3
from types import SimpleNamespace

from rcp.api.manager import RunManager
from rcp.config import get_settings
from rcp.graph.build import checkpoint_serializer
from rcp.graph.state import RCPState
from rcp.objects import (
    Hypothesis, PaperCard, ResearchFinding, ResearchGap, ResearchSynthesis, ResearchTopic,
)


def test_strict_checkpoint_serializer_round_trips_all_research_intelligence_types():
    state = RCPState(
        run_id="run-1", topic=ResearchTopic(title="Cooling"),
        paper_cards=[PaperCard(
            id="p1", title="Paper", abstract="Evidence", extraction_basis="abstract",
            findings=[ResearchFinding(
                id="p1:finding:1", paper_id="p1", statement="Energy decreased.", direction="decrease",
            )],
        )],
        research_synthesis=ResearchSynthesis(gaps=[ResearchGap(
            id="gap-1", category="scenario", statement="Conditions are unresolved.", paper_ids=["p1"],
        )]),
        hypotheses=[Hypothesis(id="H1", statement="Test cooling", model_names=["DataCenterRoom"])],
    )
    serializer = checkpoint_serializer()
    typed = serializer.dumps_typed(state)
    restored = serializer.loads_typed(typed)
    assert isinstance(restored, RCPState)
    assert restored.research_synthesis.gaps[0].id == "gap-1"
    assert restored.paper_cards[0].findings[0].paper_id == "p1"


class RecordingPool:
    def __init__(self):
        self.calls = []

    def submit(self, function, *args):
        self.calls.append((function, args))


class FakeGraph:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def get_state(self, config):
        run_id = config["configurable"]["thread_id"]
        value = self.snapshots.get(run_id, SimpleNamespace(values={}, next=()))
        if isinstance(value, Exception):
            raise value
        return value


def _meta(run_id: str, status: str | None = "running"):
    return {"run_id": run_id, "topic": "Cooling", "created_at": 1, "status": status}


def test_startup_reconciles_resumable_complete_missing_and_corrupt_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    runs = tmp_path / "data" / "runs"
    for run_id in ("resume", "waiting", "complete", "missing", "corrupt", "legacy"):
        directory = runs / run_id
        directory.mkdir(parents=True)
        status = None if run_id == "legacy" else "waiting_gate" if run_id == "waiting" else "running"
        (directory / "meta.json").write_text(json.dumps(_meta(run_id, status)))
    (runs / "complete" / "report.md").write_text("done")
    (runs / "legacy" / "report.md").write_text("legacy")
    valid = RCPState(run_id="resume", topic=ResearchTopic(title="Cooling")).model_dump()
    complete = RCPState(run_id="complete", topic=ResearchTopic(title="Cooling")).model_dump()
    waiting = RCPState(run_id="waiting", topic=ResearchTopic(title="Cooling")).model_dump()
    legacy = RCPState(run_id="legacy", topic=ResearchTopic(title="Cooling")).model_dump()
    graph = FakeGraph({
        "resume": SimpleNamespace(values=valid, next=("gap_mining",)),
        "waiting": SimpleNamespace(values=waiting, next=("select_hypothesis",)),
        "complete": SimpleNamespace(values=complete, next=()),
        "corrupt": sqlite3.DatabaseError("malformed database"),
        "legacy": SimpleNamespace(values=legacy, next=()),
    })
    pool = RecordingPool()
    manager = RunManager(graph=graph, pool=pool)

    assert manager.get("resume")["status"] == "resuming"
    assert manager.get("resume")["checkpoint_health"]["resumable"] is True
    assert pool.calls[0][1] == ("resume", None)
    assert manager.get("waiting")["status"] == "waiting_gate"
    assert len(pool.calls) == 1
    assert manager.get("complete")["status"] == "done"
    assert manager.get("missing")["status"] == "failed"
    assert manager.get("missing")["checkpoint_health"]["status"] == "missing"
    assert manager.get("corrupt")["status"] == "failed"
    assert manager.get("corrupt")["checkpoint_health"]["status"] == "corrupt"
    assert manager.get("legacy")["status"] == "done"


def test_incompatible_checkpoint_is_explicit_instead_of_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    pool = RecordingPool()
    graph = FakeGraph({"bad": SimpleNamespace(values={"run_id": "bad"}, next=("gap_mining",))})
    manager = RunManager(graph=graph, pool=pool)
    manager.runs["bad"] = _meta("bad")
    state, health, _ = manager.checkpoint_snapshot("bad", allow_empty=False)
    assert state == {}
    assert health.status == "incompatible"
    assert "supported schema" in health.detail


def test_the_checkpoint_allowlist_covers_every_type_reachable_from_state():
    """A type in RCPState but not in CHECKPOINT_TYPES fails deserialization.

    RunManager._load_existing turns that into a permanent failure for every
    in-flight run at the next restart, so drift must break CI, not production.
    """
    import typing

    from pydantic import BaseModel

    from rcp.graph.build import CHECKPOINT_TYPES

    def reachable(model: type[BaseModel], seen: set[type]) -> set[type]:
        if model in seen:
            return seen
        seen.add(model)
        for field in model.model_fields.values():
            for arg in _unwrap(field.annotation):
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    reachable(arg, seen)
        return seen

    def _unwrap(annotation) -> list:
        found = [annotation]
        for arg in typing.get_args(annotation):
            found.extend(_unwrap(arg))
        return found

    expected = reachable(RCPState, set())
    missing = expected - set(CHECKPOINT_TYPES)
    assert not missing, f"add these to CHECKPOINT_TYPES: {sorted(t.__name__ for t in missing)}"

    extra = set(CHECKPOINT_TYPES) - expected
    assert not extra, (
        "CHECKPOINT_TYPES should list exactly what is stored; remove: "
        f"{sorted(t.__name__ for t in extra)}"
    )


def test_a_version_one_checkpoint_still_loads_without_triage():
    """Any run checkpointed before the literature gate must still deserialize."""
    legacy = {
        "checkpoint_schema_version": 1,
        "run_id": "old-run",
        "topic": {"title": "Cooling"},
    }
    state = RCPState.model_validate(legacy)
    assert state.checkpoint_schema_version == 1
    # None means the gate never ran, which is distinct from having been skipped.
    assert state.literature_triage is None
    assert state.excluded_paper_ids == []
