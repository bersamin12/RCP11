/**
 * Anchoring a highlighted passage to a place in a document.
 *
 * The anchor is page + quote, not pixel coordinates: that survives a re-render, a
 * zoom change, and a different device pixel ratio, and it is what a person
 * actually cites. Rectangles are kept only to paint the highlight, normalised
 * 0-1 against the page so they stay resolution-independent.
 *
 * Every function here takes plain data rather than DOM objects. That is
 * deliberate -- jsdom returns an empty list from `Range.getClientRects()`, so
 * rect maths would otherwise be untestable outside a real browser.
 */

import type { PdfHighlightRect, PdfSelectionAnchor } from "../../types";

const CONTEXT_CHARS = 48;

export function normalizeQuote(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

export interface SelectionInput {
  paperId: string;
  pdfSha256?: string;
  page: number;
  pageText: string;
  extractor: string;
  selectedText: string;
  selectionStart: number;
  selectionEnd: number;
  clientRects: readonly { left: number; top: number; width: number; height: number }[];
  pageRect: { left: number; top: number; width: number; height: number };
}

export function anchorFromSelection(input: SelectionInput): PdfSelectionAnchor {
  const { pageRect } = input;
  const width = pageRect.width || 1;
  const height = pageRect.height || 1;
  const rects: PdfHighlightRect[] = input.clientRects.map((rect) => ({
    x: (rect.left - pageRect.left) / width,
    y: (rect.top - pageRect.top) / height,
    width: rect.width / width,
    height: rect.height / height,
  }));
  return {
    paper_id: input.paperId,
    pdf_sha256: input.pdfSha256 ?? "",
    page: input.page,
    quote: normalizeQuote(input.selectedText),
    prefix: normalizeQuote(input.pageText.slice(Math.max(0, input.selectionStart - CONTEXT_CHARS), input.selectionStart)),
    suffix: normalizeQuote(input.pageText.slice(input.selectionEnd, input.selectionEnd + CONTEXT_CHARS)),
    char_start: input.selectionStart,
    char_end: input.selectionEnd,
    rects,
    extractor: input.extractor,
  };
}

export type AnchorVerification = "verified" | "drifted" | "unverifiable";

function findAll(haystack: string, needle: string): number[] {
  if (!needle) return [];
  const hits: number[] = [];
  let from = 0;
  for (;;) {
    const at = haystack.indexOf(needle, from);
    if (at === -1) return hits;
    hits.push(at);
    from = at + 1;
    if (hits.length > 2) return hits; // ambiguity is all we need to know
  }
}

/**
 * Whether the stored offsets still point at the quoted text.
 *
 * A drifted or unverifiable anchor is surfaced to the reader rather than quietly
 * repositioned -- the same rule the platform applies to a raw-result hash that no
 * longer matches.
 */
export function verifyAnchor(anchor: PdfSelectionAnchor, pageText: string): AnchorVerification {
  const quote = normalizeQuote(anchor.quote);
  if (!quote) return "unverifiable";
  const normalized = normalizeQuote(pageText);
  if (normalizeQuote(pageText.slice(anchor.char_start, anchor.char_end)) === quote) return "verified";

  const contextual = normalizeQuote(`${anchor.prefix} ${quote} ${anchor.suffix}`);
  if (anchor.prefix || anchor.suffix) {
    if (findAll(normalized, contextual).length === 1) return "drifted";
  }
  return findAll(normalized, quote).length === 1 ? "drifted" : "unverifiable";
}

/** Corrected offsets for a drifted anchor, or null when it cannot be placed. */
export function reanchor(anchor: PdfSelectionAnchor, pageText: string): PdfSelectionAnchor | null {
  if (verifyAnchor(anchor, pageText) !== "drifted") return null;
  const quote = normalizeQuote(anchor.quote);
  const at = pageText.indexOf(quote);
  if (at === -1) return null;
  return { ...anchor, char_start: at, char_end: at + quote.length };
}
