import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { axe } from "vitest-axe";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api";
import type { PaperCard } from "../types";
import { KnowledgeBase } from "./KnowledgeBase";

const base: PaperCard = {
  id: "journal", title: "Journal study", year: 2024, doi: "10.1/x", url: null, venue: "Energy",
  authors: [], citations: 10, abstract: "", problem: "cooling", method: "simulation", metrics: [], limitations: [], findings: [], study_conditions: [], tags: ["cooling"],
  publication_type: "journal-article", peer_review_confidence: "verified", credibility_explanation: "DOI corroborated.",
  provenance: ["crossref"], selection_score: 88, ranking_factors: { relevance: 0.9, credibility: 1 },
};

describe("KnowledgeBase", () => {
  it("shows credibility details and filters preprints", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "memoryTopics").mockResolvedValue([{ slug: "cooling", cards: 2, snapshot: "s1" }]);
    vi.spyOn(api, "memoryDetail").mockResolvedValue({
      slug: "cooling", snapshot: "s1", themes: { cooling: ["Journal study", "Preprint study"] },
      paper_cards: [base, { ...base, id: "pre", title: "Preprint study", publication_type: "preprint", peer_review_confidence: "preprint", selection_score: 55 }],
    });
    const { container } = render(<MemoryRouter><KnowledgeBase /></MemoryRouter>);
    expect(await screen.findByText("Journal study")).toBeInTheDocument();
    expect(screen.getByText("peer review verified")).toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "Peer review filter" }), "preprint");
    await waitFor(() => expect(screen.queryByText("Journal study")).not.toBeInTheDocument());
    expect(screen.getByText("Preprint study")).toBeInTheDocument();
    await user.click(screen.getByText("Why selected"));
    expect(screen.getByText("DOI corroborated.")).toBeInTheDocument();
    const audit = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });

  it("ignores a stale snapshot response after the researcher switches topics", async () => {
    const user = userEvent.setup();
    let resolveCooling!: (detail: { slug: string; snapshot: string; themes: Record<string, string[]>; paper_cards: PaperCard[] }) => void;
    let resolveResilience!: (detail: { slug: string; snapshot: string; themes: Record<string, string[]>; paper_cards: PaperCard[] }) => void;
    const cooling = new Promise<Parameters<typeof resolveCooling>[0]>((resolve) => { resolveCooling = resolve; });
    const resilience = new Promise<Parameters<typeof resolveResilience>[0]>((resolve) => { resolveResilience = resolve; });
    vi.spyOn(api, "memoryTopics").mockResolvedValue([
      { slug: "cooling", cards: 1, snapshot: "s1" },
      { slug: "resilience", cards: 1, snapshot: "s2" },
    ]);
    const detail = vi.spyOn(api, "memoryDetail").mockImplementation((slug) => slug === "cooling" ? cooling : resilience);

    render(<MemoryRouter initialEntries={["/knowledge?topic=cooling"]}><KnowledgeBase /></MemoryRouter>);
    await waitFor(() => expect(detail).toHaveBeenCalledWith("cooling"));
    await user.click(screen.getByRole("button", { name: /resilience/i }));
    await waitFor(() => expect(detail).toHaveBeenCalledWith("resilience"));

    await act(async () => resolveResilience({ slug: "resilience", snapshot: "s2", themes: {}, paper_cards: [{ ...base, id: "resilience-paper", title: "Resilience paper" }] }));
    expect(await screen.findByText("Resilience paper")).toBeInTheDocument();
    await act(async () => resolveCooling({ slug: "cooling", snapshot: "s1", themes: {}, paper_cards: [{ ...base, id: "late-paper", title: "Late cooling response" }] }));
    expect(screen.getByText("Resilience paper")).toBeInTheDocument();
    expect(screen.queryByText("Late cooling response")).not.toBeInTheDocument();
  });
});
