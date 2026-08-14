"""Single-turn M1 cooperative runtime; no planning, reflection, or new memory."""

from typing import Protocol

from pydantic import ConfigDict

from xuanyi_npc.agents.game_npc import GameNPCAgentInput, GameNPCAgentInterface
from xuanyi_npc.application.action_contract import (
    PublicActionContractError,
    PublicActionContractValidator,
    build_safe_action_feedback,
)
from xuanyi_npc.application.multicase import ResumeEpisodeInput, SubmitActionInput
from xuanyi_npc.domain import AgentActionType
from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.domain.cooperation import (
    AuthorityMode,
    AgentRuntimeKind,
    CooperativeTurnResult,
    CooperativeTurnStatus,
    PendingActionConfirmation,
    PlayerContribution,
    PlayerContributionType,
)

from .npc_authority import NPCAuthorityPolicy


class CooperativeRuntimeError(ValueError):
    pass


class CooperativeService(Protocol):
    state_store: object
    context_filter: object

    def resume_episode(self, request): ...
    def submit_action_with_receipt(self, request): ...


class CooperativeTurnInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contribution: PlayerContribution
    pending_action: PendingActionConfirmation | None = None


class CooperativeRuntime:
    def __init__(
        self,
        *,
        service: CooperativeService,
        agent: GameNPCAgentInterface,
        authority_policy: NPCAuthorityPolicy | None = None,
        action_validator: PublicActionContractValidator | None = None,
    ) -> None:
        self.service = service
        self.agent = agent
        self.authority_policy = authority_policy or NPCAuthorityPolicy()
        self.action_validator = action_validator or PublicActionContractValidator()

    def handle(self, request: CooperativeTurnInput) -> CooperativeTurnResult:
        contribution = request.contribution
        public = self.service.resume_episode(ResumeEpisodeInput(
            player_id=contribution.player_id,
            case_id=contribution.case_id,
            session_id=contribution.session_id,
        ))
        if not public.ok or public.observation is None:
            raise CooperativeRuntimeError("safe case observation is unavailable")
        session = self.service.state_store.load_case_session(contribution.session_id)
        player = self.service.state_store.load_player(contribution.player_id)
        pending = self._validated_pending(request.pending_action, contribution, session.revision)
        agent_input = GameNPCAgentInput(
            turn_id=contribution.contribution_id,
            step_index=len(session.action_history) + 1,
            player_view=self.service.context_filter.player_view(player),
            case_observation=public.observation,
            player_contribution=contribution,
            authority_view=self.authority_policy.view(),
        )
        decision = self.agent.decide(agent_input)
        decision = self._resolve_contract(agent_input, decision, public.observation)
        action = decision.proposal.action
        runtime_kind = getattr(self.agent, "runtime_kind", AgentRuntimeKind.UNKNOWN)
        selected_tool = action.tool_call.name if action.tool_call is not None else None
        selected_public_target = self._public_target(action, public.observation)
        common = {
            "turn_id": agent_input.turn_id,
            "decision": decision,
            "runtime_kind": runtime_kind,
            "selected_tool": selected_tool,
            "selected_public_target": selected_public_target,
            "public_rationale": decision.proposal.explanation,
        }
        if action.action_type is AgentActionType.RESPOND:
            return CooperativeTurnResult(**common, status=CooperativeTurnStatus.RESPONDED, authority_mode=AuthorityMode.AUTONOMOUS)

        confirmed_id = None
        authority_decision_id = None
        if pending is not None and pending.action.tool_call == action.tool_call:
            confirmed_id = pending.decision_id
            authority_decision_id = pending.decision_id
        authority = self.authority_policy.evaluate(action, confirmed_decision_id=confirmed_id, decision_id=authority_decision_id)
        if authority.mode in {AuthorityMode.PROPOSAL_ONLY, AuthorityMode.CONFIRMATION_REQUIRED}:
            pending_action = PendingActionConfirmation(
                confirmation_id=f"confirm_{decision.decision_id}",
                decision_id=decision.decision_id,
                player_id=contribution.player_id,
                case_id=contribution.case_id,
                session_id=contribution.session_id,
                action=action,
                authority_mode=authority.mode,
                public_rationale=decision.proposal.explanation,
                case_revision=session.revision,
            )
            status = CooperativeTurnStatus.PROPOSAL_PENDING if authority.mode is AuthorityMode.PROPOSAL_ONLY else CooperativeTurnStatus.CONFIRMATION_REQUIRED
            return CooperativeTurnResult(**common, status=status, authority_mode=authority.mode, pending_action=pending_action)
        if authority.mode is AuthorityMode.FORBIDDEN:
            return CooperativeTurnResult(**common, status=CooperativeTurnStatus.ACTION_REJECTED, authority_mode=authority.mode, error_code=authority.reason_code)

        receipt = self.service.submit_action_with_receipt(SubmitActionInput(
            player_id=contribution.player_id,
            case_id=contribution.case_id,
            session_id=contribution.session_id,
            action=action,
        ))
        result = receipt.result
        if not result.ok:
            return CooperativeTurnResult(**common, status=CooperativeTurnStatus.ACTION_REJECTED, authority_mode=authority.mode, environment_message=result.message, error_code=result.error_code)
        return CooperativeTurnResult(**common, status=CooperativeTurnStatus.ACTION_EXECUTED, authority_mode=authority.mode, environment_message=result.message, event_sequences=result.event_sequences)

    @staticmethod
    def _public_target(action, observation):
        if action.tool_call is None:
            return None
        arguments = action.tool_call.arguments
        if "investigation_id" in arguments:
            target = next((item for item in observation.available_investigations if item.investigation_id == arguments["investigation_id"]), None)
            return target.public_description if target is not None else None
        if "diagnosis_id" in arguments:
            target = next((item for item in observation.diagnosis_candidates if item.diagnosis_id == arguments["diagnosis_id"]), None)
            return target.public_description if target is not None else None
        if "treatment_id" in arguments:
            target = next((item for item in observation.available_treatments if item.treatment_id == arguments["treatment_id"]), None)
            return target.public_description if target is not None else None
        return None

    def _resolve_contract(self, agent_input, decision, observation):
        try:
            self.action_validator.validate(decision.proposal.action, observation)
            return decision
        except PublicActionContractError as first:
            repaired = self.agent.repair_action_contract(agent_input, decision, build_safe_action_feedback(first.code, observation))
        if repaired.used_fallback:
            return repaired
        try:
            self.action_validator.validate(repaired.proposal.action, observation)
            return repaired
        except PublicActionContractError:
            return self.agent.action_contract_fallback(repaired)

    @staticmethod
    def _validated_pending(pending, contribution, revision):
        if pending is None:
            return None
        if contribution.contribution_type is not PlayerContributionType.APPROVAL:
            return None
        if (pending.player_id, pending.case_id, pending.session_id) != (
            contribution.player_id, contribution.case_id, contribution.session_id
        ):
            return None
        if contribution.responds_to_decision_id != pending.decision_id:
            return None
        if pending.case_revision != revision:
            return None
        return pending
