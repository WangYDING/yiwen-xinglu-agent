from types import SimpleNamespace

import pytest

from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime, CooperativeTurnInput
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperative_planning import AgentPlanStatus, PlanStepIntent
from xuanyi_npc.evaluation.agent_task_benchmark import _turn_summary
from tests.test_m2_cooperative_runtime_planning import (
    PlanningAgent,
    _keep_plan_action,
    _two_tool_plan_proposal,
    contribution,
    opened_case,
)


def _alignment_fixture(*, tool, arguments, step_tool, step_target):
    action = AgentAction(
        action_id="action_p2a",
        action_type=AgentActionType.USE_TOOL,
        dialogue="公开行动。",
        tool_call=ToolCallRequest(name=tool, arguments=arguments),
        confidence=0.8,
    )
    decision = SimpleNamespace(proposal=SimpleNamespace(action=action))
    step = SimpleNamespace(
        step_id="step_public",
        intent=PlanStepIntent.PROPOSE_DIAGNOSIS,
        suggested_tool=step_tool,
        public_target_id=step_target,
    )
    state = SimpleNamespace(
        current_plan=SimpleNamespace(
            status=AgentPlanStatus.ACTIVE,
            current_step_index=0,
            steps=(step,),
        )
    )
    observation = SimpleNamespace(
        available_investigations=(SimpleNamespace(investigation_id="investigation_public"),),
        diagnosis_candidates=(SimpleNamespace(diagnosis_id="diagnosis_public"),),
        available_treatments=(SimpleNamespace(treatment_id="treatment_public"),),
    )
    return decision, state, observation


@pytest.mark.parametrize(
    ("tool", "arguments", "step_tool", "step_target", "reason"),
    (
        (ToolName.SUBMIT_DIAGNOSIS, {"diagnosis_id": "diagnosis_public"}, ToolName.SUBMIT_DIAGNOSIS, "diagnosis_public", "match"),
        (ToolName.QUESTION_PATIENT, {"investigation_id": "investigation_public"}, ToolName.SUBMIT_DIAGNOSIS, "diagnosis_public", "tool_mismatch"),
        (ToolName.SUBMIT_DIAGNOSIS, {"diagnosis_id": "diagnosis_public"}, ToolName.SUBMIT_DIAGNOSIS, "diagnosis_other", "target_mismatch"),
    ),
)
def test_alignment_telemetry_distinguishes_match_tool_and_target_mismatch(
    tool, arguments, step_tool, step_target, reason
) -> None:
    decision, state, observation = _alignment_fixture(
        tool=tool, arguments=arguments, step_tool=step_tool, step_target=step_target
    )

    telemetry = CooperativeRuntime._alignment_telemetry(decision, state, observation)

    assert telemetry["proposed_public_target_id"] == next(iter(arguments.values()))
    assert telemetry["alignment_reason_code"] == reason


@pytest.mark.parametrize(
    ("arguments", "matcher_result", "reason"),
    (
        ({"diagnosis_id": "diagnosis_public", "evidence_clue_ids": ["clue_public"]}, True, "match"),
        ({"evidence_clue_ids": ["clue_public"], "diagnosis_id": "diagnosis_public"}, False, "target_mismatch"),
    ),
)
def test_diagnosis_target_telemetry_is_order_independent_but_matcher_is_unchanged(
    arguments, matcher_result, reason
) -> None:
    decision, state, observation = _alignment_fixture(
        tool=ToolName.SUBMIT_DIAGNOSIS,
        arguments=arguments,
        step_tool=ToolName.SUBMIT_DIAGNOSIS,
        step_target="diagnosis_public",
    )

    telemetry = CooperativeRuntime._alignment_telemetry(decision, state, observation)

    assert telemetry["proposed_public_target_id"] == "diagnosis_public"
    assert telemetry["proposed_argument_keys"] == tuple(arguments)
    assert telemetry["alignment_reason_code"] == reason
    assert CooperativeRuntime._action_matches_plan(decision, state) is matcher_result


def test_respond_has_no_fake_tool_or_target() -> None:
    decision, state, observation = _alignment_fixture(
        tool=ToolName.SUBMIT_DIAGNOSIS,
        arguments={"diagnosis_id": "diagnosis_public"},
        step_tool=ToolName.SUBMIT_DIAGNOSIS,
        step_target="diagnosis_public",
    )
    respond = AgentAction(
        action_id="action_respond",
        action_type=AgentActionType.RESPOND,
        dialogue="仅交流。",
        confidence=0.8,
    )
    decision = SimpleNamespace(proposal=SimpleNamespace(action=respond))

    telemetry = CooperativeRuntime._alignment_telemetry(decision, state, observation)

    assert telemetry["proposed_tool"] is None
    assert telemetry["proposed_public_target_id"] is None
    assert telemetry["proposed_argument_keys"] == ()
    assert telemetry["alignment_reason_code"] == "not_applicable"


def test_runtime_telemetry_is_serialized_without_state_authority_or_input_effect(tmp_path) -> None:
    service, player_id, opened = opened_case(tmp_path)
    agent = PlanningAgent([_two_tool_plan_proposal, _keep_plan_action(match=False)])
    runtime = CooperativeRuntime(service=service, agent=agent)
    runtime.handle(CooperativeTurnInput(contribution=contribution(player_id, opened.session_id, "turn_seed")))
    session_before = service.state_store.load_case_session(opened.session_id)
    state_before = service.state_store.load_cooperative_agent_state(opened.session_id)
    observation = service.resume_episode(
        SimpleNamespace(player_id=player_id, case_id="old_paper_umbrella", session_id=opened.session_id)
    ).observation

    rejected = runtime.handle(
        CooperativeTurnInput(contribution=contribution(player_id, opened.session_id, "turn_bad"))
    )
    session_after = service.state_store.load_case_session(opened.session_id)
    state_after = service.state_store.load_cooperative_agent_state(opened.session_id)
    summary = _turn_summary(2, "investigate", observation, rejected)

    assert rejected.error_code == "action_outside_active_plan"
    assert rejected.authority_mode.value == "forbidden"
    assert session_after == session_before
    assert state_after.current_goal == state_before.current_goal
    assert state_after.current_plan == state_before.current_plan
    assert summary.proposed_tool == rejected.proposed_tool.value
    assert summary.proposed_public_target_id == rejected.proposed_public_target_id
    assert summary.active_plan_step_tool == rejected.active_plan_step_tool.value
    assert summary.alignment_reason_code in {"tool_mismatch", "target_mismatch"}
    assert not hasattr(agent.inputs[-1], "alignment_reason_code")
    assert "proposed_public_target_id" not in agent.inputs[-1].model_dump()
