import json
from hashlib import sha256
from pathlib import Path

from xuanyi_npc.evaluation import v2_regression_preflight
from xuanyi_npc.evaluation.v2_regression_preflight import ROOT, main
from xuanyi_npc.evaluation.v2_runner import build_parser


def _plan(tmp_path: Path, expected_hash: str) -> Path:
    relative = "src/xuanyi_npc/evaluation/v2_graders.py"
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({
        "runtime_hashes": {relative: expected_hash},
        "task_runs": [{"scenario_id": "T07"}],
        "memory_pair": {"scenario_id": "M01"},
        "result_root": str(tmp_path / "results"),
        "budget": {"total_hard_cap_cny": 3.0},
    }), encoding="utf-8")
    return path


def test_regression_preflight_accepts_frozen_subset_without_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(v2_regression_preflight, "_bge_runtime_probe", lambda: {
        "actual_embedding_computed": True, "dimension": 1024,
    })
    runtime = ROOT / "src/xuanyi_npc/evaluation/v2_graders.py"
    plan = _plan(tmp_path, sha256(runtime.read_bytes()).hexdigest())

    assert main(["--plan", str(plan)]) == 0


def test_regression_preflight_rejects_runtime_hash_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(v2_regression_preflight, "_bge_runtime_probe", lambda: {
        "actual_embedding_computed": True, "dimension": 1024,
    })
    plan = _plan(tmp_path, "0" * 64)

    assert main(["--plan", str(plan)]) == 2


def test_regression_preflight_fails_when_real_bge_inference_fails(tmp_path, monkeypatch):
    runtime = ROOT / "src/xuanyi_npc/evaluation/v2_graders.py"
    plan = _plan(tmp_path, sha256(runtime.read_bytes()).hexdigest())
    monkeypatch.setattr(
        v2_regression_preflight, "_bge_runtime_probe",
        lambda: (_ for _ in ()).throw(RuntimeError("ABI conflict")),
    )

    assert main(["--plan", str(plan)]) == 2


def test_regression_preflight_accepts_full_formal_scenario_lists(tmp_path, monkeypatch):
    monkeypatch.setattr(v2_regression_preflight, "_bge_runtime_probe", lambda: {
        "actual_embedding_computed": True, "dimension": 1024,
    })
    runtime = ROOT / "src/xuanyi_npc/evaluation/v2_graders.py"
    plan = tmp_path / "formal_plan.json"
    plan.write_text(json.dumps({
        "runtime_hashes": {
            "src/xuanyi_npc/evaluation/v2_graders.py":
                sha256(runtime.read_bytes()).hexdigest(),
        },
        "task_scenario_ids": [f"T{index:02d}" for index in range(1, 25)],
        "task_repeats": 3,
        "memory_scenario_ids": [f"M{index:02d}" for index in range(1, 7)],
        "memory_repeats": 3,
        "result_root": str(tmp_path / "formal_results"),
        "budget": {"total_hard_cap_cny": 40.0},
    }), encoding="utf-8")

    assert main(["--plan", str(plan)]) == 0


def test_task_runner_accepts_explicit_small_batch_selection():
    args = build_parser().parse_args([
        "--phase", "full", "--experiment-id", "batch_test",
        "--scenario-id", "T07", "--scenario-id", "T23", "--repeats", "1",
    ])

    assert args.scenario_id == ["T07", "T23"]
    assert args.repeats == 1
