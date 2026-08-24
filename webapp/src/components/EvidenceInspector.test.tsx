import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { EvidenceInspector } from "./EvidenceInspector";
import type { EvidenceAnnotation, PaperCard } from "../types";

const paper: PaperCard = {
  id: "https://openalex.org/W1", title: "Chilled-water setpoint study", year: 2021,
  doi: "10.1/a", url: "https://openalex.org/W1", venue: "Applied Energy", authors: ["A"],
  citations: 42, abstract: "An abstract.", problem: "Cooling energy", method: "Simulation",
  metrics: ["E"], limitations: ["single site"], findings: [], study_conditions: [],
  tags: ["cooling"], publication_type: "article", peer_review_confidence: "verified",
  credibility_explanation: "Corroborated.", provenance: ["openalex"], selection_score: 71.5,
  ranking_factors: {}, extraction_basis: "abstract",
  pdf: {
    status: "available", sha256: "a".repeat(64), bytes: 10, page_count: 4,
    source_url: "", landing_page_url: "", oa_status: "gold", license: "cc-by",
    oa_version: "", provider: "openalex", content_type: "application/pdf",
    http_status: 200, error: "", retrieved_at: "", attempted_urls: [],
  },
};

const annotation: EvidenceAnnotation = {
  id: "ann-1", run_id: "run-1", evidence_id: `paper:${paper.id}`, evidence_kind: "",
  evidence_fingerprint: "", kind: "flag", severity: "blocker",
  body: "This paper does not support the claim it is cited for.",
  proposed_value: "", applied: false, anchor: null, author: "gsw",
  created_at: "2026-08-17T09:00:00Z", supersedes: null, resolved: false, resolution_note: "",
};

function setup(overrides = {}) {
  const props = {
    evidenceId: `paper:${paper.id}`,
    results: null, plan: null, papers: [paper], claims: null,
    onClose: vi.fn(),
    annotations: [annotation],
    onAnnotate: vi.fn().mockResolvedValue(undefined),
    onResolveAnnotation: vi.fn(),
    onOpenPdf: vi.fn(),
    ...overrides,
  };
  return { props, ...render(<EvidenceInspector {...props} />) };
}

describe("EvidenceInspector annotations", () => {
  it("keeps exactly one dialog in the tree when the composer opens", async () => {
    // Dialog hardcodes aria-labelledby="dialog-title"; a nested one would produce a
    // duplicate id and two competing focus traps. The composer is inline for that reason.
    setup();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: /Add comment, dispute or correction/ }));
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("shows an existing dispute with its blocking status", () => {
    setup();
    expect(screen.getByText("dispute")).toBeInTheDocument();
    expect(screen.getByText("blocks acceptance")).toBeInTheDocument();
    expect(screen.getByText(/does not support the claim/)).toBeInTheDocument();
  });

  it("offers the full text when the paper has a cached open-access PDF", async () => {
    const { props } = setup();
    await userEvent.click(screen.getByRole("button", { name: "Read the full text" }));
    expect(props.onOpenPdf).toHaveBeenCalledWith(paper.id);
  });

  it("does not offer a reader for a paper without full text", () => {
    setup({ papers: [{ ...paper, pdf: { ...paper.pdf!, status: "unavailable" as const } }] });
    expect(screen.queryByRole("button", { name: "Read the full text" })).not.toBeInTheDocument();
  });

  it("submits a well-formed draft and says corrections are only proposals", async () => {
    const { props } = setup({ annotations: [] });
    await userEvent.click(screen.getByRole("button", { name: /Add comment, dispute or correction/ }));
    await userEvent.click(screen.getByRole("radio", { name: /Correction/ }));
    await userEvent.type(screen.getByRole("textbox", { name: "Remark" }), "The method is CFD.");
    await userEvent.type(screen.getByRole("textbox", { name: "Proposed value" }), "CFD");
    await userEvent.type(screen.getByRole("textbox", { name: "Your name" }), "gsw");
    await userEvent.click(screen.getByRole("button", { name: "Save annotation" }));

    expect(vi.mocked(props.onAnnotate)).toHaveBeenCalledWith({
      evidence_id: `paper:${paper.id}`, kind: "correction", severity: "info",
      body: "The method is CFD.", author: "gsw", proposed_value: "CFD",
    });
  });

  it("states that annotations never change the deterministic checks", async () => {
    setup({ annotations: [] });
    await userEvent.click(screen.getByRole("button", { name: /Add comment, dispute or correction/ }));
    expect(screen.getByText(/never changes the deterministic checks/)).toBeInTheDocument();
  });

  it("cannot save an empty remark", async () => {
    setup({ annotations: [] });
    await userEvent.click(screen.getByRole("button", { name: /Add comment, dispute or correction/ }));
    expect(screen.getByRole("button", { name: "Save annotation" })).toBeDisabled();
  });

  it("has no accessibility violations with the composer open", async () => {
    const { container } = setup();
    await userEvent.click(screen.getByRole("button", { name: /Add comment, dispute or correction/ }));
    const audit = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });
});
