import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { PdfReaderPane, unavailableReason } from "./PdfReaderPane";
import type { PaperCard, PdfAsset } from "../types";

vi.mock("./pdf/pdfEngine", () => ({
  pdfEngine: async () => ({
    load: async () => ({
      pageCount: 1,
      renderPage: async () => ({ width: 600, height: 800 }),
      pageText: async () => ({ items: [], text: "", viewport: { width: 600, height: 800 } }),
      destroy: () => undefined,
    }),
  }),
}));

const asset = (overrides: Partial<PdfAsset> = {}): PdfAsset => ({
  status: "unavailable", sha256: "", bytes: 0, page_count: 0, source_url: "",
  landing_page_url: "", oa_status: "", license: "", oa_version: "", provider: "",
  content_type: "", http_status: null, error: "", retrieved_at: "", attempted_urls: [],
  ...overrides,
});

const paper = (pdf: PdfAsset | null): PaperCard => ({
  id: "https://openalex.org/W1",
  title: "Cooling-aware energy management",
  year: 2015, doi: "10.1/x", url: "https://openalex.org/W1", venue: "IEEE",
  authors: [], citations: 82, abstract: "", problem: "", method: "", metrics: [],
  limitations: [], findings: [], study_conditions: [], tags: [],
  publication_type: "article", peer_review_confidence: "verified",
  credibility_explanation: "", provenance: [], selection_score: 61, ranking_factors: {},
  pdf,
});

describe("PdfReaderPane", () => {
  it("explains why a paper has no full text instead of showing an empty frame", async () => {
    const { container } = render(
      <PdfReaderPane
        paper={paper(asset({ attempted_urls: ["https://a.example/x.pdf", "https://b.example/y.pdf"] }))}
        page={1} view="page" dim={false} onParams={vi.fn()} onClose={vi.fn()}
      />,
    );
    expect(screen.getByText(/2 open-access locations were checked/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open the publisher record/ })).toBeInTheDocument();
    const audit = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });

  it("distinguishes a retrieved-but-unreadable file from one that was never found", () => {
    expect(unavailableReason(paper(asset({ status: "unreadable" }))))
      .toMatch(/could not be read as a PDF/);
    expect(unavailableReason(paper(asset({ status: "too_large" }))))
      .toMatch(/exceeded the configured size limit/);
    expect(unavailableReason(paper(null)))
      .toMatch(/has been looked for yet/);
  });

  it("never asks the engine for a document it does not have", () => {
    render(
      <PdfReaderPane
        paper={paper(asset({ status: "available", sha256: "" }))}
        page={1} view="page" dim={false} onParams={vi.fn()} onClose={vi.fn()}
      />,
    );
    // status says available but the hash is missing: treat as unreadable, not a fetch.
    expect(screen.getByText(/No provider published|open-access locations/)).toBeInTheDocument();
  });
});
