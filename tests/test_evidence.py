"""Tests for evidence/provenance (X.3) and the comparator (M5.2)."""

from pathlib import Path

from rcp.evidence import check_claims, sha256_file, sha256_text, spec_digest
from rcp.objects import Claim, ExperimentSpec, ResultBundle
from rcp.simulation.collector import compare_bundles


def test_sha256_text_deterministic():
    assert sha256_text("abc") == sha256_text("abc")
    assert sha256_text("abc") != sha256_text("abd")


def test_sha256_file(tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("hello")
    assert sha256_file(p) == sha256_text("hello")


def _spec(**overrides) -> ExperimentSpec:
    base = dict(
        id="s1", hypothesis_id="H1", model_name="DataCenterRoom",
        parameters={"Q_it": 60000.0, "COP": 3.5}, outputs=["T"], stop_time=3600.0,
    )
    base.update(overrides)
    return ExperimentSpec(**base)


def test_spec_digest_order_independent():
    a = _spec(parameters={"Q_it": 60000.0, "COP": 3.5})
    b = _spec(parameters={"COP": 3.5, "Q_it": 60000.0})
    assert spec_digest(a) == spec_digest(b)
    assert spec_digest(a) != spec_digest(_spec(parameters={"Q_it": 60001.0, "COP": 3.5}))


def test_check_claims_catches_missing_and_untraceable():
    metrics = {"T_peak_degC": 27.0, "E_cool_kWh": 4.5}
    claims = [
        Claim(statement="ok", metric_keys=["T_peak_degC"]),
        Claim(statement="missing", metric_keys=["PUE"]),
        Claim(statement="untraceable"),
    ]
    warnings = check_claims(claims, metrics)
    assert any("missing metric 'PUE'" in w for w in warnings)
    assert any("cites no metrics" in w for w in warnings)
    assert not any("ok" in w for w in warnings)


def test_check_claims_empty_when_all_valid():
    metrics = {"T_peak_degC": 27.0}
    assert check_claims([Claim(statement="x", metric_keys=["T_peak_degC"])], metrics) == []


def _bundle(metrics: dict) -> ResultBundle:
    return ResultBundle(spec_id="s", status="ok", metrics=metrics)


def test_compare_bundles_deltas():
    base = _bundle({"T_peak_degC": 27.0, "E_cool_kWh": 10.0})
    cand = _bundle({"T_peak_degC": 26.0, "E_cool_kWh": 11.0})
    rows = compare_bundles(base, cand)
    assert rows["T_peak_degC"]["delta"] == -1.0
    assert rows["E_cool_kWh"]["delta"] == 1.0
    assert rows["E_cool_kWh"]["delta_pct"] == 10.0


def test_compare_bundles_handles_missing_metric():
    base = _bundle({"T_peak_degC": 27.0})
    cand = _bundle({"E_cool_kWh": 10.0})
    rows = compare_bundles(base, cand)
    assert rows["T_peak_degC"]["delta"] is None
    assert rows["E_cool_kWh"]["candidate"] == 10.0
