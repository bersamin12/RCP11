"""Reproducibility manifests and portable run artifact bundles."""

from __future__ import annotations

import hashlib
import io
import json
import platform
import subprocess
import zipfile
from pathlib import Path

from rcp.config import data_dir, get_settings
from rcp.objects import ArtifactHash, RunManifest
from rcp.simulation.registry import MODELS_DIR, get_model

MANIFEST_NAME = "manifest.json"
# .jsonl carries the append-only annotation log. .pdf is deliberately absent: the
# reproducibility bundle is meant to be handed to outside reviewers, and cached
# third-party PDFs are not ours to redistribute. Their URL, licence, and SHA-256
# travel instead, so a recipient can re-fetch and verify byte-identity.
INCLUDED_SUFFIXES = {".json", ".jsonl", ".md", ".csv", ".png", ".log", ".mos", ".mo"}


def _git(args: list[str], fallback: str = "unknown") -> str:
    try:
        proc = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=5,
            cwd=Path(__file__).resolve().parents[2],
        )
        return proc.stdout.strip() if proc.returncode == 0 else fallback
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return fallback


def _hash(path: Path, root: Path) -> ArtifactHash:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return ArtifactHash(path=str(path.relative_to(root)), sha256=digest.hexdigest(), bytes=path.stat().st_size)


def build_manifest(
    run_id: str,
    inputs: dict | None = None,
    memory_snapshot: str = "",
    model_names: list[str] | None = None,
    timings_seconds: dict[str, float] | None = None,
    token_usage: dict[str, int | float] | None = None,
    lineage: dict[str, str | int | None] | None = None,
    memory_snapshot_cards_sha256: str = "",
    literature: dict[str, str | int] | None = None,
    annotations: dict[str, str | int] | None = None,
    evaluation: dict[str, str | int] | None = None,
) -> RunManifest:
    settings = get_settings()
    run_dir = data_dir() / "runs" / run_id
    lock_path = MODELS_DIR / "models.lock.json"
    lock = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    models = {}
    for name in sorted(set(model_names or [])):
        try:
            model = get_model(name)
        except KeyError:
            continue
        models[name] = {
            "class_name": model.class_name,
            "version": model.model_version,
            "validation_status": model.validation_status,
            "source": model.source,
        }
    artifacts = []
    if run_dir.exists():
        artifacts = [
            _hash(path, run_dir)
            for path in sorted(run_dir.rglob("*"))
            if path.is_file()
            and path.name != MANIFEST_NAME
            and path.suffix.lower() in INCLUDED_SUFFIXES
        ]
    return RunManifest(
        run_id=run_id,
        code_revision=_git(["rev-parse", "HEAD"]),
        code_dirty=bool(_git(["status", "--porcelain"], "")),
        runtime={
            "python": platform.python_version(),
            "platform": platform.platform(),
            "openmodelica": str(lock.get("openmodelica", {}).get("version", "unknown")),
            "modelica_standard_library": str(
                lock.get("modelica_standard_library", {}).get("version", "unknown")
            ),
            "buildings": str(lock.get("buildings", {}).get("version", "not-used")),
            "runtime_image": settings.rcp_om_image,
        },
        models=models,
        llm={
            "model": settings.rcp_model,
            "base_url": settings.rcp_base_url,
            "temperature": settings.rcp_temperature,
            "reasoning": settings.rcp_reasoning,
        },
        inputs=inputs or {}, memory_snapshot=memory_snapshot,
        memory_snapshot_cards_sha256=memory_snapshot_cards_sha256, artifacts=artifacts,
        timings_seconds=timings_seconds or {}, token_usage=token_usage or {},
        lineage=lineage or {},
        literature=literature or {}, annotations=annotations or {}, evaluation=evaluation or {},
        warnings=[
            "The manifest records a dirty working tree; exact source reconstruction requires the local changes."
        ] if bool(_git(["status", "--porcelain"], "")) else [],
    )


def write_manifest(run_id: str, **kwargs) -> RunManifest:
    run_dir = data_dir() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    current_path = run_dir / MANIFEST_NAME
    if current_path.exists():
        try:
            current = RunManifest.model_validate_json(current_path.read_text())
            kwargs.setdefault("inputs", current.inputs)
            kwargs.setdefault("memory_snapshot", current.memory_snapshot)
            kwargs.setdefault("model_names", list(current.models))
            kwargs.setdefault("timings_seconds", current.timings_seconds)
            kwargs.setdefault("token_usage", current.token_usage)
            kwargs.setdefault("lineage", current.lineage)
            kwargs.setdefault("memory_snapshot_cards_sha256", current.memory_snapshot_cards_sha256)
            kwargs.setdefault("literature", current.literature)
            kwargs.setdefault("annotations", current.annotations)
            kwargs.setdefault("evaluation", current.evaluation)
        except ValueError:
            pass
    manifest = build_manifest(run_id, **kwargs)
    destination = current_path
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(manifest.model_dump_json(indent=2))
    temporary.replace(destination)
    return manifest


def load_manifest(run_id: str) -> RunManifest:
    path = data_dir() / "runs" / run_id / MANIFEST_NAME
    if not path.exists():
        raise FileNotFoundError(path)
    return RunManifest.model_validate_json(path.read_text())


def export_reproducibility_bundle(run_id: str) -> bytes:
    run_dir = data_dir() / "runs" / run_id
    if not run_dir.exists():
        raise FileNotFoundError(run_dir)
    manifest = write_manifest(run_id)
    allowed = {artifact.path for artifact in manifest.artifacts} | {MANIFEST_NAME}
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(allowed):
            path = run_dir / relative
            if path.is_file():
                archive.write(path, arcname=f"run-{run_id}/{relative}")
    return output.getvalue()
