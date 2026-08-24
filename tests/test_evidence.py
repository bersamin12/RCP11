"""Tests for evidence/provenance hashing and claim traceability (PRD X.3).

Matched-pair comparison lives in rcp.simulation.batch and is covered by
tests/test_batch.py; the deterministic claim gate (review_claims) is covered
there and in tests/test_annotations.py.
"""

from rcp.evidence import sha256_file, sha256_text, spec_digest
from rcp.objects import ExperimentSpec


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
