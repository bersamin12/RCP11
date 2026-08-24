import { describe, expect, it } from "vitest";

import type { PdfSelectionAnchor } from "../../types";
import { anchorFromSelection, normalizeQuote, reanchor, verifyAnchor } from "./highlights";

const PAGE =
  "Data centre cooling was studied. Raising the chilled-water setpoint reduced chiller energy by 14 percent. Limitations remain.";
const QUOTE = "Raising the chilled-water setpoint reduced chiller energy by 14 percent.";

function anchorFor(pageText: string, quote: string): PdfSelectionAnchor {
  const start = pageText.indexOf(quote);
  return anchorFromSelection({
    paperId: "p1",
    pdfSha256: "a".repeat(64),
    page: 4,
    pageText,
    extractor: "pdfjs-4/text-layer",
    selectedText: quote,
    selectionStart: start,
    selectionEnd: start + quote.length,
    clientRects: [{ left: 120, top: 260, width: 300, height: 14 }],
    pageRect: { left: 100, top: 200, width: 600, height: 800 },
  });
}

describe("anchorFromSelection", () => {
  it("normalizes rectangles against the page so they survive zoom changes", () => {
    const anchor = anchorFor(PAGE, QUOTE);
    expect(anchor.rects).toHaveLength(1);
    const [rect] = anchor.rects;
    // (120-100)/600, (260-200)/800, 300/600, 14/800
    expect(rect.x).toBeCloseTo(0.0333, 3);
    expect(rect.y).toBeCloseTo(0.075, 3);
    expect(rect.width).toBeCloseTo(0.5, 3);
    expect(rect.height).toBeCloseTo(0.0175, 3);
  });

  it("captures surrounding context so a shifted anchor can be found again", () => {
    const anchor = anchorFor(PAGE, QUOTE);
    expect(anchor.prefix).toBe("Data centre cooling was studied.");
    expect(anchor.suffix).toBe("Limitations remain.");
    expect(anchor.page).toBe(4);
    expect(anchor.quote).toBe(QUOTE);
  });

  it("collapses whitespace so a quote spanning a line break still matches", () => {
    expect(normalizeQuote("  reduced   chiller\nenergy ")).toBe("reduced chiller energy");
  });
});

describe("verifyAnchor", () => {
  it("verifies an anchor whose offsets still point at the quote", () => {
    expect(verifyAnchor(anchorFor(PAGE, QUOTE), PAGE)).toBe("verified");
  });

  it("reports drift rather than silently repositioning", () => {
    const anchor = anchorFor(PAGE, QUOTE);
    const shifted = `A newly inserted opening sentence. ${PAGE}`;
    expect(verifyAnchor(anchor, shifted)).toBe("drifted");
  });

  it("is unverifiable when the quote is gone", () => {
    const anchor = anchorFor(PAGE, QUOTE);
    expect(verifyAnchor(anchor, "An entirely different page of text.")).toBe("unverifiable");
  });

  it("uses the stored context to disambiguate a quote that repeats", () => {
    const repeated = "In winter. Energy fell. In summer. Energy fell. Overall.";
    const anchor = anchorFor(repeated, "Energy fell.");
    expect(anchor.prefix).toBe("In winter.");
    // Two identical quotes, but only one is preceded by "In winter.".
    expect(verifyAnchor(anchor, `An added opening. ${repeated}`)).toBe("drifted");
  });

  it("is unverifiable when even the context cannot tell the copies apart", () => {
    // An identical table row repeated: quote and surrounding context both match twice.
    const row = "Row A. Value 3.2. Row B.";
    const anchor = anchorFor(row, "Value 3.2.");
    expect(verifyAnchor(anchor, `padding ${row} ${row}`)).toBe("unverifiable");
  });
});

describe("reanchor", () => {
  it("corrects the offsets of a drifted anchor", () => {
    const anchor = anchorFor(PAGE, QUOTE);
    const shifted = `A newly inserted opening sentence. ${PAGE}`;
    const fixed = reanchor(anchor, shifted);
    expect(fixed).not.toBeNull();
    expect(shifted.slice(fixed!.char_start, fixed!.char_end)).toBe(QUOTE);
  });

  it("refuses to place an anchor it cannot find", () => {
    expect(reanchor(anchorFor(PAGE, QUOTE), "unrelated text")).toBeNull();
  });
});
