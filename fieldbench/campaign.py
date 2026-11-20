"""Run test procedures from the spec and turn failures into issues.

Used by the pytest procedures (procedures/), the CLI and the web API, so
all three produce the same results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import can
import cantools

from .analysis import Capture, asc_excerpt, decode, find_dropouts, plot_signals, write_logs
from .bench import load_dbc, simulate
from .checks import CheckResult, run_checks
from .ecus import RELEASES
from .faults import FaultInjector
from .issues import Issue, IssueTracker
from .spec import Procedure, Spec

PLOT_SIGNALS = ["SteeringEngaged", "ExitReason", "WheelBasedSpeed", "RearHitchPosition", "CrossTrackError"]


@dataclass
class ProcedureResult:
    procedure: Procedure
    release: str
    checks: list[CheckResult]
    duration_s: float
    messages: list[can.Message] = field(repr=False)
    capture: Capture = field(repr=False)
    files: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failed_checks(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]


@dataclass
class CampaignSummary:
    release: str
    started: str
    results: list[ProcedureResult]
    issues: list[Issue]
    files: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> int:
        return sum(r.passed for r in self.results)

    @property
    def failed(self) -> int:
        return len(self.results) - self.passed


def run_procedure(
    spec: Spec,
    procedure: Procedure,
    release: str,
    db: cantools.database.Database | None = None,
    out_dir: str | Path | None = None,
    plots: bool = False,
) -> ProcedureResult:
    db = db or load_dbc()
    started = time.perf_counter()
    scenario = spec.scenarios[procedure.scenario]
    messages = simulate(scenario, RELEASES[release], procedure.faults, db)
    capture = decode(messages, db)
    checks = run_checks(procedure.checks, capture, spec)
    result = ProcedureResult(procedure, release, checks, time.perf_counter() - started, messages, capture)

    if out_dir:
        blf, asc = write_logs(messages, Path(out_dir) / "logs" / f"{procedure.id}_{release}")
        result.files.update(blf=str(blf), asc=str(asc))
        if plots:
            result.files["plot"] = str(plot_procedure(result, spec, Path(out_dir) / "plots"))
    return result


def plot_procedure(result: ProcedureResult, spec: Spec, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    cycles = {m.name: m.cycle_ms for m in spec.messages.values()}
    spans = FaultInjector(result.procedure.faults).windows()
    status = "PASS" if result.passed else "FAIL"
    return plot_signals(
        result.capture,
        PLOT_SIGNALS,
        folder / f"{result.procedure.id}_{result.release}.png",
        spans=spans,
        dropouts=find_dropouts(result.capture, cycles),
        title=f"{result.procedure.id} {result.procedure.title} - release {result.release} - {status}",
    )


def reproduction_steps(spec: Spec, procedure: Procedure, release: str) -> list[str]:
    s = spec.scenarios[procedure.scenario]
    steps = [
        f"Flash software release {release} on the bench ECUs.",
        f"Start scenario '{s.name}': {s.speed_kmh:g} km/h, {s.engine_rpm:g} rpm, heading {s.heading_deg:g} deg, "
        f"operator engages auto-steering at {s.operator_engage_s:g} s.",
    ]
    for f in procedure.faults:
        target = f.get("message") or f.get("ecu") or ""
        steps.append(
            f"Inject fault '{f['type']}' {target} at {f['at_s']:g} s for {f['duration_s']:g} s.".replace("  ", " ")
        )
    steps.append(f"Run `pytest procedures -k {procedure.id} --release {release}` and check the result.")
    return steps


def file_issues(results: list[ProcedureResult], spec: Spec, tracker: IssueTracker, db) -> list[Issue]:
    """Open/update an issue per failed check; verify fixes for passed procedures."""
    touched = []
    for r in results:
        p = r.procedure
        if r.passed:
            touched += tracker.verify_passed(p.id, r.release)
            continue
        requirement = spec.requirements[p.requirement]
        for check in r.failed_checks():
            t = check.t_s if check.t_s is not None else 0.0
            touched.append(
                tracker.report_failure(
                    key=f"{p.id}/{check.name}",
                    title=f"{p.title}: {check.name}",
                    procedure=p.id,
                    requirement=f"{p.requirement} - {requirement.text}",
                    severity="high (safety)" if requirement.safety else "medium",
                    found_in=r.release,
                    expected=check.expected,
                    actual=check.measured,
                    steps=reproduction_steps(spec, p, r.release),
                    log_excerpt=asc_excerpt(r.messages, db, t - 0.15, t + 0.15),
                    attachments=[Path(v).name for v in r.files.values()],
                )
            )
    tracker.save()
    return touched


def run_campaign(
    spec: Spec,
    release: str,
    out_dir: str | Path,
    tracker_path: str | Path | None = None,
    procedure_ids: list[str] | None = None,
    plots: bool = True,
) -> CampaignSummary:
    """Run procedures, file issues and write the Excel + HTML report."""

    db = load_dbc()
    out_dir = Path(out_dir)
    procedures = [p for p in spec.procedures if not procedure_ids or p.id in procedure_ids]
    started = now_utc()
    results = [run_procedure(spec, p, release, db, out_dir, plots) for p in procedures]
    return finish_campaign(spec, release, started, results, out_dir, tracker_path, db)


def finish_campaign(spec, release, started, results, out_dir, tracker_path=None, db=None) -> CampaignSummary:
    from .report import write_reports

    db = db or load_dbc()
    out_dir = Path(out_dir)
    tracker = IssueTracker(tracker_path or out_dir / "issues.json")
    file_issues(results, spec, tracker, db)
    tracker.write_reports(out_dir / "issues")
    summary = CampaignSummary(release, started, results, tracker.issues)
    summary.files = write_reports(summary, spec, out_dir)
    return summary


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
