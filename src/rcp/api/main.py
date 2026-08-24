"""FastAPI backend for the RCP2026/11 web UI."""

import asyncio
import json
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from rcp.annotations import (
    annotation_digest,
    append_annotation,
    evidence_fingerprint,
    known_evidence_ids,
    load_annotations,
    load_raw_annotations,
    new_annotation_id,
    open_blockers,
    resolve_annotation,
)
from rcp.api.auth import BasicAuthMiddleware
from rcp.api.manager import NODE_ORDER, RunManager
from rcp.config import data_dir, get_settings, literature_dir
from rcp.evaluation import (
    blind,
    evaluation_digest,
    is_revealed,
    load_scorecards,
    new_scorecard_id,
    submit_scorecard,
    summarize,
)
from rcp.literature.acquire import asset_path, load_pdf_asset, pdf_path
from rcp.literature.fulltext import load_extractions, propose_full_text_card, save_extraction
from rcp.ideas import generate_thesis_ideas
from rcp.objects import (
    RUBRIC_DIMENSIONS, Annotation, EvaluationScorecard, ExperimentPlan, ExperimentResultSet,
    ExperimentSpec, PaperCard, PdfAnchor, ProtocolChanges, ResearchSynthesis, ResultBundle,
    ThesisIdea, ThesisProfile,
)
from rcp.outcomes import derive_run_outcome
from rcp.provenance import export_reproducibility_bundle, load_manifest, write_manifest
from rcp.reports import (
    ReportConflict,
    add_section,
    delete_section,
    export_report,
    list_revisions,
    load_report_document,
    regenerate_section,
    reorder_sections,
    restore_revision,
    update_metadata,
    update_section,
    validate_report,
)
from rcp.simulation.collector import add_screened_series, build_result_bundle, file_fingerprint, load_series
from rcp.simulation.batch import list_analysis_revisions, load_analysis_revision
from rcp.simulation.registry import get_model, load_registry
from rcp.simulation.runner import SimulationError, run_simulation
from rcp.simulation.validation import validate_model

_auth = get_settings()
# The interactive docs publish a machine-readable map of every route. Behind auth
# that is defence in depth rather than a fix, but there is no reason to hand it to
# anyone who gets past the password.
_docs_urls = {} if not _auth.rcp_auth_password else {
    "docs_url": None, "redoc_url": None, "openapi_url": None,
}
app = FastAPI(title="RCP2026/11 API", **_docs_urls)

# Registration order is REVERSED at execution time -- Starlette's add_middleware
# inserts at index 0, so the last registered runs first. Auth must be registered
# BEFORE CORS so that CORS ends up outside it. With auth outermost, a preflight
# OPTIONS (which browsers never send credentials on) gets a bare 401 that
# CORSMiddleware never sees, and the 401 loses its CORS headers too -- so the
# browser reports an opaque network error instead of prompting. Verified, not
# assumed; tests/test_auth.py pins the ordering.
app.add_middleware(
    BasicAuthMiddleware,
    username=_auth.rcp_auth_user,
    password=_auth.rcp_auth_password,
    realm=_auth.rcp_auth_realm,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    # pdf.js reads these when it requests byte ranges of a large document.
    expose_headers=["Content-Range", "Accept-Ranges", "ETag", "Content-Disposition"],
)

manager = RunManager()

# Idle SSE connections get dropped by reverse proxies; keep the run stream warm.
SSE_KEEPALIVE_SECONDS = 15.0


class CreateRun(BaseModel):
    topic: str
    constraints: list[str] = Field(default_factory=list)
    auto: bool = False
    thesis_idea: ThesisIdea | None = None
    thesis_profile: ThesisProfile | None = None
    memory_snapshot: str = ""


class ThesisIdeasRequest(ThesisProfile):
    regenerate: bool = False


class GateAnswer(BaseModel):
    answer: str | None = None
    decision: str | None = None
    selected_id: str | None = None
    feedback: str | None = None
    # literature_triage
    reviewer: str | None = None
    included_paper_ids: list[str] | None = None
    exclusions: list[dict] | None = None
    notes: list[dict] | None = None
    corrections: list[dict] | None = None
    full_text_confirmations: list[dict] | None = None


class RunUpdate(BaseModel):
    archived: bool


class ResearchReviewRequest(BaseModel):
    decision: str
    feedback: str = ""
    expected_version: int
    protocol_changes: ProtocolChanges | None = None


class SimRequest(BaseModel):
    model_name: str = "DataCenterRoom"
    parameters: dict[str, float] = Field(default_factory=dict)
    stop_time: float | None = None


class SectionUpdate(BaseModel):
    expected_version: int | None = None
    title: str | None = None
    content: str | None = None
    locked: bool | None = None
    citation_ids: list[str] | None = None
    evidence_ids: list[str] | None = None


class SectionCreate(BaseModel):
    expected_version: int | None = None
    title: str
    content: str = ""
    after_id: str | None = None


class SectionOrder(BaseModel):
    expected_version: int | None = None
    section_ids: list[str]


class VersionAction(BaseModel):
    expected_version: int | None = None
    force: bool = False


class MetadataUpdate(BaseModel):
    expected_version: int | None = None
    title: str | None = None
    authors: list[str] | None = None
    abstract: str | None = None
    keywords: list[str] | None = None
    disclosures: list[str] | None = None


@app.get("/api/health")
def health():
    checkpoint = manager.checkpoint_store_health()
    return {
        "ok": checkpoint.status == "ok", "nodes": NODE_ORDER,
        "checkpoint_store": checkpoint.model_dump(mode="json"),
    }


@app.post("/api/thesis-ideas")
def thesis_ideas(body: ThesisIdeasRequest):
    profile = ThesisProfile.model_validate(body.model_dump(exclude={"regenerate"}))
    return [idea.model_dump() for idea in generate_thesis_ideas(profile)]


# ---------- runs ----------

@app.post("/api/runs")
def create_run(body: CreateRun):
    if not body.topic.strip():
        raise HTTPException(422, "topic must not be empty")
    run_id = manager.create(
        body.topic.strip(), body.constraints, body.auto,
        thesis_idea=body.thesis_idea, thesis_profile=body.thesis_profile,
        memory_snapshot=body.memory_snapshot,
    )
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs():
    return manager.list_runs()


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    try:
        rec = manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    rec["state"], checkpoint, _ = manager.checkpoint_snapshot(run_id)
    rec["checkpoint_health"] = checkpoint.model_dump(mode="json")
    rec["outcome"] = derive_run_outcome(rec, rec["state"]).model_dump(mode="json")
    return rec


@app.patch("/api/runs/{run_id}")
def update_run(run_id: str, body: RunUpdate):
    try:
        return manager.set_archived(run_id, body.archived)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    except ValueError as err:
        raise HTTPException(409, str(err))


@app.post("/api/runs/{run_id}/retry")
def retry_run(run_id: str):
    try:
        return manager.retry(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    except ValueError as err:
        raise HTTPException(409, str(err))


@app.post("/api/runs/{run_id}/review")
def review_run(run_id: str, body: ResearchReviewRequest):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    if body.decision == "accept":
        try:
            validation = validate_report(load_report_document(run_id))
        except (FileNotFoundError, KeyError) as err:
            raise HTTPException(409, f"a valid structured report is required before acceptance: {err}")
        if not validation["valid"]:
            raise HTTPException(409, "fix export-blocking report issues before accepting this cycle")
        # An annotation cannot change graph routing, but it can hold up a
        # supervisor's sign-off -- which routes the objection through the existing
        # lineage machinery instead of around it.
        blockers = open_blockers(run_id)
        if blockers:
            targets = ", ".join(sorted({item.evidence_id for item in blockers}))
            raise HTTPException(
                409, f"resolve {len(blockers)} blocking reviewer annotation(s) first: {targets}",
            )
    try:
        review = manager.review(
            run_id, body.decision, body.feedback, body.expected_version,
            body.protocol_changes,
        )
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    except ValueError as err:
        raise HTTPException(409, str(err))
    return review.model_dump(mode="json")


@app.get("/api/runs/{run_id}/lineage")
def run_lineage(run_id: str):
    try:
        return manager.lineage(run_id).model_dump(mode="json")
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    except ValueError as err:
        raise HTTPException(409, str(err))


@app.get("/api/runs/{run_id}/synthesis")
def run_synthesis(run_id: str):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    path = data_dir() / "runs" / run_id / "research_synthesis.json"
    if not path.exists():
        raise HTTPException(404, "research synthesis is not available yet")
    try:
        return ResearchSynthesis.model_validate_json(path.read_text()).model_dump(mode="json")
    except ValueError as err:
        raise HTTPException(409, f"stored research synthesis is invalid: {err}")


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")

    async def stream():
        last_version = -1
        last_sent = time.monotonic()
        while True:
            rec = manager.get(run_id)
            if rec["version"] != last_version:
                last_version = rec["version"]
                rec["state"], checkpoint, _ = manager.checkpoint_snapshot(run_id)
                rec["checkpoint_health"] = checkpoint.model_dump(mode="json")
                rec["outcome"] = derive_run_outcome(rec, rec["state"]).model_dump(mode="json")
                yield f"data: {json.dumps(rec)}\n\n"
                last_sent = time.monotonic()
                if rec["status"] in ("done", "failed"):
                    return
            elif time.monotonic() - last_sent > SSE_KEEPALIVE_SECONDS:
                # A run parked at a human gate changes no version for minutes, so
                # this stream would otherwise send zero bytes for that whole time.
                # Reverse proxies -- Tailscale Funnel among them -- drop idle
                # connections, and the symptom is a timeline that silently stops
                # updating. A comment line keeps it warm; EventSource ignores it.
                yield ": keepalive\n\n"
                last_sent = time.monotonic()
            await asyncio.sleep(0.7)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/runs/{run_id}/gate")
def answer_gate(run_id: str, body: GateAnswer):
    payload: str | dict
    structured = body.decision or body.selected_id or body.included_paper_ids is not None
    if structured:
        payload = body.model_dump(exclude={"answer"}, exclude_none=True)
    elif body.answer is not None:
        payload = body.answer
    else:
        raise HTTPException(422, "provide answer or a structured gate decision")
    try:
        manager.answer_gate(run_id, payload)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    except ValueError as err:
        raise HTTPException(409, str(err))
    return {"ok": True}


@app.get("/api/runs/{run_id}/report", response_class=PlainTextResponse)
def run_report(run_id: str):
    path = data_dir() / "runs" / run_id / "report.md"
    if not path.exists():
        raise HTTPException(404, "report not drafted yet")
    return path.read_text()


def _report_error(err: Exception):
    if isinstance(err, FileNotFoundError) or isinstance(err, KeyError):
        raise HTTPException(404, str(err))
    if isinstance(err, ReportConflict):
        raise HTTPException(409, str(err))
    raise HTTPException(422, str(err))


@app.get("/api/runs/{run_id}/report/document")
def report_document(run_id: str):
    try:
        return load_report_document(run_id).model_dump()
    except (FileNotFoundError, ValueError) as err:
        _report_error(err)


@app.patch("/api/runs/{run_id}/report/sections/{section_id}")
def report_update_section(run_id: str, section_id: str, body: SectionUpdate):
    try:
        changes = body.model_dump(exclude={"expected_version"}, exclude_unset=True, exclude_none=True)
        return update_section(run_id, section_id, changes, body.expected_version).model_dump()
    except (FileNotFoundError, KeyError, ValueError) as err:
        _report_error(err)


@app.post("/api/runs/{run_id}/report/sections")
def report_add_section(run_id: str, body: SectionCreate):
    try:
        return add_section(
            run_id, body.title, body.content, body.after_id, body.expected_version
        ).model_dump()
    except (FileNotFoundError, KeyError, ValueError) as err:
        _report_error(err)


@app.delete("/api/runs/{run_id}/report/sections/{section_id}")
def report_delete_section(
    run_id: str, section_id: str, expected_version: int | None = Query(None), force: bool = Query(False)
):
    try:
        return delete_section(run_id, section_id, expected_version, force).model_dump()
    except (FileNotFoundError, KeyError, ValueError) as err:
        _report_error(err)


@app.post("/api/runs/{run_id}/report/reorder")
def report_reorder(run_id: str, body: SectionOrder):
    try:
        return reorder_sections(run_id, body.section_ids, body.expected_version).model_dump()
    except (FileNotFoundError, KeyError, ValueError) as err:
        _report_error(err)


@app.post("/api/runs/{run_id}/report/sections/{section_id}/regenerate")
def report_regenerate(run_id: str, section_id: str, body: VersionAction):
    try:
        return regenerate_section(run_id, section_id, body.expected_version, body.force).model_dump()
    except (FileNotFoundError, KeyError, ValueError) as err:
        _report_error(err)


@app.patch("/api/runs/{run_id}/report/metadata")
def report_metadata(run_id: str, body: MetadataUpdate):
    try:
        changes = body.model_dump(exclude={"expected_version"}, exclude_unset=True, exclude_none=True)
        return update_metadata(run_id, changes, body.expected_version).model_dump()
    except (FileNotFoundError, KeyError, ValueError) as err:
        _report_error(err)


@app.get("/api/runs/{run_id}/report/revisions")
def report_revisions(run_id: str):
    try:
        load_report_document(run_id)
        return [revision.model_dump() for revision in list_revisions(run_id)]
    except (FileNotFoundError, ValueError) as err:
        _report_error(err)


@app.post("/api/runs/{run_id}/report/revisions/{revision_id}/restore")
def report_restore(run_id: str, revision_id: str, body: VersionAction):
    try:
        return restore_revision(run_id, revision_id, body.expected_version).model_dump()
    except (FileNotFoundError, KeyError, ValueError) as err:
        _report_error(err)


@app.get("/api/runs/{run_id}/report/validation")
def report_validation(run_id: str):
    try:
        return validate_report(load_report_document(run_id))
    except (FileNotFoundError, ValueError) as err:
        _report_error(err)


@app.get("/api/runs/{run_id}/report/export")
def report_export(run_id: str, format: str = Query("md", pattern="^(md|docx|pdf)$")):
    try:
        payload, media_type, filename = export_report(load_report_document(run_id), format)
        return Response(
            payload, media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except (FileNotFoundError, ValueError, ImportError) as err:
        _report_error(err)


@app.get("/api/runs/{run_id}/series")
def run_series(
    run_id: str, points: int = Query(200, ge=10, le=5000),
    case_id: str | None = None, revision_id: str | None = None,
):
    """Time series from the run's simulation CSV, downsampled for charting."""
    base = data_dir() / "runs" / run_id
    candidates: list[Path] = []
    selected_result = None
    selected_results = None
    results_path = base / "sim" / "experiment_results.json"
    if revision_id:
        try:
            selected_results = load_analysis_revision(base / "sim", revision_id)
        except (KeyError, ValueError):
            raise HTTPException(404, f"unknown analysis revision {revision_id}")
    elif results_path.exists():
        try:
            selected_results = ExperimentResultSet.model_validate_json(results_path.read_text())
        except ValueError:
            pass
    if selected_results:
        selected_result = next(
            (
                result for result in selected_results.cases
                if (result.case_id or result.spec_id) == case_id
            ), None
        ) if case_id else next(
            (result for result in selected_results.cases if result.status == "ok"), None
        )
        if case_id and selected_result is None:
            raise HTTPException(404, f"unknown result case {case_id}")
        if selected_result and selected_result.result_file:
            candidates.append(Path(selected_result.result_file))
        else:
            raise HTTPException(404, "selected result has no raw simulation series")
    else:
        candidates += list(base.glob("sim/**/*_res.csv")) + list(base.glob("*_res.csv"))
    run_root = base.resolve()
    candidates = list(dict.fromkeys(
        path.resolve() for path in candidates
        if path.exists() and path.resolve().is_relative_to(run_root)
    ))
    if not candidates:
        raise HTTPException(404, "no simulation results for this run")
    if selected_result and selected_result.result_file_sha256:
        observed_sha256, _ = file_fingerprint(candidates[0])
        if observed_sha256 != selected_result.result_file_sha256:
            raise HTTPException(409, "raw simulation result failed its SHA-256 integrity check")
    protocol = None
    if selected_results:
        protocol = selected_results.analysis_protocol_snapshot
    plan_path = base / "experiment_plan.json"
    if protocol is None and plan_path.exists():
        try:
            protocol = ExperimentPlan.model_validate_json(plan_path.read_text()).analysis_protocol
        except ValueError:
            pass
    series = add_screened_series(load_series(candidates[0]), protocol)
    n = len(next(iter(series.values()), []))
    step = max(1, n // points)
    return {k: v[::step] for k, v in series.items()}


@app.get("/api/runs/{run_id}/results")
def run_results(run_id: str):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    path = data_dir() / "runs" / run_id / "sim" / "experiment_results.json"
    if not path.exists():
        raise HTTPException(404, "experiment results are not available yet")
    return ExperimentResultSet.model_validate_json(path.read_text()).model_dump(mode="json")


@app.get("/api/runs/{run_id}/results/revisions")
def run_result_revisions(run_id: str):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    return [
        revision.model_dump(mode="json")
        for revision in list_analysis_revisions(data_dir() / "runs" / run_id / "sim")
    ]


@app.get("/api/runs/{run_id}/results/revisions/{revision_id}")
def run_result_revision(run_id: str, revision_id: str):
    try:
        manager.get(run_id)
        revision = load_analysis_revision(
            data_dir() / "runs" / run_id / "sim", revision_id
        )
    except KeyError:
        raise HTTPException(404, f"unknown analysis revision {revision_id}")
    except ValueError as err:
        raise HTTPException(422, str(err))
    return revision.model_dump(mode="json")


@app.get("/api/runs/{run_id}/manifest")
def run_manifest(run_id: str):
    try:
        rec = manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    try:
        manifest = load_manifest(run_id)
    except FileNotFoundError:
        state, _, _ = manager.checkpoint_snapshot(run_id)
        manifest = write_manifest(
            run_id,
            inputs={"topic": rec["topic"], "constraints": rec.get("constraints", [])},
            memory_snapshot=state.get("memory_snapshot", ""),
            model_names=[
                case["model_name"] for case in (state.get("experiment_plan") or {}).get("cases", [])
            ],
        )
    return manifest.model_dump(mode="json")


@app.get("/api/runs/{run_id}/artifacts/export")
def run_artifacts_export(run_id: str):
    try:
        manager.get(run_id)
        payload = export_reproducibility_bundle(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    except FileNotFoundError as err:
        raise HTTPException(404, str(err))
    return Response(
        payload, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="rcp-run-{run_id}.zip"'},
    )


# ---------- knowledge base ----------

@app.get("/api/memory")
def memory_topics():
    root = data_dir() / "memory"
    topics = []
    if root.exists():
        for d in sorted(root.iterdir()):
            pointer = d / "latest.json"
            if not pointer.exists():
                continue
            snap = d / json.loads(pointer.read_text())["snapshot"]
            cards_file = snap / "paper_cards.json"
            count = len(json.loads(cards_file.read_text())) if cards_file.exists() else 0
            topics.append({"slug": d.name, "cards": count, "snapshot": snap.name})
    return topics


def pdf_href(card: PaperCard) -> str | None:
    """Where the reader should fetch this card's full text, if it has one."""
    if card.pdf and card.pdf.status == "available" and card.pdf.sha256:
        return f"/api/literature/pdf/{card.pdf.sha256}"
    return None


@app.get("/api/memory/{slug}")
def memory_detail(slug: str):
    memory_root = (data_dir() / "memory").resolve()
    d = (memory_root / slug).resolve()
    if not d.is_relative_to(memory_root):
        raise HTTPException(404, f"unknown topic {slug}")
    pointer = d / "latest.json"
    if not pointer.exists():
        raise HTTPException(404, f"unknown topic {slug}")
    snap = d / json.loads(pointer.read_text())["snapshot"]
    cards = [
        PaperCard.model_validate(card)
        for card in json.loads((snap / "paper_cards.json").read_text())
    ]
    return {
        "slug": slug,
        "snapshot": snap.name,
        "paper_cards": [
            {**card.model_dump(mode="json"), "pdf_href": pdf_href(card)} for card in cards
        ],
        "themes": json.loads((snap / "themes.json").read_text()),
    }


# ---------- literature full text ----------

# PDFs are addressed by content hash, never by paper ID: a real ID looks like
# "https://openalex.org/W2073832139" and cannot survive a URL path. The 64-hex
# pattern is also the whole path-traversal guard -- no dot or slash can pass it.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _resolve_pdf(sha256: str) -> Path:
    if not _SHA256_RE.match(sha256):
        raise HTTPException(404, "unknown pdf")
    path = pdf_path(sha256).resolve()
    if not path.is_file() or not path.is_relative_to(literature_dir().resolve()):
        raise HTTPException(404, "unknown pdf")
    return path


@app.get("/api/literature/pdf/{sha256}")
def literature_pdf(sha256: str, download: bool = Query(False)):
    """Serve a cached open-access PDF.

    FileResponse already implements HTTP range requests, If-Range, 206/416, and
    Accept-Ranges, which is how pdf.js renders page 1 of a large paper without
    downloading all of it. Content addressing makes `immutable` provably correct.
    """
    path = _resolve_pdf(sha256)
    disposition = "attachment" if download else "inline"
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="{sha256[:16]}.pdf"',
            "ETag": f'"{sha256}"',
            "Cache-Control": "private, max-age=86400, immutable",
        },
    )


@app.get("/api/literature/assets/{sha256}")
def literature_asset(sha256: str):
    if not _SHA256_RE.match(sha256):
        raise HTTPException(404, "unknown pdf")
    asset = load_pdf_asset(sha256)
    if asset is None or not asset_path(sha256).is_file():
        raise HTTPException(404, "unknown pdf")
    return asset.model_dump(mode="json")


class ScorecardRequest(BaseModel):
    reviewer_id: str
    condition: str = "platform"
    blinded: bool = True
    blinding_method: str = ""
    self_evaluated: bool = False
    # Constrained here as well as on the stored model, so an out-of-range score is
    # a bad request rather than a conflict discovered on the way to disk.
    claim_to_number_traceability: int = Field(ge=1, le=5)
    claim_to_literature_traceability: int = Field(ge=1, le=5)
    missing_evidence_visibility: int = Field(ge=1, le=5)
    experiment_comparability_preregistration: int = Field(ge=1, le=5)
    reproducibility_from_captured_inputs: int = Field(ge=1, le=5)
    calibration_validation_disclosure: int = Field(ge=1, le=5)
    claim_verification_effort: int = Field(ge=1, le=5)
    verification_time_seconds: float | None = None
    challenged_claim_id: str = ""
    observations: str = ""


@app.post("/api/runs/{run_id}/evaluation", status_code=201)
def submit_evaluation(run_id: str, body: ScorecardRequest):
    try:
        record = manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    if record.get("status") != "done":
        raise HTTPException(409, "only a completed cycle can be scored")
    if body.condition not in {"platform", "baseline"}:
        raise HTTPException(422, f"unknown condition: {body.condition}")
    if not body.reviewer_id.strip():
        raise HTTPException(422, "a scorecard must name its reviewer")
    try:
        scorecard = EvaluationScorecard(
            id=new_scorecard_id(run_id), run_id=run_id,
            **body.model_dump(),
        )
        submit_scorecard(run_id, scorecard)
    except ValueError as err:
        raise HTTPException(409, str(err))
    try:
        write_manifest(run_id, evaluation=evaluation_digest(run_id))
    except (OSError, ValueError):
        pass
    return scorecard.model_dump(mode="json")


@app.get("/api/runs/{run_id}/evaluation")
def list_evaluation(
    run_id: str,
    reviewer_id: str | None = Query(None),
    condition: str = Query("platform"),
):
    """Peer scores stay concealed until enough independent submissions exist.

    That is what makes "independently, before discussing" a property of the system
    rather than a hope. A caller always gets their own scorecard back.
    """
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    cards = load_scorecards(run_id, condition)
    revealed = is_revealed(run_id, condition)
    mine = [card for card in cards if reviewer_id and card.reviewer_id == reviewer_id]
    return {
        "count": len(cards),
        "min_reviewers": get_settings().rcp_min_rubric_reviewers,
        "revealed": revealed,
        "reviewer_ids": sorted({card.reviewer_id for card in cards}),
        "scorecards": [card.model_dump(mode="json") for card in (cards if revealed else mine)],
        "summary": summarize(run_id, condition).model_dump(mode="json") if revealed else None,
        "dimensions": list(RUBRIC_DIMENSIONS),
        # Stated rather than implied: this service has no authentication.
        "blinding_note": (
            "Blinding is a claim recorded by each submitter, not a property this "
            "service can verify: reviewer identity is self-declared."
        ),
    }


@app.get("/api/runs/{run_id}/evaluation/packet")
def evaluation_packet(run_id: str, condition: str = Query("platform")):
    """The artifact bundle to score, stripped of the platform's own confidence."""
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    state = manager.state_snapshot(run_id)
    if condition == "baseline":
        # The documented baseline condition: titles and abstracts, plus raw data.
        packet = {
            "papers": [
                {"title": card.get("title"), "abstract": card.get("abstract"),
                 "year": card.get("year"), "venue": card.get("venue")}
                for card in state.get("paper_cards") or []
            ],
            "raw_result_files": [
                case.get("result_file")
                for case in (state.get("experiment_results") or {}).get("cases") or []
            ],
        }
    else:
        packet = {
            "claims": (state.get("claim_bundle") or {}).get("claims") or [],
            "experiment_plan": state.get("experiment_plan"),
            "experiment_results": state.get("experiment_results"),
            "papers": state.get("paper_cards") or [],
        }
    return {"condition": condition, "packet": blind(packet)}


class AnnotationRequest(BaseModel):
    evidence_id: str
    kind: str = "comment"
    severity: str = "info"
    body: str
    author: str = "human"
    proposed_value: str = ""
    anchor: dict | None = None


class AnnotationResolution(BaseModel):
    resolution_note: str = ""
    author: str = "human"


@app.get("/api/runs/{run_id}/annotations")
def list_annotations(run_id: str, evidence_id: str | None = Query(None), raw: bool = Query(False)):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    records = load_raw_annotations(run_id) if raw else load_annotations(run_id)
    if evidence_id:
        records = [item for item in records if item.evidence_id == evidence_id]
    return [item.model_dump(mode="json") for item in records]


@app.post("/api/runs/{run_id}/annotations", status_code=201)
def create_annotation(run_id: str, body: AnnotationRequest):
    """Annotations are accepted at any point in a run's life, including after it ends."""
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    if body.kind not in {"comment", "flag", "correction"}:
        raise HTTPException(422, f"unknown annotation kind: {body.kind}")
    if body.severity not in {"info", "concern", "blocker"}:
        raise HTTPException(422, f"unknown severity: {body.severity}")

    state = manager.state_snapshot(run_id)
    if body.evidence_id not in known_evidence_ids(run_id, state):
        # Storing an orphan would create the dangling reference validate_report
        # already treats as export-blocking.
        raise HTTPException(422, f"unknown evidence id: {body.evidence_id}")

    try:
        annotation = Annotation(
            id=new_annotation_id(), run_id=run_id, evidence_id=body.evidence_id,
            evidence_fingerprint=evidence_fingerprint(body.evidence_id, state),
            kind=body.kind, severity=body.severity, body=body.body,
            proposed_value=body.proposed_value, author=body.author,
            anchor=PdfAnchor.model_validate(body.anchor) if body.anchor else None,
        )
        append_annotation(run_id, annotation)
    except ValueError as err:
        raise HTTPException(422, str(err))
    _refresh_annotation_manifest(run_id)
    return annotation.model_dump(mode="json")


@app.post("/api/runs/{run_id}/annotations/{annotation_id}/resolve")
def resolve_annotation_route(run_id: str, annotation_id: str, body: AnnotationResolution):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    try:
        resolution = resolve_annotation(run_id, annotation_id, body.resolution_note, body.author)
    except KeyError:
        raise HTTPException(404, f"unknown annotation {annotation_id}")
    except ValueError as err:
        raise HTTPException(422, str(err))
    _refresh_annotation_manifest(run_id)
    return resolution.model_dump(mode="json")


def _refresh_annotation_manifest(run_id: str) -> None:
    """Hash the annotation log into the manifest, throttled per run.

    write_manifest re-hashes every artifact in the run directory, which is O(run
    size); doing that on every comment would be wasteful on a run with large CSVs.
    """
    now = time.monotonic()
    last = _ANNOTATION_MANIFEST_AT.get(run_id, 0.0)
    if now - last < 2.0:
        return
    _ANNOTATION_MANIFEST_AT[run_id] = now
    try:
        write_manifest(run_id, annotations=annotation_digest(run_id))
    except (OSError, ValueError):
        # Bookkeeping must not fail the write that triggered it, but a programming
        # error here should still surface rather than be swallowed silently.
        pass


_ANNOTATION_MANIFEST_AT: dict[str, float] = {}


class FullTextRequest(BaseModel):
    # A real paper ID is a URL, so it travels in the body rather than the path.
    paper_id: str


@app.post("/api/runs/{run_id}/literature/full-text")
def propose_full_text(run_id: str, body: FullTextRequest):
    """Read a cached PDF and propose a page-cited revision. Changes nothing."""
    try:
        record = manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    if record.get("status") != "waiting_gate" or (record.get("gate") or {}).get("gate") != "literature_triage":
        raise HTTPException(409, "full-text extraction is only offered at the literature triage gate")

    state = manager.state_snapshot(run_id)
    cards = [PaperCard.model_validate(item) for item in state.get("paper_cards", [])]
    card = next((item for item in cards if item.id == body.paper_id), None)
    if card is None:
        raise HTTPException(404, f"unknown paper {body.paper_id}")
    if not card.pdf or card.pdf.status != "available" or not card.pdf.sha256:
        raise HTTPException(409, "this paper has no readable open-access full text")

    existing = load_extractions(run_id, card.id)
    for item in existing:
        if item.status == "proposed":
            item.status = "superseded"
            save_extraction(run_id, item)
    try:
        extraction = propose_full_text_card(
            run_id, card, card.pdf, pdf_path(card.pdf.sha256),
            state.get("topic", {}).get("title", ""), sequence=len(existing) + 1,
        )
    except Exception as err:
        raise HTTPException(502, f"full-text extraction failed: {err}")
    save_extraction(run_id, extraction)
    return extraction.model_dump(mode="json")


@app.get("/api/runs/{run_id}/literature/full-text")
def list_full_text(run_id: str, paper_id: str | None = Query(None)):
    try:
        manager.get(run_id)
    except KeyError:
        raise HTTPException(404, f"unknown run {run_id}")
    return [item.model_dump(mode="json") for item in load_extractions(run_id, paper_id)]


# ---------- models & simulations ----------

@app.get("/api/models")
def models():
    return {
        name: {
            "description": m.description,
            "default_stop_time": m.default_stop_time,
            "outputs": m.outputs,
            "parameters": {p: s.model_dump() for p, s in m.parameters.items()},
            "validation_status": m.validation_status,
            "model_version": m.model_version,
            "validation_report_id": m.validation_report_id,
            "limitations": m.limitations,
            "operating_range": m.operating_range,
            "libraries": m.libraries,
            "source": m.source,
            "metric_profile": m.metric_profile,
        }
        for name, m in load_registry().items()
    }


@app.get("/api/models/{name}/validation")
def model_validation(name: str):
    try:
        return validate_model(name).model_dump()
    except KeyError as err:
        raise HTTPException(404, str(err))


@app.post("/api/simulations")
def quick_simulate(body: SimRequest):
    try:
        info = get_model(body.model_name)
    except KeyError as err:
        raise HTTPException(404, str(err))
    spec = ExperimentSpec(
        id="manual-" + uuid.uuid4().hex[:6],
        hypothesis_id="manual",
        model_name=body.model_name,
        parameters=body.parameters,
        outputs=info.outputs,
        stop_time=body.stop_time or info.default_stop_time,
    )
    workdir = data_dir() / "runs" / spec.id
    try:
        csv_path, log = run_simulation(spec, workdir)
    except SimulationError as err:
        raise HTTPException(422, str(err)[:1500])
    bundle = build_result_bundle(spec, workdir, csv_path, log)
    (workdir / "result_bundle.json").write_text(bundle.model_dump_json(indent=2))
    return bundle.model_dump()


@app.get("/api/simulations/{spec_id}/series")
def quick_simulation_series(
    spec_id: str, points: int = Query(200, ge=10, le=5000),
):
    """Integrity-checked time series for a manual quick simulation."""
    if not re.fullmatch(r"manual-[0-9a-f]{6}", spec_id):
        raise HTTPException(404, f"unknown simulation {spec_id}")
    workdir = (data_dir() / "runs" / spec_id).resolve()
    result_path = workdir / "result_bundle.json"
    if not result_path.exists():
        raise HTTPException(404, f"unknown simulation {spec_id}")
    try:
        bundle = ResultBundle.model_validate_json(result_path.read_text())
    except ValueError:
        raise HTTPException(409, "stored simulation metadata is invalid")
    if not bundle.result_file:
        raise HTTPException(404, "simulation has no raw result series")
    csv_path = Path(bundle.result_file).resolve()
    if not csv_path.exists() or not csv_path.is_relative_to(workdir):
        raise HTTPException(409, "stored simulation result path is invalid")
    if bundle.result_file_sha256:
        observed_sha256, _ = file_fingerprint(csv_path)
        if observed_sha256 != bundle.result_file_sha256:
            raise HTTPException(409, "raw simulation result failed its SHA-256 integrity check")
    series = load_series(csv_path)
    length = len(next(iter(series.values()), []))
    step = max(1, length // points)
    return {key: values[::step] for key, values in series.items()}


# ---------- static frontend (production) ----------

_dist = Path(__file__).parent.parent.parent.parent / "webapp" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="webapp")
