"""Validate the V2 design inventory only. Never executes an Agent or provider."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def validate() -> dict:
    config = json.loads((HERE / "scenario_catalog.json").read_text(encoding="utf-8"))
    assert config["status"] == "DESIGN_ONLY_NOT_EXECUTABLE"
    assert config["paid_execution_enabled"] is False
    assert config["budget_cny"] is None
    scenarios = config["scenarios"]
    assert len({item["id"] for item in scenarios}) == len(scenarios) == 48
    counts = Counter(item["suite"] for item in scenarios)
    assert counts == {"task": 24, "engineering": 12, "memory_transfer": 6, "reflection_quality": 6}
    profiles = {p["id"] for p in config["profiles"]}
    assert len(profiles) == 4
    tasks = [s for s in scenarios if s["suite"] == "task"]
    assert len({(s["base_case_id"], s["profile"]) for s in tasks}) == 24
    for case_id in config["case_catalog"]:
        path = ROOT / "src/xuanyi_npc/resources/cases" / (case_id + ".json")
        assert path.is_file(), path
        resource = json.loads(path.read_text(encoding="utf-8"))
        assert resource["case_id"] == case_id
    assert sum(s["repeat_count"] for s in tasks) == 72
    memory = [s for s in scenarios if s["suite"] == "memory_transfer"]
    assert sum(len(s["conditions"]) * s["repeat_count"] for s in memory) == 54
    for item in memory:
        assert item["conditions"] == ["M0", "M1", "M2"]
    for item in scenarios:
        assert item["fixture_status"].startswith("draft")
        assert item["expected"] and item["graders"]
    broken = []
    for document in HERE.glob("*.md"):
        for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#")):
                continue
            path = target.split("#")[0]
            path = re.sub(r":\d+$", "", path)
            resolved = Path(path) if Path(path).is_absolute() else HERE / path
            if not resolved.exists():
                broken.append(str(resolved))
    assert not broken, broken
    return {
        "status": "design_inventory_valid",
        "scenario_specs": len(scenarios),
        "suite_counts": dict(counts),
        "planned_task_trials": 72,
        "planned_memory_target_trials": 54,
        "paid_calls": 0,
        "fixtures_preflighted": False,
        "grading_or_runtime_tested": False,
        "note": "Inventory, resource IDs and local links only; no execution or capability result."
    }


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))

