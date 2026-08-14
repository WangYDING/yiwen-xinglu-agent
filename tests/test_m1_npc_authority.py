from xuanyi_npc.application.npc_authority import NPCAuthorityPolicy
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import AuthorityMode


def action(tool: ToolName) -> AgentAction:
    arguments = {
        ToolName.QUESTION_PATIENT: {"investigation_id": "ask_cough"},
        ToolName.SUBMIT_DIAGNOSIS: {"diagnosis_id": "diagnosis_1"},
        ToolName.EXECUTE_TREATMENT: {"treatment_id": "treatment_1"},
    }[tool]
    return AgentAction(
        action_id="npc_turn_1",
        action_type=AgentActionType.USE_TOOL,
        dialogue="执行受限行动。",
        tool_call=ToolCallRequest(name=tool, arguments=arguments),
        confidence=0.8,
    )


def test_information_gathering_is_autonomous() -> None:
    result = NPCAuthorityPolicy().evaluate(action(ToolName.QUESTION_PATIENT))
    assert result.mode is AuthorityMode.AUTONOMOUS


def test_diagnosis_is_proposal_until_negotiation_matches() -> None:
    policy = NPCAuthorityPolicy()
    assert policy.evaluate(action(ToolName.SUBMIT_DIAGNOSIS)).mode is AuthorityMode.PROPOSAL_ONLY
    assert policy.evaluate(
        action(ToolName.SUBMIT_DIAGNOSIS),
        confirmed_decision_id="decision_1",
        decision_id="decision_1",
    ).mode is AuthorityMode.AUTONOMOUS


def test_treatment_requires_matching_confirmation() -> None:
    policy = NPCAuthorityPolicy()
    assert policy.evaluate(action(ToolName.EXECUTE_TREATMENT)).mode is AuthorityMode.CONFIRMATION_REQUIRED
    assert policy.evaluate(
        action(ToolName.EXECUTE_TREATMENT),
        confirmed_decision_id="old_decision",
        decision_id="new_decision",
    ).mode is AuthorityMode.CONFIRMATION_REQUIRED
    assert policy.evaluate(
        action(ToolName.EXECUTE_TREATMENT),
        confirmed_decision_id="decision_1",
        decision_id="decision_1",
    ).mode is AuthorityMode.AUTONOMOUS

