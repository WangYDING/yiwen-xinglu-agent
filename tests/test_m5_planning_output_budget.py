from xuanyi_npc.agents import DeepSeekAdapterConfig, DeepSeekChatAdapter, ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import (
    GAME_NPC_PLANNING_MAX_OUTPUT_TOKENS,
    GameNPCAgent,
)
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    GoalCondition,
    GoalConditionType,
)

from .test_m1_game_npc_agent import npc_input


def planning_input(case_definition, qualified_player_state):
    value = npc_input(case_definition, qualified_player_state)
    goal = AgentGoalState(
        goal_id="goal_budget",
        goal_type=AgentGoalType.RESOLVE_CASE,
        public_description="依据公开证据处理当前病例。",
        status=AgentGoalStatus.ACTIVE,
        priority=100,
        completion_condition=GoalCondition(condition_type=GoalConditionType.CASE_COMPLETED),
        created_turn_id="turn_001",
        updated_turn_id="turn_001",
    )
    return value.model_copy(update={"current_goal": goal})


def test_only_planning_request_receives_larger_bounded_budget(case_definition, qualified_player_state) -> None:
    agent = GameNPCAgent(ScriptedFakeLLM([]))
    value = planning_input(case_definition, qualified_player_state)

    simple = agent._request(value)
    planning = agent._planning_request(value)

    assert not hasattr(simple, "max_output_tokens")
    assert planning.max_output_tokens == GAME_NPC_PLANNING_MAX_OUTPUT_TOKENS == 2048


def test_deepseek_payload_uses_request_override_without_changing_default(case_definition, qualified_player_state) -> None:
    agent = GameNPCAgent(ScriptedFakeLLM([]))
    value = planning_input(case_definition, qualified_player_state)
    adapter = DeepSeekChatAdapter(DeepSeekAdapterConfig(
        api_key="unit-test-placeholder",
        base_url="https://api.deepseek.test",
    ))
    try:
        assert adapter._chat_payload(agent._request(value))["max_tokens"] == 512
        assert adapter._chat_payload(agent._planning_request(value))["max_tokens"] == 2048
    finally:
        adapter.close()
