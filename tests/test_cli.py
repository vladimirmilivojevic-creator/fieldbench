import json

import pytest

from fieldbench import cli


def test_simulate_then_analyze(tmp_path, capsys):
    fault = json.dumps({"type": "gnss_dropout", "at_s": 3, "duration_s": 1})
    assert cli.main(["simulate", "--fault", fault, "--out", str(tmp_path / "rec")]) == 0
    assert (tmp_path / "rec.blf").exists()
    assert cli.main(["analyze", str(tmp_path / "rec.blf"), "--plot", str(tmp_path / "a.png")]) == 0
    out = capsys.readouterr().out
    assert "dropouts (gap > 3 x cycle): 2" in out
    assert (tmp_path / "a.png").exists()


def test_guidance_on_real_track(tmp_path, capsys, samples):
    nmea = str(samples / "nmea" / "ijsselmeer_bg_zeus2.nmea")
    assert cli.main(["guidance", "--nmea", nmea, "--plot", str(tmp_path / "x.png")]) == 0
    out = capsys.readouterr().out
    assert "accuracy class GPS" in out and "FAIL" in out
    assert cli.main(["guidance", "--nmea", nmea, "--strict"]) == 1


def test_guidance_with_explicit_ab_line(capsys, samples):
    nmea = str(samples / "nmea" / "ijsselmeer_bg_zeus2.nmea")
    ab = ["52.85015", "5.31362", "52.8341", "5.2767"]
    assert cli.main(["guidance", "--nmea", nmea, "--ab", *ab]) == 0
    assert "AB line heading" in capsys.readouterr().out


def test_run_builds_pytest_arguments(monkeypatch):
    seen = {}
    monkeypatch.setattr("pytest.main", lambda argv: seen.setdefault("argv", argv) and 0)
    cli.main(["run", "--release", "1.3.0", "-k", "TP-GUI", "--no-plots", "--results", "out"])
    argv = seen["argv"]
    assert argv[0].endswith("procedures")
    assert "--release=1.3.0" in argv and "TP-GUI" in argv and "--no-plots" in argv


def test_serve_starts_uvicorn(monkeypatch):
    called = {}
    monkeypatch.setattr("uvicorn.run", lambda app, host, port: called.update(app=app, port=port))
    cli.main(["serve", "--port", "9999"])
    assert called == {"app": "fieldbench.api:app", "port": 9999}


def test_no_command_is_an_error():
    with pytest.raises(SystemExit):
        cli.main([])
