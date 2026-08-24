import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "../api";
import type { ThesisIdea } from "../types";
import { NewRun } from "./NewRun";

const idea: ThesisIdea = {
  id: "idea-1", rank: 1, title: "Cooling resilience", research_question: "When does cooling saturate?",
  novelty: "Maps a boundary.", feasibility: "Registry supported.", contribution: "Risk map.", risks: ["Conceptual model"],
  supporting_paper_ids: ["p1"], model_names: ["DataCenterRoom"], rank_score: 92,
  rank_explanation: "Strong model fit.", ranking_factors: { model_fit: 1 }, provider_status: "degraded",
  provider_warnings: ["Semantic Scholar returned no results."],
};

describe("NewRun", () => {
  beforeEach(() => sessionStorage.clear());

  it("supports ranked idea selection, editing, and confirmation", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "thesisIdeas").mockResolvedValue([idea, { ...idea, id: "idea-2", rank: 2, title: "Energy setpoints" }]);
    const openRun = vi.fn();
    vi.spyOn(api, "createRun").mockResolvedValue({ run_id: "run-1" });
    render(<NewRun goDashboard={vi.fn()} openRun={openRun} />);

    await user.click(screen.getByRole("button", { name: /generate five thesis ideas/i }));
    expect(await screen.findByText("Reduced provider coverage")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: /select this idea/i })[0]);
    const title = screen.getByRole("textbox", { name: "Selected idea title" });
    await user.clear(title); await user.type(title, "Edited resilience topic");
    await user.click(screen.getByRole("button", { name: /configure run/i }));
    expect(screen.getByDisplayValue("Edited resilience topic")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /review/i }));
    expect(screen.getByText("Ranked thesis idea #1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /start run/i }));
    await waitFor(() => expect(openRun).toHaveBeenCalledWith("run-1"));
  });

  it("keeps direct topic entry available", async () => {
    const user = userEvent.setup();
    const { container } = render(<NewRun goDashboard={vi.fn()} openRun={vi.fn()} />);
    expect(screen.getByRole("textbox", { name: "Domain" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /enter topic directly/i }));
    expect(screen.getByRole("heading", { name: "Enter a research topic" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Research topic" })).toBeInTheDocument();
    const audit = await axe(container, { rules: { "color-contrast": { enabled: false } } });
    expect(audit.violations).toEqual([]);
  });

  it("restores generated ideas and configuration after the wizard remounts", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "thesisIdeas").mockResolvedValue([idea]);
    const first = render(<NewRun goDashboard={vi.fn()} openRun={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: /generate five thesis ideas/i }));
    await user.click(await screen.findByRole("button", { name: /select this idea/i }));
    await user.click(screen.getByRole("button", { name: /configure run/i }));
    await user.type(screen.getByRole("textbox", { name: "New constraint" }), "preserve evidence");
    await user.click(screen.getByRole("button", { name: "Add" }));
    first.unmount();

    render(<NewRun goDashboard={vi.fn()} openRun={vi.fn()} />);
    expect(screen.getByText("Draft restored")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Research topic" })).toHaveValue("Cooling resilience");
    expect(screen.getByText("preserve evidence")).toBeInTheDocument();
  });
});
