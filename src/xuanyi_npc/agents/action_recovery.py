"""One shared, bounded repair coordinator for contextual action contracts."""

from __future__ import annotations

from pydantic import ConfigDict

from xuanyi_npc.application.action_contract import (
    PublicActionContractError,
    PublicActionContractValidator,
    build_safe_action_feedback,
)
from xuanyi_npc.application.views import CaseObservation
from xuanyi_npc.domain.base import DomainModel, Identifier

from .doctor import AgentDecision, DoctorAgentInput, DoctorAgentInterface


class ActionContractResolution(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: AgentDecision
    error_code: Identifier | None = None


class BoundedActionContractResolver:
    """Validate, repair once, then fall back without a third model call."""

    def __init__(self, validator: PublicActionContractValidator | None = None) -> None:
        self.validator = validator or PublicActionContractValidator()

    def resolve(
        self,
        doctor_agent: DoctorAgentInterface,
        agent_input: DoctorAgentInput,
        decision: AgentDecision,
        observation: CaseObservation,
    ) -> ActionContractResolution:
        try:
            self.validator.validate(decision.action, observation)
            return ActionContractResolution(decision=decision)
        except PublicActionContractError as first_error:
            first_error_code = first_error.code
            feedback = build_safe_action_feedback(first_error_code, observation)
        if decision.llm_attempts != 1:
            return ActionContractResolution(
                decision=doctor_agent.action_contract_fallback(decision),
                error_code=first_error_code,
            )
        repaired = doctor_agent.repair_action_contract(
            agent_input,
            decision,
            feedback,
        )
        if repaired.used_fallback:
            return ActionContractResolution(
                decision=repaired,
                error_code=first_error_code,
            )
        try:
            self.validator.validate(repaired.action, observation)
        except PublicActionContractError as second_error:
            return ActionContractResolution(
                decision=doctor_agent.action_contract_fallback(repaired),
                error_code=second_error.code,
            )
        return ActionContractResolution(decision=repaired)
