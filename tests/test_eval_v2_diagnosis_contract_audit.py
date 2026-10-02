import json

from xuanyi_npc.evaluation.v2_diagnosis_contract_audit import (
    FAILURE_CODE,
    audit_artifacts,
)


def _proposal(*, first_tool=None, completion_signal="signal", capability="explain"):
    return json.dumps({
        "goal_update": {"update": "keep", "public_rationale": "继续。"},
        "plan_update": {
            "update": "revise",
            "draft": {
                "steps": [
                    {
                        "intent": "analyze_evidence",
                        "capability": capability,
                        "suggested_tool": first_tool,
                        "public_target_id": None,
                        "completion_signal": completion_signal,
                    },
                    {
                        "intent": "propose_diagnosis",
                        "capability": "propose_diagnosis",
                        "suggested_tool": "submit_diagnosis",
                        "public_target_id": "diagnosis_a",
                        "completion_signal": "diagnosis_submitted",
                    },
                ],
            },
            "public_rationale": "更新计划。",
        },
        "decision": {
            "action": {
                "action_type": "use_tool",
                "tool_call": {
                    "name": "submit_diagnosis",
                    "arguments": {"diagnosis_id": "diagnosis_a"},
                },
            },
        },
    })


def test_old_v2_trace_without_tool_field_is_not_needed_for_plan_contract_audit(tmp_path):
    """The audit keys off model attempts and fallback evidence, not world event shape."""
    artifact = {
        "run_id": "t_fixture_r01",
        "events": [
            {
                "event_id": "ev_1",
                "event_type": "model_request_finished",
                "turn": 3,
                "data": {
                    "stage": "planning_initial",
                    "validation_error_code": "value_error",
                    "validation_error_path": "plan_update.draft.steps.0.completion_signal",
                    "structured_output": _proposal(completion_signal="not_a_signal"),
                },
            },
            {
                "event_id": "ev_2",
                "event_type": "model_request_finished",
                "turn": 3,
                "data": {
                    "stage": "planning_format_repair",
                    "validation_error_code": FAILURE_CODE,
                    "validation_error_path": "plan_update.draft.steps",
                    "structured_output": _proposal(),
                },
            },
            {
                "event_id": "ev_3",
                "event_type": "proposal_finalized",
                "turn": 3,
                "data": {"fallback_reason": FAILURE_CODE},
            },
            {
                "event_id": "ev_4",
                "event_type": "world_committed",
                "turn": 3,
                "data": {"submitted_diagnosis_id": "diagnosis_a"},
            },
        ],
    }
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    result = audit_artifacts([path])

    assert result["failure_instances"] == 1
    assert result["initial_classes"] == {"schema_invalid_completion_signal": 1}
    assert result["all_repair_decisions_submit_diagnosis"] is True
    assert result["all_repair_resulting_active_steps_misaligned"] is True
    record = result["records"][0]
    assert record["repair"]["diagnosis_step_positions"] == [1]
    assert record["repair"]["first_step_tool"] is None


def test_alignment_failure_is_classified_separately_from_schema_failure(tmp_path):
    proposal = _proposal()
    artifact = {
        "run_id": "t_fixture_r02",
        "events": [
            {
                "event_id": "ev_1",
                "event_type": "model_request_finished",
                "turn": 4,
                "data": {
                    "stage": "planning_initial",
                    "validation_error_code": FAILURE_CODE,
                    "validation_error_path": "plan_update.draft.steps",
                    "structured_output": proposal,
                },
            },
            {
                "event_id": "ev_2",
                "event_type": "model_request_finished",
                "turn": 4,
                "data": {
                    "stage": "planning_format_repair",
                    "validation_error_code": FAILURE_CODE,
                    "validation_error_path": "plan_update.draft.steps",
                    "structured_output": proposal,
                },
            },
            {
                "event_id": "ev_3",
                "event_type": "proposal_finalized",
                "turn": 4,
                "data": {"fallback_reason": FAILURE_CODE},
            },
        ],
    }
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")

    result = audit_artifacts([path])

    assert result["initial_classes"] == {"resulting_active_step_alignment": 1}
    assert result["records"][0]["initial"]["decision_tool"] == "submit_diagnosis"
