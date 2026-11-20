"""Excel and HTML test reports for a campaign."""

from __future__ import annotations

import base64
from pathlib import Path

import pandas as pd
from jinja2 import Environment, PackageLoader, select_autoescape

from .spec import Spec

_env = Environment(loader=PackageLoader("fieldbench", "templates"), autoescape=select_autoescape(["html", "j2"]))
_env.filters["basename"] = lambda path: Path(path).name


def tables(summary, spec: Spec) -> dict[str, pd.DataFrame]:
    procedures = pd.DataFrame(
        [
            {
                "procedure": r.procedure.id,
                "title": r.procedure.title,
                "requirement": r.procedure.requirement,
                "release": r.release,
                "result": "PASS" if r.passed else "FAIL",
                "checks": len(r.checks),
                "failed checks": len(r.failed_checks()),
                "runtime_s": round(r.duration_s, 2),
            }
            for r in summary.results
        ]
    )
    checks = pd.DataFrame(
        [
            {
                "procedure": r.procedure.id,
                "check": c.name,
                "expected": c.expected,
                "measured": c.measured,
                "result": "PASS" if c.passed else "FAIL",
            }
            for r in summary.results
            for c in r.checks
        ]
    )
    issues = pd.DataFrame(
        [
            {
                "id": i.id,
                "title": i.title,
                "severity": i.severity,
                "status": i.status,
                "found in": i.found_in,
                "verified in": i.verified_in or "",
                "occurrences": i.occurrences,
            }
            for i in summary.issues
        ],
        columns=["id", "title", "severity", "status", "found in", "verified in", "occurrences"],
    )
    overview = pd.DataFrame(
        [
            {"item": "System", "value": spec.system},
            {"item": "Software release", "value": summary.release},
            {"item": "Started", "value": summary.started},
            {"item": "Procedures", "value": len(summary.results)},
            {"item": "Passed", "value": summary.passed},
            {"item": "Failed", "value": summary.failed},
            {"item": "Open issues", "value": sum(i.status == "open" for i in summary.issues)},
        ]
    )
    return {"Summary": overview, "Procedures": procedures, "Checks": checks, "Issues": issues}


def write_excel(frames: dict[str, pd.DataFrame], path: Path) -> Path:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet, index=False)
            ws = writer.sheets[sheet]
            for column in ws.columns:  # readable column widths
                width = max(len(str(cell.value or "")) for cell in column)
                ws.column_dimensions[column[0].column_letter].width = min(max(10, width + 2), 70)
    return path


def _image(path: str | None) -> str | None:
    if not path or not Path(path).exists():
        return None
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def write_html(summary, spec: Spec, path: Path) -> Path:
    template = _env.get_template("report.html.j2")
    html = template.render(
        summary=summary,
        spec=spec,
        plots={r.procedure.id: _image(r.files.get("plot")) for r in summary.results},
    )
    path.write_text(html, encoding="utf-8")
    return path


def write_reports(summary, spec: Spec, out_dir: Path) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"report_{summary.release}"
    xlsx = write_excel(tables(summary, spec), out_dir / f"{stem}.xlsx")
    html = write_html(summary, spec, out_dir / f"{stem}.html")
    return {"xlsx": str(xlsx), "html": str(html)}
