/**
 * The only module in the app that imports pdfjs-dist.
 *
 * Everything else talks to the narrow interface below, which is what makes the
 * viewer testable: jsdom can neither rasterize a canvas nor run a web worker, so
 * unit tests mock this module and still exercise the text layer, keyboard
 * navigation, and highlight maths for real.
 */

export interface PdfTextItem {
  str: string;
  transform: number[];
  width: number;
  height: number;
  hasEOL: boolean;
}

export interface PdfViewportSize {
  width: number;
  height: number;
}

export interface PdfPageText {
  items: PdfTextItem[];
  text: string;
  viewport: PdfViewportSize;
}

export interface PdfDocumentHandle {
  pageCount: number;
  renderPage(page: number, canvas: HTMLCanvasElement, cssWidth: number, zoom: number): Promise<PdfViewportSize>;
  pageText(page: number): Promise<PdfPageText>;
  destroy(): void;
}

export interface PdfEngine {
  load(url: string, signal?: AbortSignal): Promise<PdfDocumentHandle>;
}

let cached: Promise<PdfEngine> | null = null;

/** Loaded lazily so pdfjs stays out of the main bundle. */
export function pdfEngine(): Promise<PdfEngine> {
  if (!cached) cached = createEngine();
  return cached;
}

async function createEngine(): Promise<PdfEngine> {
  const pdfjs = await import("pdfjs-dist");
  // `?worker` lets Vite bundle the worker as a first-class asset and construct it
  // itself. Setting `workerSrc` to a URL instead would have to resolve under the
  // FastAPI static mount and be served with a JS MIME type -- a needless surface.
  const PdfWorker = (await import("pdfjs-dist/build/pdf.worker.min.mjs?worker")).default;
  pdfjs.GlobalWorkerOptions.workerPort = new PdfWorker();

  return {
    async load(url, signal) {
      const task = pdfjs.getDocument({
        url,
        // Range/streaming are disabled for now so behaviour is identical under the
        // dev proxy, a Playwright route fulfilment, and FastAPI. The cost is that a
        // paper downloads fully before the first page paints.
        disableRange: true,
        disableStream: true,
        // pdf.js otherwise evaluates font programs, which would need unsafe-eval.
        isEvalSupported: false,
      });
      signal?.addEventListener("abort", () => void task.destroy(), { once: true });
      const doc = await task.promise;

      return {
        pageCount: doc.numPages,
        async renderPage(pageNumber, canvas, cssWidth, zoom) {
          const page = await doc.getPage(pageNumber);
          const base = page.getViewport({ scale: 1 });
          const ratio = Math.min(window.devicePixelRatio || 1, 2);
          const scale = (cssWidth / base.width) * zoom;
          const viewport = page.getViewport({ scale });
          canvas.width = Math.floor(viewport.width * ratio);
          canvas.height = Math.floor(viewport.height * ratio);
          const context = canvas.getContext("2d");
          if (context) {
            context.setTransform(ratio, 0, 0, ratio, 0, 0);
            await page.render({ canvasContext: context, viewport }).promise;
          }
          return { width: viewport.width, height: viewport.height };
        },
        async pageText(pageNumber) {
          const page = await doc.getPage(pageNumber);
          const content = await page.getTextContent();
          // getTextContent yields marked-content markers alongside real text runs.
          const items = content.items
            .filter((item): item is import("pdfjs-dist/types/src/display/api").TextItem =>
              "str" in item)
            .map((item) => ({
              str: item.str,
              transform: item.transform,
              width: item.width,
              height: item.height,
              hasEOL: item.hasEOL,
            }));
          const base = page.getViewport({ scale: 1 });
          return {
            items,
            text: items.map((item) => item.str + (item.hasEOL ? "\n" : "")).join(""),
            viewport: { width: base.width, height: base.height },
          };
        },
        destroy() {
          void doc.destroy();
        },
      };
    },
  };
}
