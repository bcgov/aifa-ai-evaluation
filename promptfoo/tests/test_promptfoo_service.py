import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from promptfoo.src import promptfoo_service as svc


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(svc, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(svc, "CONFIG_WORKSPACE", tmp_path / "configs")
    monkeypatch.setattr(svc, "META_DIR", tmp_path / ".meta")
    monkeypatch.setattr(svc, "RUN_TOKEN", "")
    svc.JOBS.jobs.clear()
    with TestClient(svc.app) as test_client:
        yield test_client


def test_eval_argv_is_validated_and_never_shell_interpolated(client):
    steps, output, config, eval_config = svc.build_steps(
        svc.COMMANDS["eval"],
        {"config": "promptfoo-config.yaml", "filter_pattern": "--evil; rm -rf /", "repeat": 2},
    )
    argv = steps[0]
    assert "--filter-pattern=--evil; rm -rf /" in argv
    assert "--repeat=2" in argv
    assert any(a.startswith("--output=") and a.endswith(".json") for a in argv)
    assert config == eval_config == "promptfoo-config.yaml"
    assert output.parent == svc.RESULTS_DIR


@pytest.mark.parametrize("options", [
    {"config": "../../etc/passwd"},
    {"config": "promptfoo-config.yaml", "repeat": 999},
    {"config": "promptfoo-config.yaml", "unknown": 1},
    {"config": "promptfoo-config.yaml", "filter_pattern": "line\nbreak"},
])
def test_eval_rejects_bad_options(client, options):
    response = client.post("/api/promptfoo/jobs", json={"command": "eval", "options": options})
    assert response.status_code in {400, 404}


def test_unknown_command_is_rejected(client):
    response = client.post("/api/promptfoo/jobs", json={"command": "share", "options": {}})
    assert response.status_code == 400


def test_token_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(svc, "RUN_TOKEN", "secret")
    assert client.get("/api/promptfoo/commands").status_code == 401
    assert client.get("/api/promptfoo/commands", headers={"x-run-token": "secret"}).status_code == 200


def test_attack_config_targets_only_the_adapter(client):
    response = client.post("/api/promptfoo/attacks", json={
        "name": "My scan", "purpose": "Water licence assistant", "plugins": ["hallucination"],
        "strategies": ["basic"], "action": "save",
    })
    assert response.status_code == 200
    name = response.json()["config"]
    config = json.loads((svc.CONFIG_WORKSPACE / name).read_text())
    assert config["targets"][0]["config"]["url"] == svc.TARGET_URL
    assert config["redteam"]["plugins"] == [{"id": "hallucination"}]
    assert "apiKey" not in json.dumps(config).replace("apiKeyEnvar", "")
    assert any(c["name"] == name for c in client.get("/api/promptfoo/configs").json())


def test_attack_rejects_unknown_plugin(client):
    response = client.post("/api/promptfoo/attacks", json={
        "name": "x", "purpose": "Water licence assistant", "plugins": ["exec:rm"], "action": "save",
    })
    assert response.status_code == 400


def test_result_parsing_and_csv(client):
    report = {
        "evalId": "eval-1",
        "config": {"description": "scan", "redteam": {}},
        "results": {"results": [
            {"success": True, "score": 1, "prompt": {"raw": "hi"}, "response": {"output": "ok"},
             "testCase": {"metadata": {"pluginId": "hallucination"}}},
            {"success": False, "score": 0, "prompt": {"raw": "=cmd"}, "response": {"output": "leak"},
             "gradingResult": {"reason": "leaked"},
             "testCase": {"metadata": {"pluginId": "pii:direct", "strategyId": "jailbreak"}}},
            {"success": False, "error": "timeout", "failureReason": 2, "testCase": {}},
        ]},
    }
    (svc.RESULTS_DIR / "r.json").write_text(json.dumps(report))
    detail = client.get("/api/promptfoo/results/r.json").json()
    assert (detail["summary"]["pass"], detail["summary"]["fail"], detail["summary"]["error"]) == (1, 1, 1)
    assert detail["summary"]["pass_rate"] == 50.0
    assert {g["name"] for g in detail["by_strategy"]} >= {"jailbreak", "basic"}
    assert client.get("/api/promptfoo/results/r.json?status=fail").json()["row_count"] == 1
    csv_text = client.get("/api/promptfoo/results/r.json/csv").text
    assert "'=cmd" in csv_text
    assert client.get("/api/promptfoo/results/..%2Fx.json").status_code == 404


def test_job_runs_and_streams_logs(client, tmp_path, monkeypatch):
    fake = tmp_path / "fake_promptfoo.py"
    fake.write_text(
        "import sys, json\n"
        "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--output=')]\n"
        "print('running', ' '.join(sys.argv[1:3]))\n"
        "if out: open(out[0], 'w').write(json.dumps({'results': {'results': [{'success': False}]}}))\n"
        "sys.exit(100)\n"
    )
    monkeypatch.setenv("PROMPTFOO_BIN", f"{sys.executable} {fake}")
    job = client.post("/api/promptfoo/jobs", json={"command": "eval", "options": {"config": "promptfoo-config.yaml"}}).json()
    for _ in range(100):
        state = client.get(f"/api/promptfoo/jobs/{job['id']}").json()
        if state["status"] not in {"queued", "running"}:
            break
        time.sleep(0.05)
    assert state["status"] == "succeeded"
    assert state["exit_code"] == 100
    assert state["output"].endswith(".json")
    logs = client.get(f"/api/promptfoo/jobs/{job['id']}/logs?since=0").json()
    assert any("running eval" in line for line in logs["lines"])
    listed = client.get("/api/promptfoo/results").json()
    assert listed[0]["meta"]["eval_config"] == "promptfoo-config.yaml"
