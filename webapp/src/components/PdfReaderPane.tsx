import { Suspense, lazy, useState } from "react";

import type { PaperCard, PdfSelectionAnchor } from "../types";
import { EmptyState, LoadingBlock } from "./UI";

// Lazy so pdfjs stays out of the main bundle, mirroring how App.tsx defers RunDetail.
const PdfReader = lazy(() => import("./pdf/PdfReader"));

export interface PdfReaderPaneProps {
  paper: PaperCard;
  page: number;
  view: "page" | "text";
  dim: boolean;
  onParams: (changes: Record<string, string | null>) => void;
  onClose: () => void;
  onCapture?: (anchor: PdfSelectionAnchor) => void;
}

/** Why a paper has no readable full text, phrased for a person. */
export function unavailableReason(paper: PaperCard): string {
  const asset = paper.pdf;
  if (!asset || asset.status === "not_attempted") return "No open-access full text has been looked for yet.";
  if (asset.status === "unreadable") return "A file was retrieved but could not be read as a PDF.";
  if (asset.status === "too_large") return "The published file exceeded the configured size limit.";
  if (asset.status === "not_pdf") return "The published open-access link did not return a PDF.";
  const attempts = asset.attempted_urls?.length ?? 0;
  if (attempts) return `${attempts} open-access location${attempts === 1 ? "" : "s"} were checked and none served a PDF.`;
  return asset.error || "No provider published an openly licensed full text for this paper.";
}

export function PdfReaderPane({ paper, page, view, dim, onParams, onClose, onCapture }: PdfReaderPaneProps) {
  const [anchor, setAnchor] = useState<PdfSelectionAnchor | null>(null);
  const sha = paper.pdf?.sha256 ?? "";
  const readable = paper.pdf?.status === "available" && Boolean(sha);

  if (!readable) {
    return <section className="card reader-pane" aria-label={`Reader: ${paper.title}`}>
      <EmptyState>
        {unavailableReason(paper)}
        {paper.url && <> <a href={paper.url} target="_blank" rel="noreferrer">
          Open the publisher record<span className="sr-only"> (opens in a new tab)</span>
        </a></>}
      </EmptyState>
    </section>;
  }

  return <Suspense fallback={<LoadingBlock label="Loading document viewer…" />}>
    <PdfReader
      paperId={paper.id}
      sha256={sha}
      title={paper.title}
      page={page}
      view={view}
      dim={dim}
      sourceUrl={paper.url}
      onPageChange={(next) => onParams({ page: String(next) })}
      onViewChange={(next) => onParams({ pdfview: next === "text" ? "text" : null })}
      onDimChange={(next) => onParams({ pdfdim: next ? "1" : null })}
      onCapture={(next) => { setAnchor(next); onCapture?.(next); }}
      onClose={onClose}
    />
    {anchor && !onCapture && <p className="sr-only" aria-live="polite">
      Captured a passage from page {anchor.page}.
    </p>}
  </Suspense>;
}
