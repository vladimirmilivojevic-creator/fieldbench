import openpyxl

from fieldbench.campaign import reproduction_steps, run_campaign

SUBSET = ["TP-SIG-01", "TP-GUI-12", "TP-GUI-21"]


def test_defects_found_then_verified(tmp_path, spec):
    tracker = tmp_path / "issues.json"
    old = run_campaign(spec, "1.3.0", tmp_path / "r130", tracker, SUBSET, plots=False)
    assert (old.passed, old.failed) == (1, 2)
    assert {i.procedure for i in old.issues} == {"TP-SIG-01", "TP-GUI-12"}
    assert all(i.status == "open" for i in old.issues)
    safety = next(i for i in old.issues if i.procedure == "TP-GUI-12")
    assert safety.severity == "high (safety)"
    assert "SteeringEngaged=1" in safety.log_excerpt

    new = run_campaign(spec, "1.4.0", tmp_path / "r140", tracker, SUBSET, plots=True)
    assert new.failed == 0
    assert {i.status for i in new.issues} == {"fix verified"}

    html = (tmp_path / "r140" / "report_1.4.0.html").read_text(encoding="utf-8")
    assert "fix verified" in html and "data:image/png;base64" in html
    workbook = openpyxl.load_workbook(tmp_path / "r140" / "report_1.4.0.xlsx")
    assert workbook.sheetnames == ["Summary", "Procedures", "Checks", "Issues"]
    assert (tmp_path / "r130" / "issues" / "FB-001.md").exists()
    assert (tmp_path / "r140" / "logs" / "TP-SIG-01_1.4.0.blf").exists()


def test_reproduction_steps_mention_faults(spec):
    steps = reproduction_steps(spec, spec.procedure("TP-GUI-20"), "1.3.0")
    assert any("Inject fault 'drop' WBSD at 5 s" in s for s in steps)
    assert steps[-1].startswith("Run `pytest procedures -k TP-GUI-20 --release 1.3.0`")
