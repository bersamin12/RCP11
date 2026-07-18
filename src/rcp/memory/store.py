"""Memory store: versioned snapshots of raw papers, paper cards, and themes (PRD M1.6)."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from rcp.config import data_dir
from rcp.objects import PaperCard


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


class MemoryStore:
    def __init__(self, root: Path | None = None):
        self.root = (root or data_dir() / "memory")
        self.root.mkdir(parents=True, exist_ok=True)

    def save_snapshot(
        self, topic: str, raw_papers: list[dict], cards: list[PaperCard], themes: dict
    ) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        snap = self.root / _slug(topic) / stamp
        snap.mkdir(parents=True, exist_ok=True)
        (snap / "raw_papers.json").write_text(json.dumps(raw_papers, indent=2))
        (snap / "paper_cards.json").write_text(
            json.dumps([c.model_dump() for c in cards], indent=2)
        )
        (snap / "themes.json").write_text(json.dumps(themes, indent=2))
        (snap.parent / "latest.json").write_text(json.dumps({"snapshot": stamp}))
        return snap

    def load_latest(self, topic: str) -> tuple[list[PaperCard], dict] | None:
        topic_dir = self.root / _slug(topic)
        pointer = topic_dir / "latest.json"
        if not pointer.exists():
            return None
        snap = topic_dir / json.loads(pointer.read_text())["snapshot"]
        cards = [
            PaperCard.model_validate(c)
            for c in json.loads((snap / "paper_cards.json").read_text())
        ]
        themes = json.loads((snap / "themes.json").read_text())
        return cards, themes
