"""Tests for the simulation-failure rollback gate (PRD §5.4)."""

from rcp.graph.nodes import rollback_decision, route_after_rollback, route_after_sim
from rcp.graph.state import RCPState
from rcp.objects import ResearchTopic, ResultBundle


def _state(**overrides) -> RCPState:
    base = dict(run_id="r1", topic=ResearchTopic(title="t"))
    base.update(overrides)
    return RCPState(**base)


def test_route_after_sim_ok_goes_to_analysis():
    s = _state(result_bundle=ResultBundle(spec_id="s", status="ok"))
    assert route_after_sim(s) == "analyze"


def test_route_after_sim_failed_goes_to_rollback():
    s = _state(result_bundle=ResultBundle(spec_id="s", status="failed"))
    assert route_after_sim(s) == "rollback"


def test_route_after_rollback_actions():
    assert route_after_rollback(_state(rollback_action="retry")) == "run_modelica"
    assert route_after_rollback(_state(rollback_action="revise")) == "spec_compile"
    assert route_after_rollback(_state(rollback_action="abort")) == "draft_report"
    assert route_after_rollback(_state(rollback_action="")) == "draft_report"  # unknown -> abort


def test_rollback_decision_auto_aborts():
    s = _state(auto=True, result_bundle=ResultBundle(spec_id="s", status="failed"))
    assert rollback_decision(s) == {"rollback_action": "abort"}
