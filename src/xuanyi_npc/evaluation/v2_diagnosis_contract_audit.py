"""Offline audit of diagnosis PlanStep failures in immutable V2 artifacts."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from typing import Any


FAILURE_CODE = "goal_plan_diagnosis_PlanStep_requires_submit_diagnosis"


def _initial_class(code: str | None, path: str | None) -> str:
    if code == FAILURE_CODE:
        return "resulting_active_step_alignment"
    if code == "enum":
        return "schema_invalid_enum"
    if code == "value_error" and path and path.endswith("completion_signal"):
        return "schema_invalid_completion_signal"
    return "other"


def _shape(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"parseable": False}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"parseable": False, "sha256": sha256(raw.encode()).hexdigest()}
    plan = value.get("plan_update") or {}
    draft = plan.get("draft") or {}
    steps = draft.get("steps") or []
    first = steps[0] if steps else {}
    action = ((value.get("decision") or {}).get("action") or {})
    call = action.get("tool_call") or {}
    arguments = call.get("arguments") or {}
    return {
        "parseable": True,
        "sha256": sha256(raw.encode()).hexdigest(),
        "plan_update": plan.get("update"),
        "first_step_intent": first.get("intent"),
        "first_step_capability": first.get("capability"),
        "first_step_tool": first.get("suggested_tool"),
        "first_step_target": first.get("public_target_id"),
        "diagnosis_step_positions": [
            index for index, step in enumerate(steps)
            if step.get("intent") == "propose_diagnosis"
            or step.get("capability") == "propose_diagnosis"
            or step.get("suggested_tool") == "submit_diagnosis"
        ],
        "decision_action_type": action.get("action_type"),
        "decision_tool": call.get("name"),
        "decision_target": arguments.get("diagnosis_id"),
    }


def audit_artifacts(artifact_paths: list[Path]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for path in sorted(artifact_paths):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        events = artifact["events"]
        for fallback in events:
            if (
                fallback["event_type"] != "proposal_finalized"
                or fallback["data"].get("fallback_reason") != FAILURE_CODE
            ):
                continue
            turn = fallback["turn"]
            attempts = [
                event for event in events
                if event["event_type"] == "model_request_finished"
                and event["turn"] == turn
                and event["data"].get("stage") in {
                    "planning_initial", "planning_format_repair"
                }
            ]
            by_stage = {event["data"]["stage"]: event for event in attempts}
            initial = by_stage.get("planning_initial")
            repair = by_stage.get("planning_format_repair")
            initial_data = initial["data"] if initial else {}
            repair_data = repair["data"] if repair else {}
            rows.append({
                "run_id": artifact["run_id"],
                "turn": turn,
                "fallback_event_id": fallback["event_id"],
                "initial_event_id": initial["event_id"] if initial else None,
                "repair_event_id": repair["event_id"] if repair else None,
                "initial_error_code": initial_data.get("validation_error_code"),
                "initial_error_path": initial_data.get("validation_error_path"),
                "initial_class": _initial_class(
                    initial_data.get("validation_error_code"),
                    initial_data.get("validation_error_path"),
                ),
                "initial": _shape(initial_data.get("structured_output")),
                "repair_error_code": repair_data.get("validation_error_code"),
                "repair_error_path": repair_data.get("validation_error_path"),
                "repair": _shape(repair_data.get("structured_output")),
            })

    initial_classes = Counter(row["initial_class"] for row in rows)
    initial_codes = Counter(row["initial_error_code"] for row in rows)
    repair_shapes = Counter(
        (
            row["repair"].get("plan_update"),
            row["repair"].get("first_step_intent"),
            row["repair"].get("first_step_capability"),
            row["repair"].get("first_step_tool"),
        )
        for row in rows
    )
    by_run = Counter(row["run_id"] for row in rows)
    return {
        "schema_version": "v2_diagnosis_contract_audit_v1",
        "failure_code": FAILURE_CODE,
        "failure_instances": len(rows),
        "initial_classes": dict(initial_classes),
        "initial_error_codes": {
            str(key): value for key, value in initial_codes.items()
        },
        "repair_shapes": [
            {
                "count": count,
                "plan_update": shape[0],
                "first_step_intent": shape[1],
                "first_step_capability": shape[2],
                "first_step_tool": shape[3],
            }
            for shape, count in repair_shapes.most_common()
        ],
        "by_run": dict(by_run),
        "all_repair_decisions_submit_diagnosis": all(
            row["repair"].get("decision_tool") == "submit_diagnosis" for row in rows
        ),
        "all_repair_resulting_active_steps_misaligned": all(
            row["repair"].get("plan_update") == "keep"
            or row["repair"].get("first_step_tool") != "submit_diagnosis"
            for row in rows
        ),
        "records": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    args = parser.parse_args(argv)
    paths = list(args.artifact_root.glob("runs/*/artifact.json"))
    print(json.dumps(audit_artifacts(paths), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
