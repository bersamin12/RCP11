"""RCP platform CLI."""

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import typer
from langgraph.types import Command
from rich.console import Console
from rich.table import Table

from rcp.config import data_dir, get_settings
from rcp.objects import ExperimentSpec, ResearchTopic

app = typer.Typer(help="RCP2026/11 — AI Agent Workflow for Scientific Discovery")
console = Console()


@app.command()
def run(
    topic: str,
    constraint: list[str] = typer.Option([], "--constraint", "-c"),
    auto: bool = typer.Option(False, help="Auto-resolve human gates (testing)"),
):
    """Run the full closed loop: topic -> memory -> hypotheses -> simulation -> report."""
    from rcp.graph.build import build_graph
    from rcp.graph.state import RCPState

    graph = build_graph()
    run_id = uuid.uuid4().hex[:8]
    config = {"configurable": {"thread_id": run_id}}
    console.print(f"[bold]run id:[/] {run_id}")

    state = graph.invoke(
        RCPState(run_id=run_id, topic=ResearchTopic(title=topic, constraints=constraint), auto=auto),
        config,
    )
    while "__interrupt__" in state:
        payload = state["__interrupt__"][0].value
        console.print(f"\n[bold yellow]HUMAN GATE:[/] {payload['question']}")
        for line in payload.get("options", []):
            console.print(f"  {line}")
        if "spec" in payload:
            console.print_json(json.dumps(payload["spec"]))
        answer = typer.prompt("> ")
        state = graph.invoke(Command(resume=answer), config)

    console.print(f"\n[bold green]done.[/] report: {state.get('report_path')}")


@app.command("memory-build")
def memory_build(topic: str, max_papers: int = 8):
    """Build the research memory only (Module 1)."""
    from rcp.memory.pipeline import build_research_memory

    cards, themes, snapshot = build_research_memory(topic, max_papers=max_papers)
    console.print(f"{len(cards)} paper cards, {len(themes)} themes -> {snapshot}")


@app.command("sim-run")
def sim_run(
    model: str = "DataCenterRoom",
    stop_time: float = typer.Option(0, help="0 = model default"),
    set_param: list[str] = typer.Option([], "--set", help="k=v parameter overrides"),
):
    """Run a single simulation directly (Module 4)."""
    from rcp.simulation.collector import build_result_bundle
    from rcp.simulation.registry import get_model
    from rcp.simulation.runner import SimulationError, run_simulation

    info = get_model(model)
    spec = ExperimentSpec(
        id="manual-" + uuid.uuid4().hex[:6],
        hypothesis_id="manual",
        model_name=model,
        parameters={k: float(v) for k, v in (s.split("=", 1) for s in set_param)},
        outputs=info.outputs,
        stop_time=stop_time or info.default_stop_time,
    )
    workdir = data_dir() / "runs" / spec.id
    try:
        csv_path, log = run_simulation(spec, workdir)
        bundle = build_result_bundle(spec, workdir, csv_path, log)
        console.print_json(bundle.model_dump_json())
    except SimulationError as err:
        console.print(f"[red]simulation failed:[/] {err}")
        raise typer.Exit(1)


@app.command()
def models():
    """List registered simulation models (Module 4 registry)."""
    from rcp.simulation.registry import load_registry

    table = Table("model", "validation", "version", "description", "parameters")
    for name, m in load_registry().items():
        table.add_row(name, m.validation_status, m.model_version, m.description[:80], ", ".join(m.parameters))
    console.print(table)


@app.command("model-validate")
def model_validate(model: str = "DataCenterRoom", output: Path | None = None):
    """Run deterministic offline physics/reference checks (suitable for CI)."""
    from rcp.simulation.validation import validate_model

    report = validate_model(model)
    payload = report.model_dump_json(indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload)
        console.print(f"validation report -> {output}")
    else:
        console.print_json(payload)
    if report.checks_status == "failed":
        raise typer.Exit(1)


@app.command()
def doctor():
    """Check local LLM, storage, registry, and Modelica prerequisites without running a study."""
    from rcp.simulation.registry import MODELS_DIR, load_registry

    settings = get_settings()
    table = Table("check", "status", "details")
    failures = 0

    def row(name: str, ok: bool, details: str, required: bool = True):
        nonlocal failures
        table.add_row(name, "ok" if ok else ("missing" if required else "warning"), details)
        if required and not ok:
            failures += 1

    row("model registry", bool(load_registry()), f"{len(load_registry())} registered models")
    lock = MODELS_DIR / "models.lock.json"
    lock_data = json.loads(lock.read_text()) if lock.exists() else {}
    lock_ok = (
        lock_data.get("openmodelica", {}).get("version") == "1.26.3"
        and lock_data.get("modelica_standard_library", {}).get("version") == "4.1.0"
        and lock_data.get("buildings", {}).get("version") == "13.0.0"
    )
    row("model lock", lock_ok, str(lock))
    storage = data_dir()
    row("data directory", storage.exists() and storage.is_dir(), str(storage.resolve()))
    local_omc = shutil.which("omc")
    docker = shutil.which("docker")
    row("simulation backend", bool(local_omc or docker), local_omc or docker or "not found")
    if docker:
        inspect = subprocess.run(
            [docker, "image", "inspect", settings.rcp_om_image],
            capture_output=True, text=True,
        )
        image_ok = inspect.returncode == 0
        if image_ok:
            image_data = json.loads(inspect.stdout)[0]
            labels = image_data.get("Config", {}).get("Labels", {}) or {}
            image_ok = (
                labels.get("org.rcp.buildings.commit") == lock_data.get("buildings", {}).get("git_commit")
                and labels.get("org.rcp.modelica.commit")
                == lock_data.get("modelica_standard_library", {}).get("git_commit")
            )
        row("pinned runtime image", image_ok, settings.rcp_om_image)
    else:
        row("pinned runtime image", False, "docker is required for the Buildings benchmark")
    row("LLM API key", bool(settings.openrouter_api_key), "configured" if settings.openrouter_api_key else "set OPENROUTER_API_KEY before an online workflow", required=False)
    env_file = Path(".env")
    env_private = not env_file.exists() or not (env_file.stat().st_mode & 0o077)
    auth_detail = (
        "configured" if settings.rcp_auth_password and env_private
        else ".env is group/world readable — chmod 600 .env" if settings.rcp_auth_password
        else "set RCP_AUTH_PASSWORD before exposing the API (see docs/DEPLOYMENT.md)"
    )
    row("api auth", bool(settings.rcp_auth_password) and env_private, auth_detail, required=False)
    console.print(table)
    if failures:
        raise typer.Exit(1)


MIN_AUTH_PASSWORD_LENGTH = 16


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address. Tailscale Funnel proxies to loopback."),
    port: int = typer.Option(8000, help="Port to listen on."),
    insecure_no_auth: bool = typer.Option(
        False, "--insecure-no-auth",
        help="Serve with authentication disabled. Never do this on an exposed host.",
    ),
):
    """Serve the API and the built web UI (see docs/DEPLOYMENT.md)."""
    import uvicorn

    settings = get_settings()
    password = settings.rcp_auth_password

    # Fail closed. The library default is permissive so that CI and the test suite
    # are unaffected, which means this command is the only thing standing between a
    # typo and an unauthenticated public deployment.
    if not password and not insecure_no_auth:
        console.print(
            "[red]refusing to start without authentication.[/] "
            "Set RCP_AUTH_PASSWORD in .env, or pass --insecure-no-auth."
        )
        raise typer.Exit(1)
    if password and len(password) < MIN_AUTH_PASSWORD_LENGTH:
        console.print(
            f"[red]RCP_AUTH_PASSWORD is shorter than {MIN_AUTH_PASSWORD_LENGTH} characters.[/] "
            "There is no rate limiting or lockout, so length is the only defence. "
            "Generate one with: openssl rand -base64 24"
        )
        raise typer.Exit(1)
    if insecure_no_auth and host != "127.0.0.1":
        console.print(f"[red]refusing to bind {host} with authentication disabled.[/]")
        raise typer.Exit(1)

    dist = Path(__file__).resolve().parents[2] / "webapp" / "dist"
    if not dist.exists():
        # api/main.py mounts the SPA only if this directory exists, and says nothing
        # when it does not -- the UI would just 404 with no explanation anywhere.
        console.print(f"[yellow]no built frontend at {dist}[/] — run `npm run build` in webapp/")

    from rcp.api.main import app as api

    # Passing the app object rather than an import string is deliberate: uvicorn
    # rejects workers=N in that form, so the single-worker requirement is enforced
    # structurally. RunManager (rcp/api/manager.py) holds live run state and its
    # SSE subscribers in process; a second worker would serve requests that know
    # nothing about a run in flight.
    uvicorn.run(api, host=host, port=port, log_level="info")


@app.command("benchmark-setup")
def benchmark_setup():
    """Build the pinned OpenModelica 1.26.3 + Buildings 13.0.0 image."""
    docker = shutil.which("docker")
    if not docker:
        console.print("[red]docker is not installed[/]")
        raise typer.Exit(1)
    root = Path(__file__).resolve().parents[2]
    command = [
        docker, "build", "-t", get_settings().rcp_om_image,
        "-f", str(root / "docker" / "modelica" / "Dockerfile"), str(root),
    ]
    console.print(f"Building [bold]{get_settings().rcp_om_image}[/]…")
    result = subprocess.run(command)
    if result.returncode:
        raise typer.Exit(result.returncode)


@app.command("benchmark-run")
def benchmark_run(smoke: bool = typer.Option(False, help="Run only the default matched pair")):
    """Run the preregistered ChillerCooled comparison and persist all artifacts."""
    from rcp.simulation.batch import benchmark_plan, benchmark_smoke_plan, run_plan

    run_id = "benchmark-" + uuid.uuid4().hex[:8]
    plan = benchmark_smoke_plan("benchmark", run_id) if smoke else benchmark_plan("benchmark", run_id)
    workdir = data_dir() / "runs" / run_id / "sim"
    workdir.parent.mkdir(parents=True, exist_ok=True)
    (workdir.parent / "experiment_plan.json").write_text(plan.model_dump_json(indent=2))
    console.print(f"[bold]run id:[/] {run_id} · {len(plan.cases)} cases")
    results = run_plan(plan, workdir)
    from rcp.provenance import write_manifest
    write_manifest(
        run_id, inputs={"experiment_plan": plan.model_dump(mode="json")},
        model_names=[case.model_name for case in plan.cases],
    )
    console.print_json(results.model_dump_json(indent=2))
    if results.status != "ok" or (results.quality_report and not results.quality_report.valid):
        raise typer.Exit(1)


@app.command("benchmark-validate")
def benchmark_validate():
    """Check default-pair repeatability and pinned upstream trajectories."""
    from rcp.simulation.batch import benchmark_smoke_plan, run_plan
    from rcp.simulation.reference import compare_upstream_reference
    from rcp.provenance import write_manifest

    result_sets = []
    validation_runs: list[tuple[str, object]] = []
    for suffix in ("a", "b"):
        run_id = "validation-" + uuid.uuid4().hex[:6] + suffix
        plan = benchmark_smoke_plan("validation", run_id)
        run_dir = data_dir() / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "experiment_plan.json").write_text(plan.model_dump_json(indent=2))
        result_sets.append(run_plan(plan, run_dir / "sim"))
        validation_runs.append((run_id, plan))
    for result_set in result_sets:
        if result_set.status != "ok" or (result_set.quality_report and not result_set.quality_report.valid):
            console.print("[red]benchmark execution or study-quality validation failed[/]")
            raise typer.Exit(1)
    first = next(result for result in result_sets[0].cases if result.case_id.startswith("candidate"))
    second = next(result for result in result_sets[1].cases if result.case_id.startswith("candidate"))
    failures = []
    for metric in sorted(set(first.metrics) & set(second.metrics)):
        a, b = first.metrics[metric], second.metrics[metric]
        if "temp" in metric.lower():
            ok = abs(a - b) <= 0.05
        else:
            ok = abs(a - b) <= max(abs(a), 1.0) * 0.001
        if not ok:
            failures.append(f"{metric}: {a} vs {b}")
    if failures:
        console.print("[red]repeatability validation failed:[/] " + "; ".join(failures))
        raise typer.Exit(1)
    reference_checks = []
    for result in result_sets[0].cases:
        reference_checks.append(compare_upstream_reference(
            Path(result.result_file), result.model_name,
        ))
    reference_failures = [check for check in reference_checks if check["status"] != "passed"]
    validation = {
        "status": "failed" if reference_failures else "passed",
        "repeatability_metrics": len(first.metrics),
        "upstream_reference_checks": reference_checks,
    }
    validation_path = Path(result_sets[0].cases[0].workdir).parents[2] / "benchmark_validation.json"
    validation_path.write_text(json.dumps(validation, indent=2))
    for run_id, plan in validation_runs:
        write_manifest(
            run_id, inputs={"experiment_plan": plan.model_dump(mode="json")},
            model_names=[case.model_name for case in plan.cases],
        )
    if reference_failures:
        console.print("[red]upstream trajectory validation failed[/]")
        raise typer.Exit(1)
    worst = max(check["worst_normalized_rmse"] for check in reference_checks)
    console.print(
        f"[green]benchmark validation passed[/] · {len(first.metrics)} repeatability metrics · "
        f"worst upstream normalized RMSE {worst:.3%}"
    )


@app.command("verify-llm")
def verify_llm():
    """Smoke-test the configured LLM provider."""
    from rcp.llm import get_chat_model

    s = get_settings()
    console.print(f"model={s.rcp_model} base_url={s.rcp_base_url}")
    reply = get_chat_model().invoke("Reply with exactly: OK")
    console.print(f"reply: {reply.content!r}")


if __name__ == "__main__":
    app()
