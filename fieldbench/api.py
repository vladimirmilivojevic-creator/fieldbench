"""Web API for the bench console: run a campaign, watch it, read the issues.

Campaigns run one at a time in a background worker (the free server has a
fraction of a CPU), and the browser polls GET /api/runs/{id} for progress.
"""

from __future__ import annotations

import os
import tempfile
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from . import __version__
from .analysis import dbc_cycle_times, decode, find_dropouts, message_stats, read_log
from .bench import load_dbc
from .campaign import PLOT_SIGNALS, finish_campaign, now_utc, run_procedure
from .ecus import RELEASES
from .faults import FaultInjector
from .guidance import ab_line_from_track, evaluate_track
from .issues import IssueTracker, defect_report
from .nmea import read_nmea_file
from .spec import DEFAULT_SPEC, load_spec

DATA_DIR = Path(os.environ.get("FIELDBENCH_DATA", Path(tempfile.gettempdir()) / "fieldbench"))
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
MAX_RUNS_KEPT = 6
MAX_QUEUED = 3
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

spec = load_spec(os.environ.get("FIELDBENCH_SPEC", DEFAULT_SPEC))
db = load_dbc()
runs: OrderedDict[str, dict] = OrderedDict()
runs_lock = threading.Lock()
worker = ThreadPoolExecutor(max_workers=1)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="FieldBench API", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


class RunRequest(BaseModel):
    release: str = "1.4.0"
    procedures: list[str] = Field(default_factory=list, description="empty = all procedures")


def tracker() -> IssueTracker:
    return IssueTracker(DATA_DIR / "issues.json")


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}


@app.get("/api/spec")
def get_spec():
    return {
        "system": spec.system,
        "releases": [{"version": r.version, "notes": r.notes} for r in RELEASES.values()],
        "requirements": {rid: asdict(r) for rid, r in spec.requirements.items()},
        "procedures": [
            {
                "id": p.id,
                "title": p.title,
                "requirement": p.requirement,
                "safety": spec.requirements[p.requirement].safety,
                "faults": p.faults,
            }
            for p in spec.procedures
        ],
    }


@app.post("/api/runs", status_code=202)
def start_run(request: RunRequest):
    if request.release not in RELEASES:
        raise HTTPException(422, f"unknown release {request.release}")
    known = {p.id for p in spec.procedures}
    if unknown := set(request.procedures) - known:
        raise HTTPException(422, f"unknown procedures {sorted(unknown)}")
    with runs_lock:
        if sum(r["status"] in ("queued", "running") for r in runs.values()) >= MAX_QUEUED:
            raise HTTPException(429, "the bench is busy, try again in a minute")
        run_id = uuid.uuid4().hex[:8]
        procedures = [p for p in spec.procedures if not request.procedures or p.id in request.procedures]
        runs[run_id] = {
            "id": run_id,
            "release": request.release,
            "status": "queued",
            "started": now_utc(),
            "total": len(procedures),
            "results": [],
            "summary": None,
        }
        while len(runs) > MAX_RUNS_KEPT:
            runs.popitem(last=False)
    worker.submit(_execute, run_id, request.release, procedures)
    return {"id": run_id, "status": "queued"}


def _execute(run_id: str, release: str, procedures) -> None:
    run = runs[run_id]
    run["status"] = "running"
    out_dir = DATA_DIR / "runs" / run_id
    try:
        for procedure in procedures:
            run["results"].append(run_procedure(spec, procedure, release, db, out_dir, plots=False))
        summary = finish_campaign(spec, release, run["started"], run["results"], out_dir, DATA_DIR / "issues.json", db)
        for result in run["results"]:
            result.messages = []  # logs are on disk; free the memory
        run["summary"] = summary
        run["status"] = "done"
    except Exception as exc:  # report it to the browser instead of hanging at "running"
        run["status"], run["error"] = "error", str(exc)


def _records(frame) -> list[dict]:
    """DataFrame rows as JSON-safe dicts (NaN is not valid JSON)."""
    return frame.astype(object).where(frame.notna(), None).to_dict(orient="records")


def _result_json(result) -> dict:
    return {
        "id": result.procedure.id,
        "title": result.procedure.title,
        "requirement": result.procedure.requirement,
        "passed": result.passed,
        "runtime_s": round(result.duration_s, 2),
        "checks": [asdict(c) for c in result.checks],
    }


def _get_run(run_id: str) -> dict:
    run = runs.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found (the demo keeps only the last few runs)")
    return run


@app.get("/api/runs")
def list_runs():
    return [
        {k: r[k] for k in ("id", "release", "status", "started", "total")} | {"done": len(r["results"])}
        for r in reversed(runs.values())
    ]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run = _get_run(run_id)
    summary = run["summary"]
    return {
        "id": run["id"],
        "release": run["release"],
        "status": run["status"],
        "error": run.get("error"),
        "started": run["started"],
        "total": run["total"],
        "done": len(run["results"]),
        "results": [_result_json(r) for r in list(run["results"])],
        "passed": summary.passed if summary else None,
        "failed": summary.failed if summary else None,
    }


@app.get("/api/runs/{run_id}/signals/{procedure_id}")
def get_signals(run_id: str, procedure_id: str):
    run = _get_run(run_id)
    result = next((r for r in list(run["results"]) if r.procedure.id == procedure_id), None)
    if result is None:
        raise HTTPException(404, "procedure not run yet")
    signals = {}
    for name in PLOT_SIGNALS:
        try:
            series = result.capture.signal(name)
        except KeyError:
            continue
        signals[name] = {"t": [round(t, 3) for t in series.index], "v": [round(float(v), 3) for v in series.values]}
    cycles = {m.name: m.cycle_ms for m in spec.messages.values()}
    return {
        "signals": signals,
        "faults": [
            {"start": a, "end": b, "type": kind} for a, b, kind in FaultInjector(result.procedure.faults).windows()
        ],
        "dropouts": [asdict(d) | {"gap_ms": d.gap_ms} for d in find_dropouts(result.capture, cycles)],
        "error_frames": result.capture.error_frames,
    }


def _run_file(run_id: str, relative: str) -> Path:
    run = _get_run(run_id)
    if run["status"] != "done" and not relative.startswith("logs/"):
        raise HTTPException(409, "run not finished")
    base = (DATA_DIR / "runs" / run_id).resolve()
    path = (base / relative).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404, "file not found")
    return path


@app.get("/api/runs/{run_id}/report.html")
def get_report_html(run_id: str):
    release = _get_run(run_id)["release"]
    return FileResponse(_run_file(run_id, f"report_{release}.html"), media_type="text/html")


@app.get("/api/runs/{run_id}/report.xlsx")
def get_report_xlsx(run_id: str):
    release = _get_run(run_id)["release"]
    return FileResponse(_run_file(run_id, f"report_{release}.xlsx"), filename=f"fieldbench_report_{release}.xlsx")


@app.get("/api/runs/{run_id}/logs/{filename}")
def get_log(run_id: str, filename: str):
    if not filename.endswith((".asc", ".blf")):
        raise HTTPException(404, "only .asc and .blf logs")
    return FileResponse(_run_file(run_id, f"logs/{filename}"), filename=filename)


@app.get("/api/issues")
def list_issues():
    return [asdict(i) for i in tracker().issues]


@app.get("/api/issues/{issue_id}.md", response_class=PlainTextResponse)
def get_issue_report(issue_id: str):
    issue = next((i for i in tracker().issues if i.id == issue_id), None)
    if issue is None:
        raise HTTPException(404, "issue not found")
    return defect_report(issue)


@app.delete("/api/issues", status_code=204)
def reset_issues():
    """Start the demo over: empty issue tracker."""
    (DATA_DIR / "issues.json").unlink(missing_ok=True)


@app.get("/api/guidance")
def guidance_sample():
    """XTE of the real NMEA sample track against its AB line."""
    cfg = spec.guidance
    fixes = read_nmea_file(SAMPLES_DIR / "nmea" / "ijsselmeer_bg_zeus2.nmea")
    line = ab_line_from_track(fixes, cfg["min_speed_mps"])
    result = evaluate_track(fixes, line, cfg["classes"], cfg["min_speed_mps"], cfg["max_heading_dev_deg"])
    used = result.points[result.points["used"]]
    return {
        "source": "B&G Zeus2 chartplotter, IJsselmeer NL, 2018 (gpsd test corpus, BSD-2-Clause)",
        "fix_class": result.fix_class,
        "limit_m": result.limit_m,
        "passed": result.passed,
        "stats": result.stats,
        "line_heading_deg": round(line.heading_deg, 1),
        "points": {
            "t": [round(t - used["time_s"].iloc[0], 1) for t in used["time_s"]],
            "xte": [round(x, 3) for x in used["xte_m"]],
            "east": [round(x, 2) for x in used["east_m"]],
            "north": [round(y, 2) for y in used["north_m"]],
        },
    }


@app.post("/api/analyze")
async def analyze_log(file: UploadFile):
    """Upload a Vector ASC/BLF log: message statistics and dropouts."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".asc", ".blf"):
        raise HTTPException(422, "upload a .asc or .blf file")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file larger than 5 MB")
    # ignore_cleanup_errors: on Windows a reader that failed may still hold the file
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(data)
        try:
            capture = decode(read_log(path), db)
        except Exception as exc:
            raise HTTPException(422, f"could not read log: {exc}") from exc
    cycles = dbc_cycle_times(db)
    return {
        "frames": len(capture.frames),
        "error_frames": capture.error_frames,
        "messages": _records(message_stats(capture, cycles)),
        "dropouts": [asdict(d) | {"gap_ms": d.gap_ms} for d in find_dropouts(capture, cycles)],
    }
