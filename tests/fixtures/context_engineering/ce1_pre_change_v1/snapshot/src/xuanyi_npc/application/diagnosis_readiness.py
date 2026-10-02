"""Replaceable application policy for deciding when diagnosis is ready."""

from typing import Protocol, runtime_checkable

from pydantic import ConfigDict, StrictBool

from xuanyi_npc.domain import AgentAction, CaseSessionStatus
from xuanyi_npc.domain.base import DomainModel, Identifier

from .views import CaseObservation, PlayerView


class DiagnosisReadinessDecision(DomainModel):
    """Policy result kept outside the case engine and event model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: Identifier
    can_submit_diagnosis: StrictBool


@runtime_checkable
class DiagnosisReadinessPolicy(Protocol):
    """Use only safe views and an optional proposal to decide readiness."""

    policy_id: str

    def evaluate(
        self,
        *,
        player_view: PlayerView,
        case_observation: CaseObservation,
        proposed_action: AgentAction | None = None,
    ) -> DiagnosisReadinessDecision:
        """Return whether the current runtime permits a diagnosis proposal."""


class FixedDiagnosisReadinessPolicy:
    """Temporary M2 baseline: consume each currently available investigation."""

    policy_id = "fixed_v0"

    def evaluate(
        self,
        *,
        player_view: PlayerView,
        case_observation: CaseObservation,
        proposed_action: AgentAction | None = None,
    ) -> DiagnosisReadinessDecision:
        del player_view, proposed_action
        return DiagnosisReadinessDecision(
            policy_id=self.policy_id,
            can_submit_diagnosis=(
                case_observation.session_status is CaseSessionStatus.ACTIVE
                and not case_observation.available_investigations
            ),
        )
