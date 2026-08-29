import pytest

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.action_contract import (
    INVESTIGATION_TOOL_BY_ACTION,
    PublicActionContractError,
    PublicActionContractValidator,
    project_public_diagnosis_actions,
    project_public_investigation_actions,
)
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperative_planning import AgentGoalType

from .test_m5_planning_output_budget import planning_input


def test_projection_contains_exact_arguments_for_every_public_action(case_definition, qualified_player_state) -> None:
    value = planning_input(case_definition, qualified_player_state)
    before = value.case_observation.model_dump_json()
    actions = project_public_investigation_actions(value.case_observation)

    assert len(actions) == len(value.case_observation.available_investigations)
    assert len(actions) >= 2
    for option, action in zip(value.case_observation.available_investigations, actions):
        assert action.tool_name is INVESTIGATION_TOOL_BY_ACTION[option.action_type]
        assert action.investigation_id == option.investigation_id
        assert action.arguments == {"investigation_id": option.investigation_id}
    assert value.case_observation.model_dump_json() == before


def test_projection_excludes_every_non_public_investigation(case_definition, qualified_player_state) -> None:
    value = planning_input(case_definition, qualified_player_state)
    visible = {item.investigation_id for item in project_public_investigation_actions(value.case_observation)}
    all_defined = {item.investigation_id for item in case_definition.investigations}

    assert visible == {item.investigation_id for item in value.case_observation.available_investigations}
    assert all_defined - visible
    assert visible.isdisjoint(all_defined - visible)


def test_planning_request_exposes_authoritative_exact_action_space(case_definition, qualified_player_state) -> None:
    value = planning_input(case_definition, qualified_player_state)
    request = GameNPCAgent(ScriptedFakeLLM([]))._planning_request(value)
    context = request.messages[-1].content

    assert "AUTHORITATIVE_PUBLIC_ACTION_SPACE_available_actions" in context
    assert "ToolCall arguments 必须逐字复制" in context
    assert "PLAN_INVESTIGATION_CONTRACT" in context
    assert "suggested_tool" in context
    assert "public_target_id" in context
    assert "不得交叉组合 tool/target" in context
    for action in project_public_investigation_actions(value.case_observation):
        assert f'"tool_name": "{action.tool_name.value}"' in context
        assert f'"investigation_id": "{action.investigation_id}"' in context


def test_decision_and_plan_guidance_share_the_same_projected_pairs(case_definition, qualified_player_state) -> None:
    value = planning_input(case_definition, qualified_player_state)
    context = GameNPCAgent(ScriptedFakeLLM([]))._planning_request(value).messages[-1].content
    actions = project_public_investigation_actions(value.case_observation)

    for action in actions:
        tool_position = context.index(f'"tool_name": "{action.tool_name.value}"')
        target_position = context.index(f'"investigation_id": "{action.investigation_id}"', tool_position)
        assert target_position > tool_position


def test_projection_grants_no_authority_and_validator_remains_strict(case_definition, qualified_player_state) -> None:
    value = planning_input(case_definition, qualified_player_state)
    authority_before = NPCAuthorityPolicy().view()
    option = value.case_observation.available_investigations[0]
    tool = INVESTIGATION_TOOL_BY_ACTION[option.action_type]
    invalid = AgentAction(
        action_id="action_invalid_arguments",
        action_type=AgentActionType.USE_TOOL,
        dialogue="错误参数仍应被拒绝。",
        tool_call=ToolCallRequest(name=tool, arguments={}),
        confidence=1.0,
    )

    project_public_investigation_actions(value.case_observation)
    with pytest.raises(PublicActionContractError, match="准确工具名") as captured:
        PublicActionContractValidator().validate(invalid, value.case_observation)

    assert captured.value.code == "invalid_tool_arguments"
    assert NPCAuthorityPolicy().view() == authority_before


def test_diagnosis_surface_projects_every_public_candidate_with_validator_exact_arguments(
    case_definition, qualified_player_state,
) -> None:
    value = planning_input(case_definition, qualified_player_state)
    observation = value.case_observation.model_copy(update={"can_submit_diagnosis": True})
    before = observation.model_dump_json()

    actions = project_public_diagnosis_actions(observation)

    assert {item.diagnosis_id for item in actions} == {
        item.diagnosis_id for item in observation.diagnosis_candidates
    }
    assert len(actions) == len(observation.diagnosis_candidates)
    expected_evidence = [item.clue_id for item in observation.discovered_clues]
    for projected in actions:
        assert projected.tool_name is ToolName.SUBMIT_DIAGNOSIS
        assert projected.arguments == {
            "diagnosis_id": projected.diagnosis_id,
            "evidence_clue_ids": expected_evidence,
        }
        PublicActionContractValidator().validate(
            AgentAction(
                action_id=f"action_{projected.diagnosis_id}",
                action_type=AgentActionType.USE_TOOL,
                dialogue="提出一个公开候选诊断。",
                tool_call=ToolCallRequest(
                    name=projected.tool_name,
                    arguments=projected.arguments,
                ),
                confidence=0.5,
            ),
            observation,
        )
    assert observation.model_dump_json() == before


def test_diagnosis_surface_is_empty_until_public_readiness(case_definition, qualified_player_state) -> None:
    value = planning_input(case_definition, qualified_player_state)
    observation = value.case_observation.model_copy(update={"can_submit_diagnosis": False})

    assert project_public_diagnosis_actions(observation) == ()


def test_form_diagnosis_request_exposes_calls_and_phase_action_contract(
    case_definition, qualified_player_state,
) -> None:
    value = planning_input(case_definition, qualified_player_state)
    observation = value.case_observation.model_copy(update={"can_submit_diagnosis": True})
    goal = value.current_goal.model_copy(update={"goal_type": AgentGoalType.FORM_DIAGNOSIS})
    diagnosis_value = value.model_copy(update={
        "case_observation": observation,
        "current_goal": goal,
    })

    context = GameNPCAgent(ScriptedFakeLLM([]))._planning_request(diagnosis_value).messages[-1].content

    assert "DIAGNOSIS_ACTION_CONTRACT" in context
    assert "active PlanStep 要求 submit_diagnosis" in context
    assert "不是 KEEP 同一诊断步骤后仅 RESPOND" in context
    assert "诊断候选与证据取舍仍由你自主判断" in context
    for action in project_public_diagnosis_actions(observation):
        assert f'"tool_name": "submit_diagnosis"' in context
        assert f'"diagnosis_id": "{action.diagnosis_id}"' in context
    assert "valid_diagnosis_ids" not in context
    assert "root_cause" not in context


def test_respond_remains_valid_for_ordinary_communication(case_definition, qualified_player_state) -> None:
    observation = planning_input(case_definition, qualified_player_state).case_observation
    response = AgentAction(
        action_id="action_public_response",
        action_type=AgentActionType.RESPOND,
        dialogue="先解释当前公开证据，不执行工具。",
        confidence=0.5,
    )

    PublicActionContractValidator().validate(response, observation)
