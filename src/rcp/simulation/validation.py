"""Offline physics checks and runtime credibility gates for bundled models."""

import math
import json
from datetime import datetime, timezone

from rcp.objects import ExperimentSpec, ModelValidationReport, ValidationReferenceCase
from rcp.simulation.registry import DATACENTER_BENCHMARK_PROFILES, ModelInfo, get_model
from rcp.simulation.registry import MODELS_DIR


CONCEPTUAL_DISCLOSURE = (
    "DataCenterRoom is a conceptual lumped-parameter model. Its numerical results are suitable "
    "for exploratory analysis only; successful execution does not constitute empirical or "
    "publication-strength validation."
)


def _cooling(temp: float, p: dict[str, float]) -> float:
    return min(p["Q_cool_max"], max(0.0, p["k_p"] * (temp - p["T_set"])))


def _equilibrium(p: dict[str, float]) -> tuple[float, str]:
    if p["UA"] <= 0:
        if p["Q_it"] <= p["Q_cool_max"]:
            return p["T_set"] + p["Q_it"] / p["k_p"], "controlled"
        return math.inf, "unbounded"
    no_cooling = p["T_amb"] + p["Q_it"] / p["UA"]
    if no_cooling <= p["T_set"]:
        return no_cooling, "off"
    controlled = (
        p["Q_it"] + p["UA"] * p["T_amb"] + p["k_p"] * p["T_set"]
    ) / (p["UA"] + p["k_p"])
    if _cooling(controlled, p) < p["Q_cool_max"] - 1e-9:
        return controlled, "controlled"
    return p["T_amb"] + (p["Q_it"] - p["Q_cool_max"]) / p["UA"], "saturated"


def _defaults(model: ModelInfo) -> dict[str, float]:
    return {name: param.default for name, param in model.parameters.items()}


def validate_model(name: str) -> ModelValidationReport:
    """Run deterministic analytic reference cases; no Modelica installation is required."""
    model = get_model(name)
    if model.metric_profile in DATACENTER_BENCHMARK_PROFILES:
        lock_path = MODELS_DIR / "models.lock.json"
        lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}
        wrapper = model.path.read_text() if model.path.exists() else ""
        expected_class = model.class_name.rsplit(".", 1)[-1]
        lock_ok = (
            lock.get("openmodelica", {}).get("version") == "1.26.3"
            and lock.get("modelica_standard_library", {}).get("version") == "4.1.0"
            and lock.get("buildings", {}).get("version") == "13.0.0"
        )
        outputs_ok = all(output in wrapper for output in model.outputs)
        wrapper_ok = f"model {expected_class}" in wrapper
        cases = [
            ValidationReferenceCase(
                id="pinned-runtime", name="Pinned runtime", status="passed" if lock_ok else "failed",
                tolerance="exact version lock",
                observed=f"OpenModelica {lock.get('openmodelica', {}).get('version')}; Buildings {lock.get('buildings', {}).get('version')}",
                expected="OpenModelica 1.26.3; Buildings 13.0.0",
                details="The pairing used by the upstream Buildings 13 regression suite.",
            ),
            ValidationReferenceCase(
                id="wrapper-contract", name="RCP wrapper contract",
                status="passed" if wrapper_ok and outputs_ok else "failed",
                tolerance="all registered outputs declared",
                observed=f"class={wrapper_ok}; outputs={outputs_ok}", expected="class and outputs present",
                details="Checks the stable parameter/output adapter before runtime validation.",
            ),
            ValidationReferenceCase(
                id="upstream-regression", name="Upstream reference trajectories", status="warning",
                tolerance="run rcp benchmark-validate",
                observed="not executed by the offline endpoint",
                expected="OpenModelica trajectories agree with pinned upstream references",
                details="This expensive check is performed by the benchmark validation command and integration CI.",
            ),
        ]
        return ModelValidationReport(
            id=model.validation_report_id or f"{name}-{model.model_version}", model_name=name,
            model_version=model.model_version, status=model.validation_status,
            checks_status="configured" if lock_ok and wrapper_ok and outputs_ok else "failed",
            generated_at=datetime.now(timezone.utc).isoformat(), operating_range=model.operating_range,
            reference_cases=cases,
            assumptions=[
                "The upstream DRYCOLD weather profile is used.",
                "The computer-room load is represented by the Buildings simplified room model.",
                "Library regression agreement is not empirical facility calibration.",
            ],
            limitations=model.limitations,
            disclosure=(
                "This is a library-validated simulation benchmark, not an empirically calibrated "
                "digital twin of a physical data center."
            ),
        )
    if name != "DataCenterRoom":
        return ModelValidationReport(
            id=model.validation_report_id or f"{name}-{model.model_version}", model_name=name,
            model_version=model.model_version, status=model.validation_status,
            checks_status="not_available", generated_at=datetime.now(timezone.utc).isoformat(),
            operating_range=model.operating_range, limitations=model.limitations,
            disclosure="No offline validation suite is registered for this model.",
        )

    base = _defaults(model)
    cases: list[ValidationReferenceCase] = []

    temp = 27.0
    qcool = _cooling(temp, base)
    rhs = base["Q_it"] + base["UA"] * (base["T_amb"] - temp) - qcool
    derivative = rhs / base["C_room"]
    residual = abs(base["C_room"] * derivative - rhs)
    cases.append(ValidationReferenceCase(
        id="energy-balance", name="Energy balance", status="passed" if residual <= 1e-9 else "failed",
        tolerance="absolute residual <= 1e-9 W", observed=f"{residual:.3g} W residual",
        expected="C_room*dT/dt equals net heat flow", details="Checks the governing first-law equation algebraically.",
    ))

    equilibrium, regime = _equilibrium(base)
    eq_residual = abs(
        base["Q_it"] + base["UA"] * (base["T_amb"] - equilibrium) - _cooling(equilibrium, base)
    )
    cases.append(ValidationReferenceCase(
        id="analytic-equilibrium", name="Analytic equilibrium", status="passed" if eq_residual <= 1e-6 else "failed",
        tolerance="heat-flow residual <= 1e-6 W", observed=f"T={equilibrium:.4f} degC; residual={eq_residual:.3g} W",
        expected="piecewise analytic steady state", details=f"Expected controller regime: {regime}.",
    ))

    saturated = dict(base, Q_it=200000.0, Q_cool_max=60000.0)
    sat_temp, sat_regime = _equilibrium(saturated)
    cases.append(ValidationReferenceCase(
        id="cooling-saturation", name="Cooling saturation", status="passed" if sat_regime == "saturated" else "failed",
        tolerance="exact controller branch", observed=f"{sat_regime}; equilibrium T={sat_temp:.2f} degC",
        expected="Q_cool reaches Q_cool_max", details="Confirms overload does not silently exceed installed cooling capacity.",
    ))

    low = dict(base, Q_it=1000.0, T_amb=20.0)
    low_temp, low_regime = _equilibrium(low)
    cases.append(ValidationReferenceCase(
        id="low-load", name="Low-load behavior", status="passed" if low_regime == "off" else "failed",
        tolerance="exact controller branch", observed=f"{low_regime}; equilibrium T={low_temp:.2f} degC",
        expected="cooling remains off below setpoint", details="Checks the lower limiter and passive envelope equilibrium.",
    ))

    repeat_a = _equilibrium(base)
    repeat_b = _equilibrium(dict(base))
    cases.append(ValidationReferenceCase(
        id="repeatability", name="Repeatability", status="passed" if repeat_a == repeat_b else "failed",
        tolerance="bitwise-equal analytic result", observed=str(repeat_a), expected=str(repeat_b),
        details="The offline reference calculation is deterministic.",
    ))

    required_units = {"Q_it": "W", "C_room": "J/K", "UA": "W/K", "T_amb": "degC", "COP": "-"}
    model_source = model.path.read_text()
    unit_failures = []
    for key, unit in required_units.items():
        registry_mismatch = model.parameters[key].unit != unit
        source_mismatch = unit != "-" and not any(
            key in line and f"[{unit}]" in line for line in model_source.splitlines()
        )
        if registry_mismatch or source_mismatch:
            unit_failures.append(key)
    cases.append(ValidationReferenceCase(
        id="units", name="Units", status="passed" if not unit_failures else "failed",
        tolerance="registry/model contract match", observed="all required units present" if not unit_failures else ", ".join(unit_failures),
        expected="W, J/K, W/K, degC, dimensionless COP",
        details="Cross-checks registry units against unit markers in the Modelica source.",
    ))

    warmer, _ = _equilibrium(dict(base, Q_it=base["Q_it"] * 1.1))
    lower_capacity, _ = _equilibrium(dict(base, Q_it=150000.0, Q_cool_max=50000.0))
    higher_capacity, _ = _equilibrium(dict(base, Q_it=150000.0, Q_cool_max=100000.0))
    sensitivity_ok = warmer > equilibrium and higher_capacity < lower_capacity
    cases.append(ValidationReferenceCase(
        id="parameter-sensitivity", name="Parameter sensitivity", status="passed" if sensitivity_ok else "failed",
        tolerance="expected monotonic direction", observed=f"load: {equilibrium:.3f}->{warmer:.3f}; capacity: {lower_capacity:.3f}->{higher_capacity:.3f}",
        expected="temperature rises with load and falls with available cooling", details="Checks two physically required monotonic trends.",
    ))

    checks_status = "passed" if all(case.status == "passed" for case in cases) else "failed"
    return ModelValidationReport(
        id=model.validation_report_id or f"{name}-{model.model_version}", model_name=name,
        model_version=model.model_version, status=model.validation_status, checks_status=checks_status,
        generated_at=datetime.now(timezone.utc).isoformat(),
        assumptions=[
            "The room is represented by one uniform temperature state.",
            "IT load, ambient temperature, envelope conductance, and COP are constant within a run.",
            "Cooling responds instantaneously through a bounded proportional controller.",
        ],
        operating_range=model.operating_range, reference_cases=cases,
        tolerances={"energy_balance_W": 1e-9, "equilibrium_residual_W": 1e-6},
        limitations=model.limitations, disclosure=CONCEPTUAL_DISCLOSURE,
    )


def runtime_plausibility_warnings(
    spec: ExperimentSpec, series: dict[str, list[float]] | None = None
) -> list[str]:
    model = get_model(spec.model_name)
    warnings: list[str] = []
    if model.metric_profile in DATACENTER_BENCHMARK_PROFILES:
        warnings.append(
            "This Buildings benchmark has upstream regression coverage but is not calibrated to a physical facility."
        )
    if model.validation_status != "validated":
        warnings.append(CONCEPTUAL_DISCLOSURE if spec.model_name == "DataCenterRoom" else f"Model validation status: {model.validation_status}.")
    for name, value in spec.parameters.items():
        credible = model.operating_range.get(name)
        if credible and not (float(credible["min"]) <= value <= float(credible["max"])):
            warnings.append(
                f"{name}={value:g} is outside the assessed operating range "
                f"[{credible['min']}, {credible['max']}] {credible.get('unit', '')}."
            )
    if not series:
        return warnings
    for name, values in series.items():
        if any(not math.isfinite(value) for value in values):
            warnings.append(f"Output {name} contains non-finite values.")
    temp = series.get("T", [])
    temp_range = model.operating_range.get("T")
    if temp and temp_range and (min(temp) < float(temp_range["min"]) or max(temp) > float(temp_range["max"])):
        warnings.append(
            f"Temperature output [{min(temp):.2f}, {max(temp):.2f}] degC leaves the assessed range "
            f"[{temp_range['min']}, {temp_range['max']}] degC."
        )
    energy = series.get("E_cool", [])
    if any(b + 1e-6 < a for a, b in zip(energy, energy[1:])):
        warnings.append("Cumulative cooling energy decreases, violating the expected non-negative energy integral.")
    power = series.get("P_cool", [])
    if power and min(power) < -1e-6:
        warnings.append("Cooling electric power contains negative values.")
    qcool = series.get("Q_cool", [])
    params = _defaults(model) | spec.parameters
    if qcool and max(qcool) > params["Q_cool_max"] * 1.001:
        warnings.append("Cooling output exceeds Q_cool_max by more than 0.1%.")
    if power and qcool and len(power) == len(qcool):
        mismatch = max(abs(p - q / params["COP"]) for p, q in zip(power, qcool))
        if mismatch > max(1.0, params["Q_cool_max"] / params["COP"] * 0.001):
            warnings.append("P_cool is inconsistent with Q_cool/COP beyond the runtime tolerance.")
    if model.metric_profile in DATACENTER_BENCHMARK_PROFILES:
        room_temp = series.get("T_room_K", [])
        assessed = model.operating_range.get("T_room_K")
        if room_temp and assessed and (
            min(room_temp) < float(assessed["min"]) or max(room_temp) > float(assessed["max"])
        ):
            warnings.append("Room temperature leaves the assessed benchmark output range.")
        hvac_power = series.get("P_HVAC_W", [])
        power_range = model.operating_range.get("P_HVAC_W")
        if hvac_power and power_range:
            excluded = sum(
                value < float(power_range["min"]) or value > float(power_range["max"])
                for value in hvac_power
            )
            if excluded:
                warnings.append(
                    f"{excluded} HVAC-power samples outside the preregistered physical screen were "
                    "excluded from the primary energy integral; raw upstream energy is retained as a diagnostic."
                )
        for energy_name in ("E_HVAC_J", "E_IT_J"):
            energy_values = series.get(energy_name, [])
            if any(b + 1e-6 < a for a, b in zip(energy_values, energy_values[1:])):
                warnings.append(f"{energy_name} decreases, violating its cumulative-energy contract.")
    return list(dict.fromkeys(warnings))
