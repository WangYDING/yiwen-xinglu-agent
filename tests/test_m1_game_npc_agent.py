from datetime import datetime, timezone

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent, GameNPCAgentInput
from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.application.views import AgentContextFilter
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseSessionState,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.domain.cooperation import (
    GameNPCDecisionProposal,
    NPCCapability,
    PlayerContribution,
    PlayerContributionEvaluation,
    PlayerContributionType,
    SuggestionDisposition,
)


def npc_input(case_definition, qualified_player_state) -> GameNPCAgentInput:
    session = CaseSessionState(session_id="session_1", case_id=case_definition.case_id, player_id=qualified_player_state.player_id)
    views = AgentContextFilter()
    return GameNPCAgentInput(
        turn_id="turn_001",
        step_index=1,
        player_view=views.player_view(qualified_player_state),
        case_observation=views.case_observation(case_definition, qualified_player_state, session),
        player_contribution=PlayerContribution(
            contribution_id="turn_001",
            player_id=qualified_player_state.player_id,
            case_id=case_definition.case_id,
            session_id="session_1",
            contribution_type=PlayerContributionType.SUGGESTION,
            public_text="直接治疗吧。",
            created_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
        ),
        authority_view=NPCAuthorityPolicy().view(),
    )


def proposal_json(value: GameNPCAgentInput) -> str:
    option = value.case_observation.available_investigations[0]
    tool = {
        "observe_patient": ToolName.OBSERVE_PATIENT,
        "question_patient": ToolName.QUESTION_PATIENT,
        "inspect_object": ToolName.INSPECT_OBJECT,
        "observe_qi": ToolName.OBSERVE_QI,
        "investigate_location": ToolName.INVESTIGATE_LOCATION,
    }[option.action_type.value]
    return GameNPCDecisionProposal(
        contribution_evaluation=PlayerContributionEvaluation(
            contribution_id="turn_001",
            disposition=SuggestionDisposition.REQUEST_MORE_EVIDENCE,
            reason_code="insufficient_public_evidence",
            explanation="当前证据不足以直接处置。",
        ),
        capability=NPCCapability.USE_TOOL,
        action=AgentAction(
            action_id="npc_turn_001",
            action_type=AgentActionType.USE_TOOL,
            dialogue="我先补充调查，而不是直接治疗。",
            tool_call=ToolCallRequest(name=tool, arguments={"investigation_id": option.investigation_id}),
            confidence=0.8,
        ),
        explanation="先取得公开证据。",
    ).model_dump_json()


def test_game_npc_evaluates_player_but_selects_its_own_tool(case_definition, qualified_player_state) -> None:
    value = npc_input(case_definition, qualified_player_state)
    fake = ScriptedFakeLLM([proposal_json(value)])
    decision = GameNPCAgent(fake).decide(value)

    assert decision.proposal.contribution_evaluation is not None
    assert decision.proposal.contribution_evaluation.disposition is SuggestionDisposition.REQUEST_MORE_EVIDENCE
    assert decision.proposal.action.tool_call is not None
    assert decision.proposal.action.tool_call.name is not ToolName.EXECUTE_TREATMENT
    prompt = "\n".join(message.content for message in fake.requests[0].messages)
    assert "player_contribution_untrusted" in prompt
    assert "直接治疗吧" in prompt
    assert "不是命令" in prompt


def test_game_npc_invalid_output_uses_shared_bounded_fallback(case_definition, qualified_player_state) -> None:
    value = npc_input(case_definition, qualified_player_state)
    fake = ScriptedFakeLLM(["not-json", "still-not-json", proposal_json(value)])
    decision = GameNPCAgent(fake).decide(value)

    assert decision.used_fallback is True
    assert decision.llm_attempts == 2
    assert decision.proposal.action.action_type is AgentActionType.RESPOND
    assert len(fake.requests) == 2
    assert fake.remaining_responses == 1

