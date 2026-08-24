import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { LiteratureTriage } from "./LiteratureTriage";
import type { TriageEntry, TriagePaper } from "../types";

const papers: TriagePaper[] = [
  {
    id: "p1", title: "Chilled-water setpoint study", year: 2021, venue: "Applied Energy",
    doi: "10.1/a", url: "https://openalex.org/W1", extraction_basis: "abstract",
    peer_review_confidence: "verified", selection_score: 71.5, insufficient_evidence: [],
    finding_count: 2, pdf_status: "available", pdf_sha256: "a".repeat(64),
    pdf_href: "/api/literature/pdf/" + "a".repeat(64), license: "cc-by",
  },
  {
    id: "p2", title: "Astrophysics of quasars", year: 2019, venue: "ApJ",
    doi: "10.1/b", url: "https://openalex.org/W2", extraction_basis: "abstract",
    peer_review_confidence: "likely", selection_score: 44.2,
    insufficient_evidence: ["limitations"], finding_count: 1,
    pdf_status: "unavailable", pdf_sha256: "", pdf_href: null, license: "",
  },
];

function setup(entries: Record<string, TriageEntry> = {}) {
  const props = {
    papers,
    entries: {
      p1: { paper_id: "p1", decision: "include" as const, reason: "", note: "" },
      p2: { paper_id: "p2", decision: "include" as const, reason: "", note: "" },
      ...entries,
    },
    busy: false,
    onEntryChange: vi.fn(),
    onOpenPdf: vi.fn(),
    onSubmit: vi.fn(),
  };
  return { props, ...render(<LiteratureTriage {...props} />) };
}

describe("LiteratureTriage", () => {
  it("offers the full text only where an open-access PDF exists", () => {
    setup();
    expect(screen.getAllByRole("button", { name: "Read full text" })).toHaveLength(1);
    expect(screen.getByText("no open-access full text")).toBeInTheDocument();
  });

  it("presents the decision as a radio group, not a pair of toggles", () => {
    setup();
    // Mutually exclusive choices must reach assistive technology as such.
    const include = screen.getAllByRole("radio", { name: "Include" });
    const exclude = screen.getAllByRole("radio", { name: "Exclude" });
    expect(include).toHaveLength(2);
    expect(exclude).toHaveLength(2);
    expect(include[0]).toBeChecked();
  });

  it("refuses to submit while an exclusion has no stated reason", async () => {
    setup({ p2: { paper_id: "p2", decision: "exclude", reason: "", note: "" } });
    expect(screen.getByRole("button", { name: "Confirm literature set" })).toBeDisabled();
    expect(screen.getByText(/State a reason for 1 excluded paper/)).toBeInTheDocument();
  });

  it("allows submission once every exclusion is explained", async () => {
    const { props } = setup({
      p2: { paper_id: "p2", decision: "exclude", reason: "off-topic: astrophysics", note: "" },
    });
    const submit = screen.getByRole("button", { name: "Confirm literature set" });
    expect(submit).toBeEnabled();
    await userEvent.type(screen.getByRole("textbox", { name: "Reviewer name" }), "gsw");
    await userEvent.click(submit);
    expect(props.onSubmit).toHaveBeenCalledWith("gsw");
  });

  it("refuses to submit an empty literature set", () => {
    setup({
      p1: { paper_id: "p1", decision: "exclude", reason: "superseded", note: "" },
      p2: { paper_id: "p2", decision: "exclude", reason: "off-topic", note: "" },
    });
    expect(screen.getByRole("button", { name: "Confirm literature set" })).toBeDisabled();
    expect(screen.getByText("At least one paper must be retained.")).toBeInTheDocument();
  });

  it("reports the running tally for a screen reader", () => {
    setup({ p2: { paper_id: "p2", decision: "exclude", reason: "off-topic", note: "" } });
    expect(screen.getByText("1 included · 1 excluded")).toHaveAttribute("aria-live", "polite");
  });

  it("says plainly that exclusions are recorded", () => {
    setup();
    expect(screen.getByText(/hashed into the run manifest/)).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = setup({
      p2: { paper_id: "p2", decision: "exclude", reason: "off-topic", note: "" },
    });
    const audit = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });
});
