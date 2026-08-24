"""Tests for the simulation-failure rollback gate (PRD §5.4).

The gate is `handle_run_failure`; it routes on the whole ExperimentResultSet
rather than a single bundle, because "continue with partial evidence" is only
offered when at least one case actually succeeded.
"""

from rcp.graph.nodes import handle_run_failure, route_after_failure, route_after_run
from rcp.graph.state import RCPState
from rcp.objects import ExperimentResultSet, ResearchTopic, ResultBundle


def _state(**overrides) -> RCPState:
    base = dict(run_id="r1", topic=ResearchTopic(title="t"))
    base.update(overrides)
    return RCPState(**base)


def _results(*statuses) -> ExperimentResultSet:
    cases = [ResultBundle(spec_id=f"s{i}", status=s) for i, s in enumerate(statuses)]
    overall = "ok" if all(s == "ok" for s in statuses) else "partial"
    return ExperimentResultSet(plan_id="p1", status=overall, cases=cases)


def test_route_after_run_ok_goes_to_analysis():
    assert route_after_run(_state(experiment_results=_results("ok"))) == "analyze"


def test_route_after_run_failure_goes_to_gate():
    assert route_after_run(_state(experiment_results=_results("ok", "failed"))) == "failure"


def test_route_after_run_without_results_goes_to_gate():
    assert route_after_run(_state()) == "failure"


def test_route_after_failure_actions():
    assert route_after_failure(_state(rollback_action="continue")) == "analyze"
    assert route_after_failure(_state(rollback_action="revise")) == "revise"
    assert route_after_failure(_state(rollback_action="abort")) == "abort"
    assert route_after_failure(_state(rollback_action="")) == "abort"  # unknown -> abort


def test_handle_run_failure_auto_aborts():
    # `auto` must never invent a scientific outcome: it aborts rather than
    # silently continuing on partial evidence.
    state = _state(auto=True, experiment_results=_results("ok", "failed"))
    assert handle_run_failure(state) == {"rollback_action": "abort"}
