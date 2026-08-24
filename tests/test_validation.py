from rcp.graph.state import RCPState
from rcp.objects import Claim, ClaimBundle, ExperimentSpec, Hypothesis, ResearchTopic, ResultBundle
from rcp.simulation.validation import runtime_plausibility_warnings, validate_model


def test_offline_model_validation_covers_required_physics_cases():
    report = validate_model("DataCenterRoom")
    ids = {case.id for case in report.reference_cases}
    assert report.status == "conceptual"
    assert report.checks_status == "passed"
    assert ids == {
        "energy-balance", "analytic-equilibrium", "cooling-saturation", "low-load",
        "repeatability", "units", "parameter-sensitivity",
    }
    assert all(case.status == "passed" for case in report.reference_cases)
    assert "publication-strength" in report.disclosure


def test_runtime_plausibility_warns_on_assessed_range_and_outputs():
    spec = ExperimentSpec(
        id="outside", hypothesis_id="h", model_name="DataCenterRoom",
        parameters={"Q_it": 200000}, outputs=["T", "E_cool"],
    )
    warnings = runtime_plausibility_warnings(
        spec,
        {"T": [27.0, 50.0], "E_cool": [0.0, 10.0, 5.0], "P_cool": [1.0, -1.0]},
    )
    joined = " ".join(warnings)
    assert "conceptual lumped-parameter" in joined
    assert "outside the assessed operating range" in joined
    assert "Temperature output" in joined
    assert "energy decreases" in joined
    assert "negative values" in joined


def test_unvalidated_results_gate_claim_wording_and_confidence(monkeypatch):
    from rcp.graph import nodes

    monkeypatch.setattr(
        nodes, "llm_json",
        lambda *args, **kwargs: ClaimBundle(
            hypothesis_id="h", claims=[Claim(statement="This proves the controller is optimal.", evidence="T=27", confidence="high")]
        ),
    )
    state = RCPState(
        run_id="r", topic=ResearchTopic(title="topic"),
        selected_hypothesis=Hypothesis(id="h", statement="hypothesis"),
        result_bundle=ResultBundle(
            spec_id="s", status="ok", metrics={"T_peak_degC": 27}, validation_status="conceptual",
            warnings=["Exploratory only."],
        ),
    )
    result = nodes.analyze_results(state)["claim_bundle"]
    claim = result.claims[0]
    assert "exploratory model" in claim.statement
    assert "proves" not in claim.statement
    assert claim.confidence == "medium"
    assert claim.evidence_ids == ["metric:T_peak_degC"]
    assert result.credibility_warnings == ["Exploratory only."]
