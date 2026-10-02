"""Offline-only validator for the frozen V2 small-batch regression plan."""
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys

from xuanyi_npc.evaluation.v2_scenarios import resolve_scenarios


ROOT = Path(__file__).resolve().parents[3]


def _bge_runtime_probe() -> dict[str, object]:
    """Load the frozen BGE model and execute one real local inference."""
    expected = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if Path(sys.executable).resolve() != expected.resolve():
        raise RuntimeError(
            f"project virtualenv required: expected {expected.resolve()}, got {Path(sys.executable).resolve()}"
        )
    from xuanyi_npc.evaluation.v2_memory_pairs import _embedding_adapter
    from xuanyi_npc.memory import EmbeddingRequest, EmbeddingRequestItem

    adapter = _embedding_adapter()
    result = adapter.embed(EmbeddingRequest(
        embedding_space_id=adapter.embedding_space_id,
        dimension=adapter.dimension,
        items=(EmbeddingRequestItem(
            item_id="v2_preflight_probe",
            text="V2 付费前本地向量预检：只验证模型加载与一次实际推理。",
        ),),
    ))
    vector = result.items[0].vector
    return {
        "python_executable": str(Path(sys.executable).resolve()),
        "numpy": importlib.metadata.version("numpy"),
        "scipy": importlib.metadata.version("scipy"),
        "scikit_learn": importlib.metadata.version("scikit-learn"),
        "sentence_transformers": importlib.metadata.version("sentence-transformers"),
        "embedding_space_id": result.embedding_space_id,
        "dimension": len(vector),
        "l2_norm": math.sqrt(sum(value * value for value in vector)),
        "actual_embedding_computed": True,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    errors: list[str] = []
    for relative, expected in plan["runtime_hashes"].items():
        path = ROOT / relative
        actual = sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if actual != expected:
            errors.append(f"runtime hash mismatch: {relative}")
    resolved, _ = resolve_scenarios()
    available = {item["id"] for item in resolved["scenarios"]}
    selected = {item["scenario_id"] for item in plan.get("task_runs", ())}
    selected.update(plan.get("task_scenario_ids", ()))
    if plan.get("memory_pair"):
        selected.add(plan["memory_pair"]["scenario_id"])
    selected.update(
        item["scenario_id"] for item in plan.get("memory_pairs", ())
    )
    selected.update(plan.get("memory_scenario_ids", ()))
    missing = selected - available
    if missing:
        errors.append(f"scenario IDs missing from resolved catalog: {sorted(missing)}")
    result_root = ROOT / plan["result_root"]
    for child in ("real_model_trials", "real_model_memory_pairs"):
        if (result_root / child).exists():
            errors.append(f"immutable output already exists: {result_root / child}")
    bge_probe = None
    if not errors:
        try:
            bge_probe = _bge_runtime_probe()
        except Exception as exc:
            errors.append(f"BGE real inference preflight failed: {type(exc).__name__}: {exc}")
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "status": "READY", "paid_model_calls": 0,
        "task_runs": len(plan.get("task_runs", ())) or (
            len(plan.get("task_scenario_ids", ()))
            * int(plan.get("task_repeats", 1))
        ),
        "memory_target_runs": (
            3 if plan.get("memory_pair") else
            len(plan.get("memory_pairs", ())) * 3 or
            len(plan.get("memory_scenario_ids", ()))
            * int(plan.get("memory_repeats", 1)) * 3
        ),
        "total_hard_budget_cny": plan["budget"]["total_hard_cap_cny"],
        "bge_preflight": bge_probe,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
