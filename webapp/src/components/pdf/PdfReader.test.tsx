import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import PdfReader from "./PdfReader";

const PAGES: Record<number, string> = {
  1: "Data centre cooling was studied across nine matched pairs of simulation cases here.",
  2: "Raising the chilled-water setpoint from six to ten degrees reduced chiller energy by fourteen percent overall.",
  3: "Limitations remain: the model is conceptual and has not been calibrated against a physical facility.",
};

// pdfjs-dist never enters the jsdom module graph. Mocking at this seam keeps the
// text layer, the text view, keyboard navigation, and the capture flow real.
vi.mock("./pdfEngine", () => ({
  pdfEngine: async () => ({
    load: async () => ({
      pageCount: 3,
      renderPage: async () => ({ width: 600, height: 800 }),
      pageText: async (page: number) => ({
        items: [{ str: PAGES[page], transform: [], width: 400, height: 12, hasEOL: true }],
        text: PAGES[page],
        viewport: { width: 600, height: 800 },
      }),
      destroy: () => undefined,
    }),
  }),
}));

function setup(overrides: Partial<React.ComponentProps<typeof PdfReader>> = {}) {
  const props = {
    paperId: "https://openalex.org/W1",
    sha256: "a".repeat(64),
    title: "Cooling-aware energy management",
    page: 1,
    view: "page" as const,
    dim: false,
    onPageChange: vi.fn(),
    onViewChange: vi.fn(),
    onDimChange: vi.fn(),
    onCapture: vi.fn(),
    onClose: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<PdfReader {...props} />) };
}

describe("PdfReader", () => {
  it("shows the page position once the document loads", async () => {
    setup();
    await waitFor(() => expect(screen.getByText("of 3")).toBeInTheDocument());
    expect(screen.getByRole("spinbutton", { name: "Page number" })).toHaveValue(1);
  });

  it("pages forward from the toolbar", async () => {
    const { props } = setup();
    await waitFor(() => expect(screen.getByText("of 3")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(props.onPageChange).toHaveBeenCalledWith(2);
  });

  it("pages with the keyboard without hijacking the rest of the app", async () => {
    const { props } = setup({ page: 2 });
    await waitFor(() => expect(screen.getByText("of 3")).toBeInTheDocument());
    const region = screen.getByRole("region", { name: /Reader:/ });
    region.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(props.onPageChange).toHaveBeenCalledWith(3);
    await userEvent.keyboard("{ArrowLeft}");
    expect(props.onPageChange).toHaveBeenCalledWith(1);
  });

  it("hides the raster from assistive technology", async () => {
    const { container } = setup();
    await waitFor(() => expect(screen.getByText("of 3")).toBeInTheDocument());
    expect(container.querySelector("canvas")).toHaveAttribute("aria-hidden", "true");
    expect(container.querySelector(".pdf-text-layer")).toBeTruthy();
  });

  it("offers a keyboard-only route to capturing a passage in the text view", async () => {
    const { props } = setup({ view: "text", page: 2 });
    await waitFor(() => expect(screen.getByText(/Raising the chilled-water setpoint/)).toBeInTheDocument());
    const onCapture = vi.mocked(props.onCapture);
    await userEvent.click(screen.getByRole("button", { name: "Quote this paragraph" }));
    expect(onCapture).toHaveBeenCalledTimes(1);
    const anchor = onCapture.mock.calls[0][0];
    expect(anchor.page).toBe(2);
    expect(anchor.quote).toContain("reduced chiller energy by fourteen percent");
    expect(anchor.paper_id).toBe("https://openalex.org/W1");
  });

  it("discloses that dimming makes figure colours unauthoritative", async () => {
    setup({ dim: true });
    await waitFor(() => expect(screen.getByText("of 3")).toBeInTheDocument());
    expect(screen.getByText(/Figure colours are not authoritative/)).toBeInTheDocument();
  });

  it("cannot capture a highlight until something is selected", async () => {
    setup();
    await waitFor(() => expect(screen.getByText("of 3")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Highlight selection" })).toBeDisabled();
  });

  it("has no accessibility violations in either view", async () => {
    const { container, unmount } = setup();
    await waitFor(() => expect(screen.getByText("of 3")).toBeInTheDocument());
    const page = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(page.violations).toEqual([]);
    unmount();

    const text = setup({ view: "text" });
    await waitFor(() => expect(screen.getByText("of 3")).toBeInTheDocument());
    const audit = await axe(text.container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });
});
