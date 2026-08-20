import pytest

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.application.action_contract import (
    INVESTIGATION_TOOL_BY_ACTION,
    PublicActionContractError,
    PublicActionContractValidator,
    project_public_investigation_actions,
)
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest

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
    for action in project_public_investigation_actions(value.case_observation):
        assert f'"tool_name": "{action.tool_name.value}"' in context
        assert f'"investigation_id": "{action.investigation_id}"' in context


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

