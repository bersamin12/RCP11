from rcp.memory.papercard import CardFields, FindingFields, extract_card
from rcp.memory.synthesis import SynthesisProposal, build_research_synthesis
from rcp.objects import PaperCard, ResearchConflict, ResearchFinding, ResearchGap


def _card(paper_id: str, direction: str, condition: str = "hot climate") -> PaperCard:
    return PaperCard(
        id=paper_id, title=f"Paper {paper_id}", abstract="available", extraction_basis="abstract",
        findings=[ResearchFinding(
            id=f"{paper_id}:finding:1", paper_id=paper_id,
            statement=f"Setpoint produced {direction} cooling energy.",
            intervention="higher cooling setpoint", outcome="cooling energy",
            direction=direction, conditions=[condition],
        )],
    )


def test_abstract_findings_receive_stable_ids_and_provenance(monkeypatch):
    monkeypatch.setattr(
        "rcp.memory.papercard.llm_json",
        lambda *args, **kwargs: CardFields(
            problem="Cooling energy", method="Simulation", metrics=["energy"],
            study_conditions=["hot climate"],
            findings=[FindingFields(
                statement="A higher setpoint reduced cooling energy.",
                intervention="higher setpoint", outcome="cooling energy", direction="decrease",
            )],
        ),
    )
    card = extract_card({"id": "p1", "title": "Cooling", "abstract": "Evidence"}, "cooling")
    assert card.findings[0].id == "p1:finding:1"
    assert card.findings[0].extraction_basis == "abstract"
    assert card.field_provenance["findings"] == ["abstract"]
    assert "findings" not in card.insufficient_evidence


def test_synthesis_validates_references_and_demotes_unsupported_contradiction():
    cards = [_card("p1", "decrease"), _card("p2", "decrease", "mild climate")]

    def generate(*args, **kwargs):
        return SynthesisProposal(
            gaps=[
                ResearchGap(
                    id="invented", category="scenario", statement="Climate sensitivity is unresolved.",
                    paper_ids=["p1", "missing"], finding_ids=["p1:finding:1", "bad"],
                    model_names=["DataCenterRoom", "ImaginaryModel"], confidence="medium",
                ),
                ResearchGap(
                    id="bad", category="scope", statement="Unsupported", paper_ids=["missing"],
                ),
            ],
            conflicts=[ResearchConflict(
                id="c", kind="contradiction", statement="Reported effects differ by climate.",
                finding_ids=["p1:finding:1", "p2:finding:1"], paper_ids=["missing"],
            )],
        )

    synthesis = build_research_synthesis("cooling", cards, "/snapshot", generate=generate)
    assert synthesis.gaps[0].id == "gap-1"
    assert synthesis.gaps[0].paper_ids == ["p1"]
    assert synthesis.gaps[0].finding_ids == ["p1:finding:1"]
    assert synthesis.gaps[0].model_names == ["DataCenterRoom"]
    assert len(synthesis.gaps) == 1
    assert synthesis.conflicts[0].kind == "tension"
    assert synthesis.conflicts[0].paper_ids == ["p1", "p2"]
    assert any("Demoted" in warning for warning in synthesis.warnings)
    assert any("Dropped unsupported gap" in warning for warning in synthesis.warnings)


def test_direct_opposing_findings_remain_a_contradiction():
    cards = [_card("p1", "decrease"), _card("p2", "increase")]

    def generate(*args, **kwargs):
        return SynthesisProposal(
            gaps=[ResearchGap(
                id="g", category="scenario", statement="Conditions require testing.", paper_ids=["p1"],
            )],
            conflicts=[ResearchConflict(
                id="c", kind="contradiction", statement="Setpoint energy direction conflicts.",
                finding_ids=["p1:finding:1", "p2:finding:1"],
            )],
        )

    synthesis = build_research_synthesis("cooling", cards, generate=generate)
    assert synthesis.conflicts[0].kind == "contradiction"
    assert synthesis.papers_with_findings == 2
    assert synthesis.finding_count == 2


def test_title_only_coverage_degrades_without_inventing_conflicts():
    card = PaperCard(id="p1", title="Title only")
    synthesis = build_research_synthesis(
        "cooling", [card], generate=lambda *args, **kwargs: SynthesisProposal(),
    )
    assert synthesis.papers_with_abstract == 0
    assert synthesis.conflicts == []
    assert synthesis.gaps[0].confidence == "low"
    assert any("title-only" in warning for warning in synthesis.warnings)
