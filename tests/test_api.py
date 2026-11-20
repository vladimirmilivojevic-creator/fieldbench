import time

import pytest
from fastapi.testclient import TestClient

from fieldbench import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", tmp_path)
    api.runs.clear()
    with TestClient(api.app) as c:
        yield c


def wait_done(client, run_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] in ("done", "error"):
            return run
        time.sleep(0.1)
    raise AssertionError("run did not finish")


def test_health_and_spec(client):
    assert client.get("/health").json()["status"] == "ok"
    spec = client.get("/api/spec").json()
    assert {r["version"] for r in spec["releases"]} == {"1.3.0", "1.4.0"}
    assert any(p["id"] == "TP-GUI-10" and p["safety"] for p in spec["procedures"])


def test_run_campaign_end_to_end(client):
    started = client.post("/api/runs", json={"release": "1.3.0", "procedures": ["TP-SIG-01", "TP-GUI-10"]})
    assert started.status_code == 202
    run = wait_done(client, started.json()["id"])
    assert run["status"] == "done" and (run["passed"], run["failed"]) == (1, 1)
    run_id = run["id"]

    signals = client.get(f"/api/runs/{run_id}/signals/TP-GUI-10").json()
    assert "SteeringEngaged" in signals["signals"]
    assert signals["faults"][0]["type"] == "gnss_dropout"
    assert {d["message"] for d in signals["dropouts"]} == {"GNSS_POSITION", "GNSS_COG_SOG"}

    assert client.get(f"/api/runs/{run_id}/report.html").text.startswith("<!doctype html>")
    assert client.get(f"/api/runs/{run_id}/report.xlsx").status_code == 200
    assert client.get(f"/api/runs/{run_id}/logs/TP-GUI-10_1.3.0.asc").status_code == 200
    assert client.get(f"/api/runs/{run_id}/logs/..%2F..%2Fissues.json").status_code == 404
    assert client.get(f"/api/runs/{run_id}/logs/x.txt").status_code == 404

    issues = client.get("/api/issues").json()
    assert [i["procedure"] for i in issues] == ["TP-SIG-01"]
    assert client.get("/api/issues/FB-001.md").text.startswith("# FB-001")
    assert client.get("/api/issues/FB-999.md").status_code == 404
    assert client.get("/api/runs").json()[0]["id"] == run_id

    assert client.delete("/api/issues").status_code == 204
    assert client.get("/api/issues").json() == []


def test_run_validation(client):
    assert client.post("/api/runs", json={"release": "9.9.9"}).status_code == 422
    assert client.post("/api/runs", json={"procedures": ["TP-NOPE"]}).status_code == 422
    assert client.get("/api/runs/nope").status_code == 404


def test_busy_bench_returns_429(client):
    for i in range(api.MAX_QUEUED):
        api.runs[f"busy{i}"] = {"status": "running"}
    assert client.post("/api/runs", json={}).status_code == 429


def test_signals_and_files_before_done(client):
    api.runs["r1"] = {"id": "r1", "release": "1.4.0", "status": "running", "results": [], "summary": None}
    assert client.get("/api/runs/r1/signals/TP-GUI-10").status_code == 404
    assert client.get("/api/runs/r1/report.html").status_code == 409


def test_failed_run_reports_error(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("bench exploded")

    monkeypatch.setattr(api, "run_procedure", broken)
    run_id = client.post("/api/runs", json={"procedures": ["TP-COM-01"]}).json()["id"]
    run = wait_done(client, run_id)
    assert run["status"] == "error" and "exploded" in run["error"]


def test_guidance_sample(client):
    body = client.get("/api/guidance").json()
    assert body["fix_class"] == "GPS" and body["passed"] is False
    assert len(body["points"]["xte"]) == body["stats"]["fixes_used"]


def test_analyze_upload(client, tmp_path, nominal_messages):
    from fieldbench.analysis import write_logs

    blf, _ = write_logs(nominal_messages, tmp_path / "upload")
    body = client.post("/api/analyze", files={"file": ("field.blf", blf.read_bytes())}).json()
    assert body["frames"] == len(nominal_messages) and body["dropouts"] == []
    assert client.post("/api/analyze", files={"file": ("notes.txt", b"hi")}).status_code == 422
    assert client.post("/api/analyze", files={"file": ("bad.blf", b"not a blf")}).status_code == 422


def test_upload_too_large(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 10)
    assert client.post("/api/analyze", files={"file": ("big.asc", b"x" * 20)}).status_code == 413
