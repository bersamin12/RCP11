import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api } from "../../api";
import type { PdfSelectionAnchor } from "../../types";
import { Alert, Button, LoadingBlock } from "../UI";
import { anchorFromSelection } from "./highlights";
import { pdfEngine, type PdfDocumentHandle, type PdfPageText } from "./pdfEngine";

const EXTRACTOR = "pdfjs-4/text-layer";
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;

export interface PdfReaderProps {
  paperId: string;
  sha256: string;
  title: string;
  page: number;
  view: "page" | "text";
  dim: boolean;
  onPageChange: (page: number) => void;
  onViewChange: (view: "page" | "text") => void;
  onDimChange: (dim: boolean) => void;
  onCapture: (anchor: PdfSelectionAnchor) => void;
  onClose: () => void;
  sourceUrl?: string | null;
}

/** Text items grouped into paragraph-ish blocks for the accessible reading view. */
function blocksOf(content: PdfPageText | null): string[] {
  if (!content) return [];
  const blocks: string[] = [];
  let current = "";
  for (const item of content.items) {
    current += item.str;
    if (item.hasEOL) {
      current += " ";
      if (current.trim().length > 120) {
        blocks.push(current.trim());
        current = "";
      }
    }
  }
  if (current.trim()) blocks.push(current.trim());
  return blocks.length ? blocks : [content.text.trim()].filter(Boolean);
}

export default function PdfReader({
  paperId, sha256, title, page, view, dim,
  onPageChange, onViewChange, onDimChange, onCapture, onClose, sourceUrl,
}: PdfReaderProps) {
  const [doc, setDoc] = useState<PdfDocumentHandle | null>(null);
  const [content, setContent] = useState<PdfPageText | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState(1);
  const [hasSelection, setHasSelection] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  const region = useRef<HTMLElement | null>(null);
  const shell = useRef<HTMLDivElement | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const textLayer = useRef<HTMLDivElement | null>(null);

  const pageCount = doc?.pageCount ?? 0;
  const current = Math.min(Math.max(1, page), pageCount || 1);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setDoc(null);
    pdfEngine()
      .then((engine) => engine.load(api.literaturePdfUrl(sha256), controller.signal))
      .then((handle) => { if (active) setDoc(handle); })
      .catch((err) => { if (active) setError(err instanceof Error ? err.message : String(err)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; controller.abort(); };
  }, [sha256, reloadKey]);

  useEffect(() => () => doc?.destroy(), [doc]);

  // Text is loaded for both modes: the page view needs it for the selectable
  // overlay, the text view renders it directly.
  useEffect(() => {
    if (!doc) return;
    let active = true;
    doc.pageText(current)
      .then((next) => { if (active) setContent(next); })
      .catch(() => { if (active) setContent(null); });
    return () => { active = false; };
  }, [doc, current]);

  useEffect(() => {
    if (!doc || view !== "page" || !canvas.current || !shell.current) return;
    const width = shell.current.clientWidth - 24;
    if (width <= 0) return;
    let active = true;
    void doc.renderPage(current, canvas.current, width, zoom).catch(() => {
      if (active) setError("This page could not be rendered. Try the text view.");
    });
    return () => { active = false; };
  }, [doc, current, zoom, view]);

  useEffect(() => {
    const onSelect = () => {
      const selection = window.document.getSelection();
      const anchorNode = selection?.anchorNode ?? null;
      setHasSelection(
        Boolean(selection && !selection.isCollapsed && anchorNode && textLayer.current?.contains(anchorNode)),
      );
    };
    window.document.addEventListener("selectionchange", onSelect);
    return () => window.document.removeEventListener("selectionchange", onSelect);
  }, []);

  useEffect(() => { region.current?.focus(); }, []);

  const capture = useCallback((quote: string) => {
    const text = content?.text ?? "";
    const start = text.indexOf(quote);
    onCapture(anchorFromSelection({
      paperId, pdfSha256: sha256, page: current, pageText: text, extractor: EXTRACTOR,
      selectedText: quote,
      selectionStart: start < 0 ? 0 : start,
      selectionEnd: start < 0 ? quote.length : start + quote.length,
      clientRects: [],
      pageRect: { left: 0, top: 0, width: 1, height: 1 },
    }));
  }, [content, current, onCapture, paperId, sha256]);

  const captureSelection = () => {
    const selection = window.document.getSelection();
    const quote = selection?.toString() ?? "";
    if (quote.trim()) capture(quote.trim());
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    // Scoped to the reader, never window: the run page has its own shortcuts.
    if (event.target instanceof HTMLInputElement) return;
    const go = (next: number) => { event.preventDefault(); onPageChange(Math.min(Math.max(1, next), pageCount || 1)); };
    if (event.key === "ArrowRight" || event.key === "PageDown") go(current + 1);
    else if (event.key === "ArrowLeft" || event.key === "PageUp") go(current - 1);
    else if (event.key === "Home") go(1);
    else if (event.key === "End") go(pageCount || 1);
    else if (event.key === "+" || event.key === "=") { event.preventDefault(); setZoom((z) => Math.min(MAX_ZOOM, z + 0.25)); }
    else if (event.key === "-") { event.preventDefault(); setZoom((z) => Math.max(MIN_ZOOM, z - 0.25)); }
    else if (event.key === "0") { event.preventDefault(); setZoom(1); }
  };

  const blocks = useMemo(() => blocksOf(content), [content]);

  return <section
    ref={region}
    className="card reader-pane"
    tabIndex={-1}
    aria-label={`Reader: ${title}`}
    aria-describedby="pdf-shortcuts"
    onKeyDown={onKeyDown}
  >
    <p className="sr-only" id="pdf-shortcuts">
      Arrow keys or Page Up and Page Down change page. Plus and minus zoom. Zero fits the width.
    </p>
    <div className="pdf-toolbar">
      <div className="pdf-pager">
        <Button onClick={() => onPageChange(current - 1)} disabled={current <= 1}>Previous page</Button>
        <label>
          <span className="sr-only">Page number</span>
          <input
            className="field mono" type="number" min={1} max={pageCount || 1} value={current}
            onChange={(event) => onPageChange(Number(event.target.value) || 1)}
          />
        </label>
        <span className="mono">of {pageCount || "—"}</span>
        <Button onClick={() => onPageChange(current + 1)} disabled={!pageCount || current >= pageCount}>Next page</Button>
      </div>
      <div className="pdf-tools">
        <Button onClick={() => setZoom((z) => Math.max(MIN_ZOOM, z - 0.25))} disabled={view === "text" || zoom <= MIN_ZOOM}>Zoom out</Button>
        <span className="mono">{Math.round(zoom * 100)}%</span>
        <Button onClick={() => setZoom((z) => Math.min(MAX_ZOOM, z + 0.25))} disabled={view === "text" || zoom >= MAX_ZOOM}>Zoom in</Button>
        <Button onClick={() => onViewChange(view === "page" ? "text" : "page")}>
          {view === "page" ? "View as text" : "View as page"}
        </Button>
        <Button aria-pressed={dim} onClick={() => onDimChange(!dim)} disabled={view === "text"}>Dim page</Button>
        <Button variant="primary" disabled={!hasSelection} onClick={captureSelection}>Highlight selection</Button>
        <Button variant="ghost" onClick={onClose}>Close reader</Button>
      </div>
    </div>

    {dim && view === "page" && <Alert tone="warning">
      Colours are inverted for reading comfort. Figure colours are not authoritative in this mode.
    </Alert>}

    {error && <Alert tone="danger" title="This document could not be displayed">
      <p>{error}</p>
      <div className="toolbar">
        <Button onClick={() => setReloadKey((key) => key + 1)}>Retry</Button>
        {sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">Open the original<span className="sr-only"> (opens in a new tab)</span></a>}
      </div>
    </Alert>}

    {loading ? <LoadingBlock label="Loading document…" /> : !error && <div
      className="pdf-page-shell"
      ref={shell}
      // The shell scrolls, so it must be reachable by keyboard in its own right.
      tabIndex={0}
      role="group"
      aria-label={`Document content, page ${current}`}
    >
      {view === "page" ? <div className={`pdf-page${dim ? " dim" : ""}`} aria-label={`Page ${current} of ${pageCount}`}>
        <canvas className="pdf-canvas" ref={canvas} aria-hidden="true" />
        <div className="pdf-text-layer" ref={textLayer}>
          {content?.items.map((item, index) => <span key={index}>{item.str}</span>)}
        </div>
      </div> : <div className="pdf-text-view">
        <h3 className="sr-only">Page {current} of {pageCount}, as text</h3>
        {blocks.length ? blocks.map((block, index) => <p className="pdf-text-block" key={index}>
          {block}
          {/* The keyboard-only route to capturing a passage. */}
          <Button variant="ghost" onClick={() => capture(block)}>Quote this paragraph</Button>
        </p>) : <p className="muted">This page has no extractable text layer. It may be a scanned image.</p>}
      </div>}
    </div>}
    <p className="mono pdf-status" aria-live="polite">Page {current} of {pageCount || "—"}</p>
  </section>;
}
