"""Theme builder: cluster paper cards by tag into a theme map (PRD M1.5, minimal MVP)."""

from collections import defaultdict

from rcp.objects import PaperCard


def build_theme_map(cards: list[PaperCard]) -> dict[str, list[str]]:
    themes: dict[str, list[str]] = defaultdict(list)
    for card in cards:
        for tag in card.tags:
            themes[tag.lower().strip()].append(card.title)
    return dict(sorted(themes.items(), key=lambda kv: len(kv[1]), reverse=True))
