from rcp.memory.ranking import rank_papers


def test_rank_papers_prefers_credible_complete_work_and_is_deterministic():
    papers = [
        {
            "id": "pre", "title": "Cooling optimization digital twins", "abstract": "cooling digital twins",
            "year": 2026, "publication_type": "preprint", "venue": "arXiv", "citations": 40,
            "provenance": ["openalex"],
        },
        {
            "id": "journal", "title": "Cooling optimization digital twins", "abstract": "cooling digital twins",
            "year": 2024, "publication_type": "journal-article", "venue": "Energy and Buildings",
            "doi": "10.1/example", "authors": ["A. Author"], "citations": 10,
            "provenance": ["crossref", "openalex-doi"],
        },
    ]
    first = rank_papers(papers, "cooling optimization digital twins")
    second = rank_papers(papers, "cooling optimization digital twins")
    assert [paper["id"] for paper in first] == [paper["id"] for paper in second]
    assert first[0]["id"] == "journal"
    assert first[0]["peer_review_confidence"] == "verified"
    assert first[1]["peer_review_confidence"] == "preprint"
    assert first[0]["ranking_factors"]["relevance"] >= 0.9


def test_rank_order_preserves_provider_relevance_prior_for_otherwise_equal_records():
    papers = [
        {"id": "2", "title": "Beta cooling", "publication_type": "unknown"},
        {"id": "1", "title": "Alpha cooling", "publication_type": "unknown"},
    ]
    ranked = rank_papers(papers, "unrelated")
    assert [paper["title"] for paper in ranked] == ["Beta cooling", "Alpha cooling"]
