import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api";
import type { ReportDocument } from "../types";
import { ReportWorkspace } from "./ReportWorkspace";

const document: ReportDocument = {
  schema_version: 1, version: 1, run_id: "r1", created_at: "2026-01-01", updated_at: "2026-01-01", migrated_from_legacy: false,
  metadata: { title: "Report", run_id: "r1", authors: [], abstract: "", keywords: [], disclosures: ["Conceptual model"] },
  sections: [{ id: "introduction", title: "Introduction", kind: "introduction", content: "Original", locked: false, generated: true, stale: false, citation_ids: [], evidence_ids: ["comparison-1"], generated_content: "Original", updated_at: "2026-01-01" }],
  references: [], figures: [], evidence_links: [],
};

describe("ReportWorkspace", () => {
  it("autosaves sections and exposes revisions and export controls", async () => {
    const user = userEvent.setup();
    const onEvidenceSelect = vi.fn();
    vi.spyOn(api, "reportDocument").mockResolvedValue(document);
    vi.spyOn(api, "reportValidation").mockResolvedValue({ valid: true, errors: 0, warnings: 0, issues: [], version: 1 });
    const update = vi.spyOn(api, "updateReportSection").mockImplementation(async (_run, _section, changes) => ({
      ...document, version: 2, sections: [{ ...document.sections[0], content: String(changes.content) }],
    }));
    vi.spyOn(api, "reportRevisions").mockResolvedValue([{ id: "v1", version: 1, created_at: "2026-01-01", summary: "Initial" }]);
    render(<ReportWorkspace runId="r1" warnings={["Exploratory only"]} onEvidenceSelect={onEvidenceSelect} />);

    const editor = await screen.findByRole("textbox", { name: "Edit Introduction" });
    fireEvent.change(editor, { target: { value: "Manual edit" } });
    await waitFor(() => expect(update).toHaveBeenCalledWith("r1", "introduction", { content: "Manual edit", expected_version: 1 }), { timeout: 1800 });
    expect(screen.getByLabelText("Live report preview")).toHaveTextContent("Manual edit");
    await user.click(screen.getByRole("button", { name: "Revision history" }));
    expect(await screen.findByText(/Initial/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Export DOCX" })).toBeInTheDocument();
    expect(screen.getByText("Exploratory evidence")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "evidence comparison-1" }));
    expect(onEvidenceSelect).toHaveBeenCalledWith("comparison-1");
  });
});
