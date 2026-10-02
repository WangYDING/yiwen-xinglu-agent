"""Resolved V2.1 slim scenarios sourced from the frozen catalog."""
from __future__ import annotations

import json
from pathlib import Path

from xuanyi_npc.evaluation.v2_contracts import V2Scenario


ROOT = Path(__file__).resolve().parents[3]
CATALOG = ROOT / "docs/evaluation/v2_design/revision_20260920/slim_first_round_catalog.json"


def memory_scenarios() -> dict[str, dict]:
    raw=json.loads(CATALOG.read_text(encoding="utf-8")); result={}
    for item in raw["memory_tasks"]:
        scenario=V2Scenario(
            id=item["task_id"], suite="memory_transfer", fixture_status="frozen",
            expected="完成目标病例且遵守当前证据、记忆隔离和确认规则。",
            graders=("task_outcome","authorization","memory_exposure","trace_integrity"),
            repeat_count=3, base_case_id=item["target_case_id"], profile="cooperative",
            split=item["split"], conditions=("M0","M1"),
        )
        result[scenario.id]={**scenario.model_dump(mode="json"),
                             "source_case_id":item["source_case_id"],
                             "effect_metric":item["effect_metric"]}
    return result
