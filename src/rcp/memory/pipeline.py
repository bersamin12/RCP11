"""Research Memory pipeline: query plan -> fetch -> dedup -> extract cards -> themes -> store."""

from pathlib import Path

from rich.console import Console

from rcp.memory.connectors import search_openalex, search_semantic_scholar
from rcp.memory.dedup import dedupe
from rcp.memory.papercard import extract_card, screen_relevant
from rcp.memory.query_planner import plan_queries
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

    with_abstract = [p for p in papers if p.get("abstract")]
    selected = (with_abstract or papers)[:max_papers]
    cards: list[PaperCard] = []
    for i, paper in enumerate(selected, 1):
        console.print(f"  extracting card {i}/{len(selected)}: {paper['title'][:70]}")
        try:
            cards.append(extract_card(paper, topic))
        except RuntimeError as err:
            console.print(f"    [yellow]skipped ({err})[/]")

    themes = build_theme_map(cards)
    snapshot = MemoryStore().save_snapshot(topic, papers, cards, themes)
    console.print(f"[green]saved snapshot:[/] {snapshot}")
    return cards, themes, snapshot
