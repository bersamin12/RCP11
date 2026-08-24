"""Research Memory pipeline: query plan -> fetch -> dedup -> extract cards -> themes -> store."""

from pathlib import Path

from rich.console import Console

from rcp.config import get_settings
from rcp.literature.acquire import attach_open_access_pdfs
from rcp.memory.connectors import enrich_doi_metadata, search_openalex, search_semantic_scholar
from rcp.memory.dedup import dedupe
from rcp.memory.papercard import extract_card, screen_relevant
from rcp.memory.query_planner import plan_queries
from rcp.memory.ranking import rank_papers
from rcp.memory.store import MemoryStore
from rcp.memory.theme import build_theme_map
from rcp.objects import PaperCard

console = Console()


def build_research_memory(
    topic: str,
    max_papers: int = 10,
    per_query: int = 10,
    n_queries: int = 4,
) -> tuple[list[PaperCard], dict, Path]:
    console.print(f"[bold cyan]Research Memory[/] — topic: {topic}")

    queries = plan_queries(topic, n=n_queries)
    console.print(f"  queries: {queries}")

    raw: list[dict] = []
    for q in queries:
        oa = search_openalex(q, per_page=per_query)
        s2 = search_semantic_scholar(q, limit=per_query)
        console.print(f"  '{q}': openalex={len(oa)} s2={len(s2)}")
        raw += oa + s2

    papers = dedupe(raw)
    console.print(f"  {len(raw)} results -> {len(papers)} unique papers")

    papers = screen_relevant(papers, topic)
    console.print(f"  relevance screen kept {len(papers)} papers")

    papers = enrich_doi_metadata(papers)
    papers = rank_papers(papers, topic)

    # Ranking already rewards evidence completeness, including an abstract.
    # Do not exclude an otherwise strong peer-reviewed record solely because a
    # provider withheld its abstract.
    selected = papers[:max_papers]

    # Only the selected records are fetched, never the whole candidate pool.
    # A PDF is attached here but is never read: extract_card stays abstract-bounded,
    # because the presence of a file is not evidence that anyone read it.
    selected = attach_open_access_pdfs(selected)
    oa_pdf_count = sum(
        1 for paper in selected if (paper.get("pdf") or {}).get("status") == "available"
    )
    if get_settings().rcp_fetch_oa_pdfs:
        console.print(f"  open-access PDFs: {oa_pdf_count}/{len(selected)}")

    cards: list[PaperCard] = []
    for i, paper in enumerate(selected, 1):
        console.print(f"  extracting card {i}/{len(selected)}: {paper['title'][:70]}")
        try:
            cards.append(extract_card(paper, topic))
        except Exception as err:
            console.print(f"    [yellow]skipped ({err})[/]")

    themes = build_theme_map(cards)
    snapshot = MemoryStore().save_snapshot(
        topic, papers, cards, themes,
        metadata={
            "topic": topic, "queries": queries, "max_papers": max_papers,
            "per_query": per_query, "n_queries": n_queries,
            "raw_result_count": len(raw), "unique_result_count": len(papers),
            "oa_pdf_count": oa_pdf_count,
        },
    )
    console.print(f"[green]saved snapshot:[/] {snapshot}")
    return cards, themes, snapshot
