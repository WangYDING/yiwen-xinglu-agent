from types import SimpleNamespace

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime
from xuanyi_npc.domain import AgentActionType
from tests.test_p2_plan_decision_alignment import _diagnosis_input, _proposal


def _empty_diagnosis_step(proposal):
    empty = proposal.plan_update.draft.steps[0].model_copy(update={
        "suggested_tool": None,
        "public_target_id": None,
    })
    return proposal.model_copy(update={
        "plan_update": proposal.plan_update.model_copy(update={
            "draft": proposal.plan_update.draft.model_copy(update={
                "steps": (empty, proposal.plan_update.draft.steps[1])
            })
        })
    })


def test_failed_repair_records_sanitized_attempts_without_changing_fallback(
    case_definition, qualified_player_state
) -> None:
    value = _diagnosis_input(case_definition, qualified_player_state)
    proposal, diagnosis_id, _ = _proposal(value)
    invalid = _empty_diagnosis_step(proposal)
    adapter = ScriptedFakeLLM([invalid.model_dump_json(), invalid.model_dump_json()])
    agent = GameNPCAgent(adapter)

    result = agent.propose_turn(value)
    execution = agent.last_planning_execution()

    assert execution.output is None
    assert execution.attempts == 2
    assert execution.repair_attempted is True
    assert execution.repair_succeeded is False
    assert result.decision.action.action_type is AgentActionType.RESPOND
    assert result.plan_update.draft.steps[0].intent.value == "analyze_evidence"

    initial, repaired = execution.attempt_telemetry
    for attempt in (initial, repaired):
        assert attempt.failure_code.startswith("goal_plan_propose_diagnosis_PlanStep")
        assert attempt.field_path == "plan_update.draft.steps"
        assert attempt.plan_first_step_intent == "propose_diagnosis"
        assert attempt.plan_first_step_tool is None
        assert attempt.plan_first_step_public_target is None
        assert attempt.decision_action_type == "use_tool"
        assert attempt.decision_tool == "submit_diagnosis"
        assert attempt.decision_public_target == diagnosis_id

    runtime = object.__new__(CooperativeRuntime)
    runtime.agent = agent
    projected = runtime._repair_attempt_telemetry_fields(
        SimpleNamespace(repair_kind="format_repair")
    )
    assert projected["initial_validation_error_code"] == initial.failure_code
    assert projected["repair_validation_error_code"] == repaired.failure_code
    assert projected["repaired_plan_first_step_tool"] is None
    assert projected["repaired_decision_tool"] == "submit_diagnosis"

    request_text = "\n".join(
        message.content for request in adapter.requests for message in request.messages
    )
    assert "repair_validation_error_code" not in request_text
    assert "repaired_plan_first_step_tool" not in request_text
