from rcp.outcomes import derive_run_outcome


def test_outcome_uses_reviewed_claims_and_deterministic_comparisons():
    record = {
        "status": "done", "started_at": 10, "ended_at": 16,
        "token_usage": {"total_tokens": 42},
    }
    state = {
        "claim_bundle": {
            "claims": [{"statement": "Candidate reduced energy in the approved cases."}],
            "credibility_warnings": ["Exploratory model."],
        },
        "experiment_results": {
            "plan_id": "plan-1", "status": "ok", "cases": [], "warnings": [],
            "comparisons": [
                {"id": "c1", "pair_id": "p1", "metric": "energy", "baseline_case_id": "b1",
                 "candidate_case_id": "c1", "baseline_value": 10, "candidate_value": 8,
                 "absolute_delta": -2, "percent_delta": -20, "direction": "lower_is_better",
                 "candidate_better": True, "unit": "kWh"},
                {"id": "c2", "pair_id": "p2", "metric": "energy", "baseline_case_id": "b2",
                 "candidate_case_id": "c2", "baseline_value": 10, "candidate_value": 11,
                 "absolute_delta": 1, "percent_delta": 10, "direction": "lower_is_better",
                 "candidate_better": False, "unit": "kWh"},
            ],
            "quality_report": {"valid": True, "protocol_id": "v1", "protocol_sha256": "x", "checks": []},
        },
    }
    outcome = derive_run_outcome(record, state)
    assert outcome.primary_finding.startswith("Candidate reduced")
    assert outcome.quality_status == "qualified"
    assert outcome.metrics[0].wins == 1 and outcome.metrics[0].losses == 1
    assert outcome.metrics[0].median_percent_delta == -5
    assert outcome.elapsed_seconds == 6


def test_outcome_explains_incomplete_runs_without_inventing_findings():
    outcome = derive_run_outcome({"status": "waiting_gate"}, {})
    assert outcome.quality_status == "pending"
    assert "will appear" in outcome.primary_finding
    assert "human decision" in outcome.next_action
