import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { api } from "../api";
import { Models } from "./Models";

describe("Models", () => {
  it("keeps conceptual status and reference-case validation visible", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "models").mockResolvedValue({ DataCenterRoom: {
      description: "Lumped room", default_stop_time: 3600, outputs: ["T"], parameters: {},
      validation_status: "conceptual", model_version: "1.0", validation_report_id: "v1",
      limitations: ["Not empirically calibrated."], operating_range: {},
    } });
    vi.spyOn(api, "modelValidation").mockResolvedValue({
      id: "v1", model_name: "DataCenterRoom", model_version: "1.0", status: "conceptual", checks_status: "passed", generated_at: "2026-01-01",
      assumptions: [], operating_range: {}, tolerances: {}, limitations: ["Not empirically calibrated."], disclosure: "Exploratory only.",
      reference_cases: [{ id: "energy", name: "Energy balance", status: "passed", tolerance: "1e-9 W", observed: "0 W", expected: "0 W", details: "" }],
    });
    render(<Models />);
    expect(await screen.findByText("conceptual")).toBeInTheDocument();
    expect(screen.getByText("Not empirically calibrated.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /view validation details/i }));
    expect(await screen.findByText("Energy balance")).toBeInTheDocument();
  });

  it("switches registered models and uses the dedicated quick-simulation series contract", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "models").mockResolvedValue({
      DataCenterRoom: {
        description: "Lumped room", default_stop_time: 3600, outputs: ["T"],
        parameters: { Q_it: { default: 60000, min: 10000, max: 120000, unit: "W", description: "IT load" } },
        validation_status: "conceptual", model_version: "1.0", validation_report_id: "v1", limitations: ["Exploratory."], operating_range: {},
      },
      PlantModel: {
        description: "Plant benchmark", default_stop_time: 7200, outputs: ["T"],
        parameters: { load: { default: 50, min: 10, max: 100, unit: "%", description: "Plant load" } },
        validation_status: "validated", model_version: "2.0", validation_report_id: "v2", limitations: [], operating_range: {},
      },
    });
    vi.spyOn(api, "modelValidation").mockResolvedValue({
      id: "v", model_name: "model", model_version: "1", status: "conceptual", checks_status: "passed", generated_at: "2026-01-01",
      assumptions: [], operating_range: {}, tolerances: {}, limitations: [], disclosure: "", reference_cases: [],
    });
    const simulate = vi.spyOn(api, "simulate").mockResolvedValue({
      spec_id: "manual-abcdef", case_id: "manual-abcdef", model_name: "PlantModel", parameters: { load: 75 }, status: "ok",
      workdir: "/tmp/sim", result_file: "/tmp/sim/result.csv", metrics: { T_peak_degC: 27.5 }, log_excerpt: "ok",
      validation_status: "validated", warnings: [], validation_report_id: "v2",
    });
    const simulationSeries = vi.spyOn(api, "simulationSeries").mockResolvedValue({ time: [0, 7200], T: [27, 25] });

    render(<Models />);
    const selector = await screen.findByRole("combobox", { name: "Registered model" });
    await user.selectOptions(selector, "PlantModel");
    expect(await screen.findByText("Plant benchmark")).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Stop time" })).toHaveValue(7200);

    const exact = screen.getByRole("spinbutton", { name: "load exact value" });
    await user.clear(exact); await user.type(exact, "75");
    await user.click(screen.getByRole("button", { name: "Run simulation" }));
    expect(simulate).toHaveBeenCalledWith("PlantModel", { load: 75 }, 7200);
    expect(simulationSeries).toHaveBeenCalledWith("manual-abcdef");
    expect(await screen.findByRole("img", { name: /Room temperature, 2 samples/i })).toBeInTheDocument();
  });
});
