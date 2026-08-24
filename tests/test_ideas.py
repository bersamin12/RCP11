from rcp.ideas import generate_thesis_ideas
from rcp.objects import ThesisProfile


def test_thesis_ideas_degrade_to_five_registry_grounded_candidates(monkeypatch):
    monkeypatch.setattr("rcp.ideas.search_openalex", lambda *args, **kwargs: [])
    monkeypatch.setattr("rcp.ideas.search_semantic_scholar", lambda *args, **kwargs: [])
    monkeypatch.setattr("rcp.ideas.llm_json", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    profile = ThesisProfile(domain="Data-center cooling", interests=["resilience"])
    ideas = generate_thesis_ideas(profile)
    assert len(ideas) == 5
    assert [idea.rank for idea in ideas] == [1, 2, 3, 4, 5]
    assert all(idea.model_names == ["DataCenterRoom"] for idea in ideas)
    assert all(idea.provider_status == "degraded" for idea in ideas)
    assert "provider unavailable" in ideas[0].provider_warnings[0]
