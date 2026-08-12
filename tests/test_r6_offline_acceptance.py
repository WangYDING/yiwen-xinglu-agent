import json
from xuanyi_npc.evaluation.product_acceptance import run_acceptance


def test_eight_routes_and_two_normalized_runs_pass_offline(tmp_path):
    result = run_acceptance(tmp_path)
    assert result["status"] == "offline_passed_r6_in_progress"
    assert len(result["routes"]) == 8
    assert result["determinism"]["matched"]
    assert result["determinism"]["run_1_hash"] == result["determinism"]["run_2_hash"]
    assert result["routes"][5]["score"] == result["routes"][6]["score"] == 100
    assert result["routes"][6]["ordinary_investigations_saved"] == 1


def test_runner_reports_truthful_zero_external_boundary(tmp_path):
    result = run_acceptance(tmp_path)
    assert set(result["external_calls"].values()) == {0}
    assert result["truthfulness"] == {
        "real_model": "not_run", "human_playtest": "not_executed",
        "remote_release": "not_executed", "r6": "in_progress",
    }
    serialized = json.dumps(result, ensure_ascii=False).lower()
    assert "api_key" not in serialized and "prompt" not in serialized
