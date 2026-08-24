import pytest

from rcp.literature.fulltext import (
    apply_extraction,
    propose_full_text_card,
    read_pdf_pages,
    select_context,
)
from rcp.objects import PaperCard, PaperCardPatch, PdfAsset, ResearchFinding
from tests.pdf_fixture import make_pdf

BODY = "Raising the chilled-water setpoint from 6 to 10 C reduced chiller energy by 14 percent."
METHOD_PAGE = "Methods. We simulated nine matched pairs with a calibrated chiller model."
REFERENCE_PAGE = "References"
CITED = "Smith et al. reported a 40 percent saving from immersion cooling."


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_DATA_DIR", str(tmp_path / "data"))
    from rcp.config import get_settings

    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def write_pdf(tmp_path, pages: list[str]):
    path = tmp_path / "paper.pdf"
    path.write_bytes(make_pdf(pages))
    return path


def card_of() -> PaperCard:
    return PaperCard(
        id="https://openalex.org/W1", title="Setpoint study", year=2021,
        abstract="An abstract.", problem="cooling energy", method="unclear from abstract",
        extraction_basis="abstract",
        findings=[ResearchFinding(id="https://openalex.org/W1:finding:1",
                                  paper_id="https://openalex.org/W1",
                                  statement="Energy fell.", direction="decrease")],
    )


def asset_of() -> PdfAsset:
    return PdfAsset(status="available", sha256="a" * 64, page_count=3)


# ---------- reading and bounding ----------

def test_pages_are_numbered_as_a_reader_would_cite_them(store, tmp_path):
    pages = read_pdf_pages(write_pdf(tmp_path, [BODY, METHOD_PAGE]))
    assert [page.number for page in pages] == [1, 2]
    assert "chilled-water setpoint" in pages[0].text


def test_the_reference_list_is_cut_before_the_model_sees_it(store, tmp_path):
    """A cited paper's result restated as this paper's is the classic fabrication."""
    pages = read_pdf_pages(write_pdf(tmp_path, [BODY, METHOD_PAGE, REFERENCE_PAGE, CITED]))
    context, used = select_context(pages)
    assert "immersion cooling" not in context
    assert 4 not in used
    assert "chilled-water setpoint" in context


def test_a_references_section_starting_mid_page_is_still_cut(store, tmp_path):
    """The realistic layout: body text, then the heading, then the citations."""
    mixed = f"{METHOD_PAGE} References. {CITED}"
    pages = read_pdf_pages(write_pdf(tmp_path, [BODY, mixed]))
    context, _ = select_context(pages)
    assert "immersion cooling" not in context
    assert "nine matched pairs" in context, "body text before the heading must survive"


def test_page_markers_survive_into_the_extract(store, tmp_path):
    pages = read_pdf_pages(write_pdf(tmp_path, [BODY, METHOD_PAGE]))
    context, used = select_context(pages)
    for number in used:
        assert f"[[page={number}]]" in context


def test_the_extract_respects_the_configured_budget(store, tmp_path, monkeypatch):
    monkeypatch.setenv("RCP_FULLTEXT_MAX_CHARS", "120")
    from rcp.config import get_settings

    get_settings.cache_clear()
    pages = read_pdf_pages(write_pdf(tmp_path, [BODY, METHOD_PAGE, BODY, METHOD_PAGE]))
    context, _ = select_context(pages)
    assert len(context) <= 120


# ---------- a proposal changes nothing ----------

def test_a_proposal_leaves_the_card_untouched(store, tmp_path):
    card = card_of()
    before = card.model_dump()
    extraction = propose_full_text_card(
        "run-1", card, asset_of(), write_pdf(tmp_path, [BODY, METHOD_PAGE]), "cooling",
        generate=lambda *a, **k: PaperCardPatch(
            method="Simulation of nine matched pairs",
            findings=[ResearchFinding(id="x", paper_id="x", statement="Energy fell 14%.",
                                      direction="decrease", source_pages=[1], quote=BODY)],
        ),
    )
    assert extraction.status == "proposed"
    assert card.model_dump() == before
    assert card.extraction_basis == "abstract"


def test_a_finding_whose_quote_is_absent_from_the_text_is_dropped(store, tmp_path):
    extraction = propose_full_text_card(
        "run-1", card_of(), asset_of(), write_pdf(tmp_path, [BODY]), "cooling",
        generate=lambda *a, **k: PaperCardPatch(findings=[
            ResearchFinding(id="x", paper_id="x", statement="Energy fell 14%.",
                            direction="decrease", source_pages=[1], quote=BODY),
            ResearchFinding(id="y", paper_id="y", statement="Immersion cooling saved 40%.",
                            direction="decrease", source_pages=[1],
                            quote="A sentence that was never in this document."),
        ]),
    )
    assert len(extraction.proposed.findings) == 1
    assert any("quote is absent" in w for w in extraction.warnings)


def test_a_finding_citing_a_page_outside_the_extract_is_dropped(store, tmp_path):
    extraction = propose_full_text_card(
        "run-1", card_of(), asset_of(), write_pdf(tmp_path, [BODY]), "cooling",
        generate=lambda *a, **k: PaperCardPatch(findings=[
            ResearchFinding(id="x", paper_id="x", statement="Energy fell.", direction="decrease",
                            source_pages=[99], quote=BODY),
        ]),
    )
    assert extraction.proposed.findings == []
    assert any("outside the extract" in w for w in extraction.warnings)


def test_proposed_findings_use_a_separate_id_namespace(store, tmp_path):
    """An accepted upgrade must never collide with an abstract-derived finding."""
    card = card_of()
    extraction = propose_full_text_card(
        "run-1", card, asset_of(), write_pdf(tmp_path, [BODY]), "cooling",
        generate=lambda *a, **k: PaperCardPatch(findings=[
            ResearchFinding(id="ignored", paper_id="ignored", statement="Energy fell 14%.",
                            direction="decrease", source_pages=[1], quote=BODY),
        ]),
    )
    new_id = extraction.proposed.findings[0].id
    assert new_id == f"{card.id}:finding:ft1"
    assert new_id not in {finding.id for finding in card.findings}
    assert extraction.superseded_finding_ids == [f"{card.id}:finding:1"]


def test_an_image_only_pdf_never_calls_the_model(store, tmp_path):
    empty = tmp_path / "scan.pdf"
    empty.write_bytes(make_pdf([" "]))

    def must_not_run(*args, **kwargs):
        raise AssertionError("the LLM must not be called without extractable text")

    extraction = propose_full_text_card(
        "run-1", card_of(), asset_of(), empty, "cooling", generate=must_not_run,
    )
    assert extraction.status == "rejected"
    assert any("no extractable text layer" in w for w in extraction.warnings)


# ---------- only a confirmation reaches the full_text tier ----------

def test_an_unconfirmed_extraction_cannot_be_applied(store, tmp_path):
    extraction = propose_full_text_card(
        "run-1", card_of(), asset_of(), write_pdf(tmp_path, [BODY]), "cooling",
        generate=lambda *a, **k: PaperCardPatch(method="Simulation"),
    )
    with pytest.raises(ValueError, match="only a confirmed extraction"):
        apply_extraction(card_of(), extraction)


def test_a_confirmed_extraction_records_the_page_and_the_person(store, tmp_path):
    card = card_of()
    extraction = propose_full_text_card(
        "run-1", card, asset_of(), write_pdf(tmp_path, [BODY, METHOD_PAGE]), "cooling",
        generate=lambda *a, **k: PaperCardPatch(
            method="Simulation of nine matched pairs",
            findings=[ResearchFinding(id="x", paper_id="x", statement="Energy fell 14%.",
                                      direction="decrease", source_pages=[1], quote=BODY)],
        ),
    )
    extraction.status = "accepted"
    updated = apply_extraction(card, extraction, ["method", "findings"], confirmed_by="gsw")

    assert updated.extraction_basis == "full_text"
    assert updated.method == "Simulation of nine matched pairs"
    assert updated.field_provenance["method"] == ["full_text", "pdf:aaaaaaaaaaaa", "confirmed:gsw"]
    assert updated.findings[0].extraction_basis == "full_text"
    assert updated.findings[0].source_pages == [1]
    assert updated.findings[0].quote


def test_only_the_fields_a_person_ticked_are_applied(store, tmp_path):
    card = card_of()
    extraction = propose_full_text_card(
        "run-1", card, asset_of(), write_pdf(tmp_path, [BODY]), "cooling",
        generate=lambda *a, **k: PaperCardPatch(method="Simulation", problem="rewritten problem"),
    )
    extraction.status = "accepted"
    updated = apply_extraction(card, extraction, ["method"], confirmed_by="gsw")
    assert updated.method == "Simulation"
    assert updated.problem == card.problem, "an unticked field must not be rewritten"
    assert "problem" not in updated.field_provenance
