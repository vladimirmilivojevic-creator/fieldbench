"""A small issue tracker kept as one JSON file next to the results.

Lifecycle: a failing check opens an issue (or adds an occurrence to the open
one). When the same procedure passes on a later software release, the issue
is marked "fix verified" with that release. Each issue is also written as a
Markdown defect report that can be pasted into Jira / GitHub Issues.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

OPEN, VERIFIED = "open", "fix verified"


@dataclass
class Issue:
    id: str
    key: str  # procedure id + check name: the same failure maps to the same issue
    title: str
    procedure: str
    requirement: str
    severity: str
    status: str
    found_in: str
    expected: str
    actual: str
    steps: list[str]
    log_excerpt: str
    attachments: list[str] = field(default_factory=list)
    occurrences: int = 1
    verified_in: str | None = None
    first_seen: str = ""
    last_seen: str = ""


class IssueTracker:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.issues: list[Issue] = []
        if self.path and self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.issues = [Issue(**item) for item in raw]

    def _find_open(self, key: str) -> Issue | None:
        return next((i for i in self.issues if i.key == key and i.status == OPEN), None)

    def report_failure(self, key: str, **details) -> Issue:
        now = _now()
        issue = self._find_open(key)
        if issue:
            issue.occurrences += 1
            issue.last_seen = now
            issue.actual = details["actual"]
            return issue
        issue = Issue(
            id=f"FB-{len(self.issues) + 1:03d}",
            key=key,
            status=OPEN,
            first_seen=now,
            last_seen=now,
            **details,
        )
        self.issues.append(issue)
        return issue

    def verify_passed(self, procedure: str, release: str) -> list[Issue]:
        """A procedure passed on `release`: close its open issues."""
        closed = []
        for issue in self.issues:
            if issue.procedure == procedure and issue.status == OPEN and issue.found_in != release:
                issue.status, issue.verified_in, issue.last_seen = VERIFIED, release, _now()
                closed.append(issue)
        return closed

    def open_issues(self) -> list[Issue]:
        return [i for i in self.issues if i.status == OPEN]

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = [asdict(i) for i in self.issues]
            self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def write_reports(self, folder: str | Path) -> list[Path]:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        paths = []
        for issue in self.issues:
            path = folder / f"{issue.id}.md"
            path.write_text(defect_report(issue), encoding="utf-8")
            paths.append(path)
        return paths


def defect_report(issue: Issue) -> str:
    steps = "\n".join(f"{n}. {step}" for n, step in enumerate(issue.steps, 1))
    attachments = "\n".join(f"- `{a}`" for a in issue.attachments) or "- none"
    verified = f"\n**Fix verified in:** {issue.verified_in}" if issue.verified_in else ""
    return f"""# {issue.id}: {issue.title}

| Field | Value |
|---|---|
| Status | {issue.status} |
| Severity | {issue.severity} |
| Procedure | {issue.procedure} |
| Requirement | {issue.requirement} |
| Found in release | {issue.found_in} |
| Occurrences | {issue.occurrences} |
| First seen | {issue.first_seen} |
{verified}

## Steps to reproduce
{steps}

## Expected
{issue.expected}

## Actual
{issue.actual}

## Log excerpt (ASC, decoded)
```
{issue.log_excerpt}
```

## Attachments
{attachments}
"""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
