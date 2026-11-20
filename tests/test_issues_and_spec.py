import pytest

from fieldbench.issues import OPEN, VERIFIED, IssueTracker, defect_report
from fieldbench.spec import load_spec


def details(**overrides):
    base = {
        "title": "hitch out of range",
        "procedure": "TP-SIG-01",
        "requirement": "REQ-SIG-001",
        "severity": "medium",
        "found_in": "1.3.0",
        "expected": "0..100 %",
        "actual": "20..102 %",
        "steps": ["flash 1.3.0", "run"],
        "log_excerpt": "13.0 1 CFE45F0x Rx d 8 FF",
    }
    return base | overrides


def test_tracker_lifecycle(tmp_path):
    path = tmp_path / "issues.json"
    tracker = IssueTracker(path)
    first = tracker.report_failure("TP-SIG-01/range", **details())
    again = tracker.report_failure("TP-SIG-01/range", **details(actual="20..103 %"))
    assert first is again and again.occurrences == 2 and again.actual == "20..103 %"
    assert tracker.verify_passed("TP-SIG-01", "1.3.0") == []  # same release is not a fix
    tracker.save()

    reloaded = IssueTracker(path)
    assert [i.id for i in reloaded.open_issues()] == ["FB-001"]
    [closed] = reloaded.verify_passed("TP-SIG-01", "1.4.0")
    assert closed.status == VERIFIED and closed.verified_in == "1.4.0"

    # a regression later opens a new issue, the verified one stays closed
    new = reloaded.report_failure("TP-SIG-01/range", **details(found_in="1.5.0"))
    assert new.id == "FB-002" and new.status == OPEN


def test_defect_report_markdown(tmp_path):
    tracker = IssueTracker()
    tracker.report_failure("k", **details(attachments=["TP-SIG-01_1.3.0.blf"]))
    text = defect_report(tracker.issues[0])
    assert text.startswith("# FB-001: hitch out of range")
    assert "1. flash 1.3.0" in text and "`TP-SIG-01_1.3.0.blf`" in text
    [path] = tracker.write_reports(tmp_path)
    assert path.read_text(encoding="utf-8") == text
    tracker.save()  # no path: nothing to do


def test_every_requirement_has_a_procedure(spec):
    """Traceability: a requirement without a test procedure is a gap in the test plan."""
    covered = {p.requirement for p in spec.procedures}
    assert set(spec.requirements) - covered == set()


def test_spec_loads(spec):
    assert spec.bitrate == 250000
    assert spec.procedure("TP-GUI-10").faults[0]["type"] == "gnss_dropout"
    with pytest.raises(KeyError):
        spec.procedure("TP-NOPE")


@pytest.mark.parametrize(
    ("needle", "replacement", "error"),
    [
        ("requirement: REQ-GUI-001\n", "requirement: REQ-TYPO\n", "unknown requirement"),
        (
            "scenario: field_pass\n    checks:\n      - {type: timeouts}",
            "scenario: moon\n    checks:\n      - {type: timeouts}",
            "unknown scenario",
        ),
        ("id: TP-COM-02", "id: TP-COM-01", "duplicate"),
    ],
)
def test_spec_validation(tmp_path, needle, replacement, error):
    from fieldbench.spec import DEFAULT_SPEC

    text = DEFAULT_SPEC.read_text(encoding="utf-8")
    assert needle in text
    bad = tmp_path / "spec.yaml"
    bad.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        load_spec(bad)
