from datetime import datetime, timezone
from pathlib import Path

from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime, CooperativeTurnInput
from xuanyi_npc.application.clinic import message_requests_case_action
from xuanyi_npc.application.multicase import CreatePlayerInput, StartEpisodeInput
from xuanyi_npc.domain import AgentAction, AgentActionType, CaseActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import (
    AgentRuntimeKind,
    CooperativeTurnStatus,
    GameNPCDecision,
    GameNPCDecisionProposal,
    NPCCapability,
    PlayerContribution,
    PlayerContributionEvaluation,
    PlayerContributionType,
    SuggestionDisposition,
)
from tests.cooperative_runtime_helpers import build_service


class StubAgent:
    config = object()
    runtime_kind = AgentRuntimeKind.TEST_DOUBLE

    def __init__(self, action: AgentAction) -> None:
        self.action = action
        self.inputs = []

    def decide(self, agent_input):
        self.inputs.append(agent_input)
        return GameNPCDecision(
            decision_id=f"decision_{agent_input.turn_id}",
            turn_id=agent_input.turn_id,
            proposal=GameNPCDecisionProposal(
                contribution_evaluation=PlayerContributionEvaluation(
                    contribution_id=agent_input.player_contribution.contribution_id,
                    disposition=SuggestionDisposition.PARTIAL_ACCEPT,
                    reason_code="alternative_is_more_informative",
                    explanation="接受调查方向，但由我选择具体行动。",
                ),
                capability=NPCCapability.USE_TOOL,
                action=self.action,
                explanation="执行一个可逆调查。",
            ),
            llm_attempts=1,
            used_fallback=False,
        )

    def repair_action_contract(self, agent_input, prior, feedback):
        del agent_input, feedback
        return self.action_contract_fallback(prior)

    def action_contract_fallback(self, prior):
        proposal = prior.proposal.model_copy(update={
            "capability": NPCCapability.EXPLAIN,
            "action": AgentAction(
                action_id=prior.proposal.action.action_id,
                action_type=AgentActionType.RESPOND,
                dialogue="当前证据不足，暂不执行。",
                confidence=0.0,
            ),
        })
        return prior.model_copy(update={"proposal": proposal, "llm_attempts": 2, "used_fallback": True})


def opened_case(root: Path):
    service = build_service(root)
    created = service.create_player(CreatePlayerInput(display_name="协作测试玩家"))
    opened = service.start_episode(StartEpisodeInput(player_id=created.player_id, case_id="old_paper_umbrella"))
    assert opened.ok and opened.observation is not None and opened.session_id is not None
    return service, created.player_id, opened


def contribution(player_id, session_id):
    return PlayerContribution(
        contribution_id="turn_001",
        player_id=player_id,
        case_id="old_paper_umbrella",
        session_id=session_id,
        contribution_type=PlayerContributionType.SUGGESTION,
        public_text="我建议先查患者，但具体怎么查由你判断。",
        created_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )


def test_natural_chat_requires_an_explicit_action_request() -> None:
    assert message_requests_case_action("你好") is False
    assert message_requests_case_action("下一步要做什么？") is False
    assert message_requests_case_action("为什么不检查大门？") is False
    assert message_requests_case_action("先不要检查大门") is False
    assert message_requests_case_action("要不检查一下大门") is True
    assert message_requests_case_action("请询问店主最近用的燃料") is True
    assert message_requests_case_action("我认为可以形成辨证了") is True


def test_runtime_executes_one_npc_selected_low_risk_tool(tmp_path: Path) -> None:
    service, player_id, opened = opened_case(tmp_path)
    option = opened.observation.available_investigations[0]
    tool = {
        CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
        CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
        CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
        CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
        CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
    }[option.action_type]
    action = AgentAction(
        action_id="npc_turn_001",
        action_type=AgentActionType.USE_TOOL,
        dialogue="我选择先执行这项公开调查。",
        tool_call=ToolCallRequest(name=tool, arguments={"investigation_id": option.investigation_id}),
        confidence=0.8,
    )
    agent = StubAgent(action)

    result = CooperativeRuntime(service=service, agent=agent).handle(
        CooperativeTurnInput(contribution=contribution(player_id, opened.session_id))
    )

    assert result.status is CooperativeTurnStatus.ACTION_EXECUTED
    assert result.event_sequences == (1,)
    assert result.runtime_kind is AgentRuntimeKind.TEST_DOUBLE
    assert result.selected_tool is tool
    assert result.selected_public_target == option.public_description
    assert result.public_rationale == "执行一个可逆调查。"
    assert service.state_store.load_case_session(opened.session_id).revision == 1
    assert agent.inputs[0].player_contribution.public_text.startswith("我建议")


def test_conversation_only_turn_cannot_execute_or_advance_plan(tmp_path: Path) -> None:
    service, player_id, opened = opened_case(tmp_path)
    option = opened.observation.available_investigations[0]
    tool = {
        CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
        CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
        CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
        CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
        CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
    }[option.action_type]
    agent = StubAgent(AgentAction(
        action_id="npc_turn_001",
        action_type=AgentActionType.USE_TOOL,
        dialogue="模型试图继续执行调查。",
        tool_call=ToolCallRequest(
            name=tool,
            arguments={"investigation_id": option.investigation_id},
        ),
        confidence=0.8,
    ))
    greeting = contribution(player_id, opened.session_id).model_copy(update={
        "contribution_type": PlayerContributionType.GENERAL_MESSAGE,
        "public_text": "你好",
    })

    result = CooperativeRuntime(service=service, agent=agent).handle(
        CooperativeTurnInput(contribution=greeting, allow_world_action=False)
    )

    assert result.status is CooperativeTurnStatus.RESPONDED
    assert result.decision.proposal.action.action_type is AgentActionType.RESPOND
    assert "不会自行推进调查" in result.decision.proposal.action.dialogue
    assert result.goal_changed is False and result.plan_changed is False
    assert service.state_store.load_case_session(opened.session_id).revision == 0
    assert agent.inputs == []


def test_runtime_does_not_execute_diagnosis_without_negotiation(tmp_path: Path) -> None:
    service, player_id, opened = opened_case(tmp_path)
    diagnosis_id = opened.observation.diagnosis_candidates[0].diagnosis_id
    action = AgentAction(
        action_id="npc_turn_001",
        action_type=AgentActionType.USE_TOOL,
        dialogue="我提出这个辨证供我们讨论。",
        tool_call=ToolCallRequest(name=ToolName.SUBMIT_DIAGNOSIS, arguments={"diagnosis_id": diagnosis_id, "evidence_clue_ids": []}),
        confidence=0.6,
    )
    agent = StubAgent(action)
    result = CooperativeRuntime(service=service, agent=agent).handle(
        CooperativeTurnInput(contribution=contribution(player_id, opened.session_id))
    )

    # Diagnosis readiness is still an earlier deterministic public contract. If it is
    # unavailable, the runtime must not reach CaseEngine or create a proposal that can execute.
    assert result.status in {CooperativeTurnStatus.RESPONDED, CooperativeTurnStatus.PROPOSAL_PENDING}
    assert service.state_store.load_case_session(opened.session_id).revision == 0
