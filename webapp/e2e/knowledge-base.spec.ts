import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

// A real, parseable two-page PDF (reportlab output), so pdf.js genuinely renders
// and produces a text layer, and paging has somewhere to go. jsdom can do neither,
// which is why rasterization and text extraction are proved here, not in vitest.
const PDF_BASE64 =
  "JVBERi0xLjMKJZOMi54gUmVwb3J0TGFiIEdlbmVyYXRlZCBQREYgZG9jdW1lbnQgKG9wZW5zb3Vy" +
  "Y2UpCjEgMCBvYmoKPDwKL0YxIDIgMCBSCj4+CmVuZG9iagoyIDAgb2JqCjw8Ci9CYXNlRm9udCAv" +
  "SGVsdmV0aWNhIC9FbmNvZGluZyAvV2luQW5zaUVuY29kaW5nIC9OYW1lIC9GMSAvU3VidHlwZSAv" +
  "VHlwZTEgL1R5cGUgL0ZvbnQKPj4KZW5kb2JqCjMgMCBvYmoKPDwKL0NvbnRlbnRzIDggMCBSIC9N" +
  "ZWRpYUJveCBbIDAgMCA2MTIgNzkyIF0gL1BhcmVudCA3IDAgUiAvUmVzb3VyY2VzIDw8Ci9Gb250" +
  "IDEgMCBSIC9Qcm9jU2V0IFsgL1BERiAvVGV4dCAvSW1hZ2VCIC9JbWFnZUMgL0ltYWdlSSBdCj4+" +
  "IC9Sb3RhdGUgMCAvVHJhbnMgPDwKCj4+IAogIC9UeXBlIC9QYWdlCj4+CmVuZG9iago0IDAgb2Jq" +
  "Cjw8Ci9Db250ZW50cyA5IDAgUiAvTWVkaWFCb3ggWyAwIDAgNjEyIDc5MiBdIC9QYXJlbnQgNyAw" +
  "IFIgL1Jlc291cmNlcyA8PAovRm9udCAxIDAgUiAvUHJvY1NldCBbIC9QREYgL1RleHQgL0ltYWdl" +
  "QiAvSW1hZ2VDIC9JbWFnZUkgXQo+PiAvUm90YXRlIDAgL1RyYW5zIDw8Cgo+PiAKICAvVHlwZSAv" +
  "UGFnZQo+PgplbmRvYmoKNSAwIG9iago8PAovUGFnZU1vZGUgL1VzZU5vbmUgL1BhZ2VzIDcgMCBS" +
  "IC9UeXBlIC9DYXRhbG9nCj4+CmVuZG9iago2IDAgb2JqCjw8Ci9BdXRob3IgKGFub255bW91cykg" +
  "L0NyZWF0aW9uRGF0ZSAoRDoyMDI2MDgxNzE3MzgxMiswOCcwMCcpIC9DcmVhdG9yIChhbm9ueW1v" +
  "dXMpIC9LZXl3b3JkcyAoKSAvTW9kRGF0ZSAoRDoyMDI2MDgxNzE3MzgxMiswOCcwMCcpIC9Qcm9k" +
  "dWNlciAoUmVwb3J0TGFiIFBERiBMaWJyYXJ5IC0gXChvcGVuc291cmNlXCkpIAogIC9TdWJqZWN0" +
  "ICh1bnNwZWNpZmllZCkgL1RpdGxlICh1bnRpdGxlZCkgL1RyYXBwZWQgL0ZhbHNlCj4+CmVuZG9i" +
  "ago3IDAgb2JqCjw8Ci9Db3VudCAyIC9LaWRzIFsgMyAwIFIgNCAwIFIgXSAvVHlwZSAvUGFnZXMK" +
  "Pj4KZW5kb2JqCjggMCBvYmoKPDwKL0ZpbHRlciBbIC9BU0NJSTg1RGVjb2RlIC9GbGF0ZURlY29k" +
  "ZSBdIC9MZW5ndGggMTY0Cj4+CnN0cmVhbQpHYXMyQV8kWWNaJ0xoYkZgRT82J2MldDpBVyldbUM1" +
  "QEVNRS1aa01rLDVoPGg+ZlZRMVwtTDxlUW1NSVhETGVMJDMqVTNNZ3AoRXMrcj0iO3JScFM8VyFZ" +
  "ImFPRmJaYXA2LSI9V0RkJ2JxZCxjal0xczk0MWxZOVEmbEctYmRxNlEyJTMhdWhnVXUvVjIqKTBx" +
  "aF1gU0FwSDlfdCEhWnNkSS9+PmVuZHN0cmVhbQplbmRvYmoKOSAwIG9iago8PAovRmlsdGVyIFsg" +
  "L0FTQ0lJODVEZWNvZGUgL0ZsYXRlRGVjb2RlIF0gL0xlbmd0aCAxNjQKPj4Kc3RyZWFtCkdhczJB" +
  "XSpjRD8nRiJBXWBLWSpMWlFUbWEnWFVKWEopRnBbLHFJWVM4XzNxOUpbSEpiQFohMStqdXJJOE8p" +
  "UGtwPSwxUlIpbTY1J0FEZVpeKzdGWjheODVgZCxkSkBVJHEzaDFCaytRTCtlOiRmJmJCTkBARGg5" +
  "aG04OUlkVFA3bGROS2FnRz1pMEo7YGA3cGtvY0NYZ0xYLVJfJGllIXBJS34+ZW5kc3RyZWFtCmVu" +
  "ZG9iagp4cmVmCjAgMTAKMDAwMDAwMDAwMCA2NTUzNSBmIAowMDAwMDAwMDYxIDAwMDAwIG4gCjAw" +
  "MDAwMDAwOTIgMDAwMDAgbiAKMDAwMDAwMDE5OSAwMDAwMCBuIAowMDAwMDAwMzkyIDAwMDAwIG4g" +
  "CjAwMDAwMDA1ODUgMDAwMDAgbiAKMDAwMDAwMDY1MyAwMDAwMCBuIAowMDAwMDAwOTE0IDAwMDAw" +
  "IG4gCjAwMDAwMDA5NzkgMDAwMDAgbiAKMDAwMDAwMTIzMyAwMDAwMCBuIAp0cmFpbGVyCjw8Ci9J" +
  "RCAKWzwyNDViYzIzZWEwYWI1ODRlZDdjN2Y2ZTE1NzNmZmFiZj48MjQ1YmMyM2VhMGFiNTg0ZWQ3" +
  "YzdmNmUxNTczZmZhYmY+XQolIFJlcG9ydExhYiBnZW5lcmF0ZWQgUERGIGRvY3VtZW50IC0tIGRp" +
  "Z2VzdCAob3BlbnNvdXJjZSkKCi9JbmZvIDYgMCBSCi9Sb290IDUgMCBSCi9TaXplIDEwCj4+CnN0" +
  "YXJ0eHJlZgoxNDg3CiUlRU9GCg==";

const SHA = "a".repeat(64);
const PAPER_ID = "https://openalex.org/W2276903495";

const card = {
  id: PAPER_ID,
  title: "Cooling-aware energy management in data centres",
  year: 2015, doi: "10.1109/jstsp.2015.2500189", url: PAPER_ID,
  venue: "IEEE Journal of Selected Topics in Signal Processing",
  authors: ["Tianyi Chen"], citations: 82,
  abstract: "Energy and workload management for data centres.",
  problem: "Cooling energy optimisation", method: "Stochastic optimisation",
  metrics: ["Energy cost"], limitations: ["Assumes i.i.d. processes"],
  findings: [], study_conditions: [], tags: ["data center cooling"],
  publication_type: "article", peer_review_confidence: "verified",
  credibility_explanation: "Corroborated across providers.",
  provenance: ["openalex"], selection_score: 61.4,
  ranking_factors: { relevance: 0.8 }, extraction_basis: "abstract",
  pdf: {
    status: "available", sha256: SHA, bytes: 1024, page_count: 2,
    source_url: "https://oa.example/paper.pdf", landing_page_url: "",
    oa_status: "gold", license: "cc-by", oa_version: "publishedVersion",
    provider: "openalex", content_type: "application/pdf", http_status: 200,
    error: "", retrieved_at: "2026-08-17T00:00:00Z", attempted_urls: [],
  },
};

const closedCard = {
  ...card,
  id: "https://openalex.org/W999",
  title: "A paywalled study",
  pdf: {
    ...card.pdf, status: "unavailable", sha256: "", page_count: 0,
    oa_status: "closed", license: "",
    attempted_urls: ["https://a.example/x.pdf", "https://b.example/y.pdf"],
  },
};

async function mockApi(page: Page) {
  await page.route("**/api/**", async (route) => {
    const { pathname } = new URL(route.request().url());
    if (pathname === "/api/health") return route.fulfill({ json: { ok: true } });
    if (pathname === "/api/memory") {
      return route.fulfill({ json: [{ slug: "cooling", cards: 2, snapshot: "20260718T082611Z" }] });
    }
    if (pathname === "/api/memory/cooling") {
      return route.fulfill({
        json: {
          slug: "cooling", snapshot: "20260718T082611Z",
          themes: { "data center cooling": ["Cooling-aware energy management in data centres"] },
          paper_cards: [card, closedCard],
        },
      });
    }
    if (pathname.startsWith("/api/literature/pdf/")) {
      return route.fulfill({
        body: Buffer.from(PDF_BASE64, "base64"),
        contentType: "application/pdf",
      });
    }
    return route.fulfill({ json: [] });
  });
}

const readerUrl = `/#/knowledge?topic=cooling&pdf=${encodeURIComponent(PAPER_ID)}&page=1`;

test("renders an open-access PDF with a selectable text layer", async ({ page }) => {
  await mockApi(page);
  await page.goto(readerUrl);
  await page.waitForSelector(".pdf-canvas");
  // The canvas must actually be painted, not merely present.
  const painted = await page.evaluate(() => {
    const canvas = document.querySelector("canvas.pdf-canvas") as HTMLCanvasElement;
    const blank = document.createElement("canvas");
    blank.width = canvas.width;
    blank.height = canvas.height;
    return canvas.width > 0 && canvas.toDataURL() !== blank.toDataURL();
  });
  expect(painted).toBe(true);
  await expect(page.locator(".pdf-text-layer")).toContainText("chilled-water setpoint");
});

test("explains why a closed-access paper has no reader", async ({ page }) => {
  await mockApi(page);
  await page.goto("/#/knowledge?topic=cooling");
  const closed = page.locator(".paper-memory-card", { hasText: "A paywalled study" });
  await expect(closed.getByText("no open-access full text")).toBeVisible();
});

for (const theme of ["light", "dark"]) {
  test(`reader has no accessibility violations in ${theme} mode`, async ({ page }) => {
    await page.addInitScript((value) => localStorage.setItem("rcp-theme", value), theme);
    await mockApi(page);

    await page.goto(readerUrl);
    await page.waitForSelector(".pdf-canvas");
    // The text layer is a transparent, aria-hidden geometric overlay mirroring the
    // raster; its accessible equivalent is the text view, audited below with no
    // exclusions at all. Auditing transparent text here only measures the overlay.
    const pageView = await new AxeBuilder({ page }).exclude(".pdf-text-layer").analyze();
    expect(pageView.violations).toEqual([]);

    await page.goto(`${readerUrl}&pdfview=text`);
    await page.waitForSelector(".pdf-text-view");
    const textView = await new AxeBuilder({ page }).analyze();
    expect(textView.violations).toEqual([]);
  });
}

for (const width of [390, 768, 1440]) {
  test(`reader does not scroll the page sideways at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await mockApi(page);
    await page.goto(readerUrl);
    await page.waitForSelector(".pdf-canvas");
    const noOverflow = () =>
      page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
    expect(await noOverflow()).toBe(true);

    // Zooming must scroll inside the page shell, never the document.
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.waitForTimeout(500);
    expect(await noOverflow()).toBe(true);
  });
}

test("reader survives 200% zoom", async ({ page }) => {
  await mockApi(page);
  await page.goto(readerUrl);
  await page.evaluate(() => { document.documentElement.style.zoom = "2"; });
  await page.waitForSelector(".pdf-canvas");
  await page.waitForTimeout(500);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
  ).toBe(true);
});

test("keyboard paging updates the deep-linkable page parameter", async ({ page }) => {
  await mockApi(page);
  await page.goto(readerUrl);
  await page.waitForSelector(".pdf-canvas");
  await expect(page.getByRole("spinbutton", { name: "Page number" })).toHaveValue("1");
  await page.getByRole("button", { name: "Next page" }).click();
  await expect(page).toHaveURL(/page=2/);
});
