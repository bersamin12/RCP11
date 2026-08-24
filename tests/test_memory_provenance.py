import json

from rcp.memory.papercard import extract_card
from rcp.memory.store import MemoryStore


def test_missing_abstract_is_marked_without_llm_inference(monkeypatch):
    monkeypatch.setattr(
        "rcp.memory.papercard.llm_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    card = extract_card({"id": "p1", "title": "Title-only record"}, "cooling")
    assert card.extraction_basis == "title"
    assert card.method == ""
    assert {"problem", "method", "metrics", "limitations"} <= set(card.insufficient_evidence)


def test_an_attached_pdf_never_upgrades_the_extraction_basis(monkeypatch):
    """Having the file is not the same as having read it.

    Only a human confirming a full-text proposal at the triage gate may raise a
    card to "full_text"; acquisition alone must leave the tier untouched.
    """
    monkeypatch.setattr(
        "rcp.memory.papercard.llm_json",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("LLM must not be called")),
    )
    paper = {
        "id": "p1",
        "title": "Title-only record",
        "pdf": {"status": "available", "sha256": "a" * 64, "page_count": 12},
    }
    card = extract_card(paper, "cooling")
    assert card.extraction_basis == "title"
    assert card.pdf is not None and card.pdf.status == "available"
    assert card.pdf.page_count == 12


def test_memory_snapshot_preserves_inputs_and_is_reloadable(tmp_path):
    store = MemoryStore(tmp_path / "memory")
    card = extract_card({"id": "p1", "title": "Title-only record"}, "cooling")
    snapshot = store.save_snapshot(
        "Cooling Study", [{"id": "p1"}], [card], {"cooling": ["p1"]},
        metadata={"topic": "Cooling Study", "queries": ["cooling benchmark"], "per_query": 5},
    )
    manifest = json.loads((snapshot / "snapshot_manifest.json").read_text())
    assert manifest["queries"] == ["cooling benchmark"]
    loaded = store.load_latest("Cooling Study")
    assert loaded is not None
    assert loaded[0][0].id == "p1"
