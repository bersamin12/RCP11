from pathlib import Path

from rcp.objects import ExperimentSpec
from rcp.simulation.collector import build_result_bundle, compute_metrics, load_series

CSV = '"time","T","P_cool","E_cool"\n0,27,0,0\n1800,25,5000,9000000\n3600,24,4000,16200000\n'


def _write_csv(tmp_path: Path) -> Path:
    p = tmp_path / "model_res.csv"
    p.write_text(CSV)
    return p


def test_load_series(tmp_path):
    series = load_series(_write_csv(tmp_path))
    assert series["T"] == [27.0, 25.0, 24.0]
    assert len(series["time"]) == 3


def test_compute_metrics(tmp_path):
    metrics = compute_metrics(load_series(_write_csv(tmp_path)))
    assert metrics["T_peak_degC"] == 27.0
    assert metrics["E_cool_kWh"] == 4.5  # 16.2e6 J / 3.6e6
    assert "T_avg_steady_degC" in metrics and "T_std_steady_degC" in metrics


def test_build_result_bundle_failure_path(tmp_path):
    spec = ExperimentSpec(id="s1", hypothesis_id="H1", model_name="DataCenterRoom")
    bundle = build_result_bundle(spec, tmp_path, None, "", error="boom")
    assert bundle.status == "failed"
    assert "boom" in bundle.log_excerpt
