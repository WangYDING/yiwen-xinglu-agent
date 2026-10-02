"""Risk-based deterministic authority policy for M1."""

from xuanyi_npc.domain import AgentAction, AgentActionType, ToolName
from xuanyi_npc.domain.cooperation import AuthorityMode, NPCAuthorityView
from xuanyi_npc.domain.npc_authority import AUTONOMOUS_TOOLS, AuthorityDecision


class NPCAuthorityPolicy:
    def view(self) -> NPCAuthorityView:
        return NPCAuthorityView(
            autonomous_tools=AUTONOMOUS_TOOLS,
            proposal_only_tools=(ToolName.SUBMIT_DIAGNOSIS,),
            confirmation_required_tools=(ToolName.EXECUTE_TREATMENT,),
            forbidden_tools=(),
        )

    def evaluate(
        self,
        action: AgentAction,
        *,
        confirmed_decision_id: str | None = None,
        decision_id: str | None = None,
    ) -> AuthorityDecision:
        if action.action_type is AgentActionType.RESPOND:
            return AuthorityDecision(mode=AuthorityMode.AUTONOMOUS, reason_code="social_action")
        if action.tool_call is None:
            return AuthorityDecision(mode=AuthorityMode.FORBIDDEN, reason_code="missing_tool_call")
        tool = action.tool_call.name
        if tool in AUTONOMOUS_TOOLS:
            return AuthorityDecision(mode=AuthorityMode.AUTONOMOUS, reason_code="reversible_information_action")
        if tool is ToolName.SUBMIT_DIAGNOSIS:
            if decision_id is not None and confirmed_decision_id == decision_id:
                return AuthorityDecision(mode=AuthorityMode.AUTONOMOUS, reason_code="diagnosis_negotiation_matched")
            return AuthorityDecision(mode=AuthorityMode.PROPOSAL_ONLY, reason_code="diagnosis_requires_negotiation")
        if tool is ToolName.EXECUTE_TREATMENT:
            if decision_id is not None and confirmed_decision_id == decision_id:
                return AuthorityDecision(mode=AuthorityMode.AUTONOMOUS, reason_code="treatment_confirmation_matched")
            return AuthorityDecision(mode=AuthorityMode.CONFIRMATION_REQUIRED, reason_code="irreversible_treatment")
        return AuthorityDecision(mode=AuthorityMode.FORBIDDEN, reason_code="tool_outside_npc_authority")
