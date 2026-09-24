import json
from pathlib import Path

from aifa_pyrit.pyrit_runner import PyRITRunner


def test_save_result_payload_writes_to_results_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = PyRITRunner()

    result = {
        "query": "sample query",
        "attack_type": "CrescendoAttack",
        "results": {"total_turns": 1, "turns": [{"turn": 1, "prompt": "hi", "response": "hello"}]},
    }

    path = runner.save_result_payload(result, attack_name="Crescendo")

    assert Path(path).exists()
    saved = json.loads(Path(path).read_text())
    assert saved["attack_type"] == "CrescendoAttack"
    assert saved["query"] == "sample query"
    assert str(tmp_path / "results") in path
