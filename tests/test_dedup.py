from rcp.memory.dedup import dedupe, normalize_title


def test_normalize_title():
    assert normalize_title("Deep Learning: A Survey!") == "deep learning a survey"


def test_dedupe_by_doi_merges_and_keeps_max_citations():
    papers = [
        {"title": "Paper A", "doi": "10.1/X", "citations": 5, "abstract": ""},
        {"title": "Paper A (v2)", "doi": "10.1/x", "citations": 9, "abstract": "full text"},
    ]
    result = dedupe(papers)
    assert len(result) == 1
    assert result[0]["citations"] == 9
    assert result[0]["abstract"] == "full text"


def test_dedupe_by_title_when_no_doi():
    papers = [
        {"title": "Same Title", "doi": None, "citations": 1},
        {"title": "same title", "doi": None, "citations": 2},
        {"title": "Different", "doi": None, "citations": 0},
    ]
    assert len(dedupe(papers)) == 2
