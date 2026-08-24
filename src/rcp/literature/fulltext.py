"""Read a cached open-access PDF and propose a page-cited card revision.

Nothing here changes a paper card. It produces a *proposal* that a human reads
against the document and confirms at the literature-triage gate. That confirmation
step is the entire meaning of ``extraction_basis == "full_text"``: without it the
tier would say only that a file was downloaded, which is not the same as anyone
having read it.

Two deterministic guards bound what the model can assert:

* the reference list is cut before the text is shown, because the single most
  common fabricated "finding" is a cited paper's title restated as this paper's
  result; and
* every proposed finding must quote text that actually appears in the extract, and
  cite a page that was actually supplied. Quotes that fail are dropped, not
  flagged -- a claim we cannot locate in the source has no business in a card.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from rcp.config import data_dir, get_settings
from rcp.llm import llm_json
from rcp.objects import (
    FullTextExtraction,
    PaperCard,
    PaperCardPatch,
    PdfAsset,
    ResearchFinding,
    utc_now,
)

# Page text is whitespace-normalised, so line anchors are useless here. The heading
# is matched wherever it appears; body text before it is kept and everything from it
# onwards is discarded, which handles both a dedicated reference page and a section
# that begins partway down one.
REFERENCES_RE = re.compile(
    r"\b(references|bibliography|works cited|literature cited)\b\s*[:.]?(?:\s|$)",
    re.IGNORECASE,
)
PRIORITY_RE = re.compile(
    r"\b(abstract|introduction|method|methodology|materials|experimental|"
    r"result|discussion|conclusion|evaluation|analysis)\b",
    re.IGNORECASE,
)
PAGE_MARKER = "[[page={number}]]"
MIN_PAGE_CHARS = 40


class PdfPage(BaseModel):
    number: int  # 1-based, as a reader would cite it
    text: str


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def read_pdf_pages(path: Path, max_pages: int | None = None) -> list[PdfPage]:
    """Per-page text. Returns [] for an image-only scan or an unparseable file."""
    limit = max_pages or get_settings().rcp_pdf_max_pages
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception:
        return []
    pages: list[PdfPage] = []
    for index, page in enumerate(reader.pages[:limit], 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        # Short pages are kept here so a bare "References" heading page can still
        # mark where the body ends; they are dropped after that cut.
        pages.append(PdfPage(number=index, text=_normalize(text)))
    return pages


def select_context(pages: list[PdfPage], max_chars: int | None = None) -> tuple[str, list[int]]:
    """Build a page-tagged extract of the paper's own body text."""
    budget = max_chars or get_settings().rcp_fulltext_max_chars
    if not pages:
        return "", []

    # Everything from the reference list onwards is about other people's work.
    body = pages
    for position, page in enumerate(pages):
        match = REFERENCES_RE.search(page.text) if position > 0 else None
        if match:
            head = page.text[: match.start()].strip()
            body = pages[:position]
            if head:
                body = [*body, page.model_copy(update={"text": head})]
            break
    # Only now drop pages too sparse to be worth showing -- a bare heading page had
    # to survive long enough to mark the cut.
    body = [page for page in body if len(page.text) >= MIN_PAGE_CHARS]
    if not body:
        return "", []

    chosen: dict[int, PdfPage] = {}
    used = 0
    for group in (
        [page for page in body if PRIORITY_RE.search(page.text)],
        body,
    ):
        for page in group:
            if page.number in chosen:
                continue
            marker = PAGE_MARKER.format(number=page.number)
            cost = len(page.text) + len(marker) + 2
            if used + cost > budget:
                continue
            chosen[page.number] = page
            used += cost

    ordered = [chosen[number] for number in sorted(chosen)]
    context = "\n\n".join(
        f"{PAGE_MARKER.format(number=page.number)}\n{page.text}" for page in ordered
    )
    return context, [page.number for page in ordered]


def extraction_dir(run_id: str) -> Path:
    return data_dir() / "runs" / run_id / "literature" / "fulltext"


def _slug(paper_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", paper_id.lower()).strip("-")[:60] or "paper"


def save_extraction(run_id: str, extraction: FullTextExtraction) -> Path:
    directory = extraction_dir(run_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{_slug(extraction.paper_id)}-{extraction.id.rsplit(':', 1)[-1]}.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(extraction.model_dump_json(indent=2))
    temporary.replace(destination)
    return destination


def load_extractions(run_id: str, paper_id: str | None = None) -> list[FullTextExtraction]:
    directory = extraction_dir(run_id)
    if not directory.is_dir():
        return []
    found: list[FullTextExtraction] = []
    for path in sorted(directory.glob("*.json")):
        try:
            extraction = FullTextExtraction.model_validate_json(path.read_text())
        except ValueError:
            continue
        if paper_id is None or extraction.paper_id == paper_id:
            found.append(extraction)
    return found


SYSTEM = (
    "You extract structured scientific evidence from the full text of one paper. "
    "Never invent a result, condition, method, or limitation that is absent from the "
    "supplied text. Every finding must set source_pages to the [[page=N]] marker(s) "
    "covering the sentence it came from, and quote to that sentence copied verbatim. "
    "Ignore any result attributed to a cited paper rather than to this study."
)


def propose_full_text_card(
    run_id: str,
    card: PaperCard,
    asset: PdfAsset,
    pdf_file: Path,
    topic: str,
    generate: Callable[..., Any] | None = None,
    sequence: int = 1,
) -> FullTextExtraction:
    """Read the PDF and propose a revision. The card itself is never touched."""
    # Resolved here, not as a default argument: a default binds at definition time,
    # which would silently defeat any attempt to substitute the provider in a test.
    generate = generate or llm_json
    extraction = FullTextExtraction(
        id=f"fulltext:{_slug(card.id)}:{sequence}",
        run_id=run_id,
        paper_id=card.id,
        pdf_sha256=asset.sha256,
        page_count=asset.page_count,
        created_at=utc_now(),
        llm_model=get_settings().rcp_model,
    )

    pages = read_pdf_pages(pdf_file)
    context, used = select_context(pages)
    if not context:
        # An image-only scan. Refuse without spending a token on it.
        extraction.status = "rejected"
        extraction.warnings = ["The PDF has no extractable text layer; it may be a scanned image."]
        return extraction

    extraction.pages_used = used
    extraction.chars_used = len(context)

    patch = generate(
        f"Research topic under study: {topic}\n\n"
        f"Paper title: {card.title}\n"
        f"Venue: {card.venue or 'unknown'} ({card.year or '?'})\n\n"
        f"Full text (page-tagged, reference list removed):\n{context}\n\n"
        "Extract only information explicitly supported by this text: the problem, method "
        "(including mathematical models when stated), metrics, stated limitations, study "
        "conditions, 3-6 topical tags, and discrete reported findings. For each finding, "
        "record the intervention, outcome, direction, conditions, metrics, the source "
        "pages, and the verbatim supporting sentence. Use empty values rather than "
        "inferring anything the text does not contain.",
        PaperCardPatch,
        system=SYSTEM,
    )

    haystack = _normalize(context).casefold()
    allowed = set(used)
    kept: list[ResearchFinding] = []
    warnings: list[str] = []
    for index, finding in enumerate(patch.findings, 1):
        if not finding.statement.strip():
            continue
        pages_cited = [number for number in finding.source_pages if number in allowed]
        if not pages_cited:
            warnings.append(f"Dropped a finding citing pages outside the extract: {finding.statement[:70]}")
            continue
        quote = _normalize(finding.quote)
        if not quote or quote.casefold() not in haystack:
            # The strongest deterministic check available: a sentence we cannot
            # locate in the source was not read out of it.
            warnings.append(f"Dropped a finding whose quote is absent from the text: {finding.statement[:70]}")
            continue
        kept.append(finding.model_copy(update={
            # A separate namespace from the abstract scheme, so an accepted upgrade
            # can never collide with, or masquerade as, an abstract-derived finding.
            "id": f"{card.id}:finding:ft{len(kept) + 1}",
            "paper_id": card.id,
            "extraction_basis": "full_text",
            "source_pages": pages_cited,
            "quote": quote,
        }))

    extraction.proposed = patch.model_copy(update={"findings": kept})
    extraction.superseded_finding_ids = [finding.id for finding in card.findings]
    extraction.warnings = warnings
    return extraction


PATCH_FIELDS = ("problem", "method", "metrics", "limitations", "study_conditions", "tags")


def apply_extraction(
    card: PaperCard, extraction: FullTextExtraction, accepted_fields: list[str] | None = None,
    confirmed_by: str = "",
) -> PaperCard:
    """Apply a confirmed proposal, recording that a person accepted each field."""
    if extraction.status != "accepted":
        raise ValueError("only a confirmed extraction may be applied to a card")

    fields = set(accepted_fields if accepted_fields is not None else PATCH_FIELDS)
    updated = card.model_copy(deep=True)
    provenance = dict(updated.field_provenance)
    source = [
        "full_text",
        f"pdf:{extraction.pdf_sha256[:12]}",
        f"confirmed:{confirmed_by or extraction.confirmed_by or 'human'}",
    ]

    touched = False
    for field in PATCH_FIELDS:
        if field not in fields:
            continue
        value = getattr(extraction.proposed, field)
        if not value:
            continue
        setattr(updated, field, value)
        provenance[field] = list(source)
        touched = True

    if "findings" in fields and extraction.proposed.findings:
        updated.findings = list(extraction.proposed.findings)
        provenance["findings"] = list(source)
        touched = True

    if touched:
        updated.field_provenance = provenance
        # The maximum tier present on the card, not a blanket relabel.
        updated.extraction_basis = "full_text"
        updated.full_text_extraction_id = extraction.id
        updated.insufficient_evidence = [
            name for name in updated.insufficient_evidence if name not in fields
        ]
    return updated
