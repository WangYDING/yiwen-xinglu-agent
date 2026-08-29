"""In-process case tools that translate proposals into deterministic commands."""

from datetime import datetime
from typing import TypeVar

from pydantic import ConfigDict, Field, JsonValue, ValidationError

from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseActionType,
    CaseDefinition,
    CaseEvent,
    CaseSessionState,
    ExecuteTreatmentCommand,
    InvestigationCommand,
    PlayerState,
    SubmitDiagnosisCommand,
    ToolName,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.engine import (
    ActionMismatchError,
    CaseEngine,
    EngineResult,
    ScoreBreakdown,
    UnknownInvestigationError,
)

from .diagnosis_readiness import (
    DiagnosisReadinessPolicy,
)
from .views import AgentContextFilter, CaseObservation


class ToolCallError(ValueError):
    """Base error for requests rejected before a domain command is formed."""

    code = "tool_call_error"


class InvalidToolArgumentsError(ToolCallError):
    code = "invalid_tool_arguments"


class ToolActionRequiredError(ToolCallError):
    code = "tool_action_required"


class DiagnosisNotReadyError(ToolCallError):
    """Raised only when the selected runtime policy blocks diagnosis."""

    code = "diagnosis_not_ready"


class ToolArguments(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class EmptyToolArguments(ToolArguments):
    pass


class InvestigationToolArguments(ToolArguments):
    investigation_id: Identifier


class DiagnosisToolArguments(ToolArguments):
    diagnosis_id: Identifier
    evidence_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)


class TreatmentToolArguments(ToolArguments):
    treatment_id: Identifier


class ToolExecutionResult(DomainModel):
    """Validated application result; only domain events may change the session."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    session: CaseSessionState
    events: tuple[CaseEvent, ...] = Field(default_factory=tuple)
    message: NonEmptyText
    score_breakdown: ScoreBreakdown | None = None


INVESTIGATION_TOOL_ACTIONS = {
    ToolName.OBSERVE_PATIENT: CaseActionType.OBSERVE_PATIENT,
    ToolName.QUESTION_PATIENT: CaseActionType.QUESTION_PATIENT,
    ToolName.INSPECT_OBJECT: CaseActionType.INSPECT_OBJECT,
    ToolName.OBSERVE_QI: CaseActionType.OBSERVE_QI,
    ToolName.INVESTIGATE_LOCATION: CaseActionType.INVESTIGATE_LOCATION,
}


ArgumentsT = TypeVar("ArgumentsT", bound=ToolArguments)


class CaseToolExecutor:
    """Validate a model proposal and delegate every state change to CaseEngine."""

    def __init__(
        self,
        engine: CaseEngine | None = None,
        context_filter: AgentContextFilter | None = None,
        diagnosis_readiness_policy: DiagnosisReadinessPolicy | None = None,
    ) -> None:
        self.engine = engine or CaseEngine()
        self.context_filter = context_filter or AgentContextFilter()
        self.diagnosis_readiness_policy = diagnosis_readiness_policy

    def case_observation(
        self,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
        proposed_action: AgentAction | None = None,
    ) -> CaseObservation:
        """Apply the selected runtime policy to the otherwise generic safe view."""

        observation = self.context_filter.case_observation(case, player, session)
        if self.diagnosis_readiness_policy is None:
            return observation
        decision = self.diagnosis_readiness_policy.evaluate(
            player_view=self.context_filter.player_view(player),
            case_observation=observation,
            proposed_action=proposed_action,
        )
        return observation.model_copy(
            update={"can_submit_diagnosis": decision.can_submit_diagnosis}
        )

    def execute(
        self,
        action: AgentAction,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
        occurred_at: datetime,
    ) -> ToolExecutionResult:
        if action.action_type is not AgentActionType.USE_TOOL or action.tool_call is None:
            raise ToolActionRequiredError("a use_tool AgentAction is required")

        call = action.tool_call
        if call.name is ToolName.GET_PLAYER_VIEW:
            self._parse_arguments(EmptyToolArguments, call.arguments)
            view = self.context_filter.player_view(player)
            return ToolExecutionResult(
                session=session,
                message=f"玩家只读视图已刷新，可用技能 {len(view.available_skills)} 项。",
            )

        if call.name is ToolName.GET_CASE_OBSERVATION:
            self._parse_arguments(EmptyToolArguments, call.arguments)
            view = self.case_observation(case, player, session)
            return ToolExecutionResult(
                session=session,
                message=(
                    "病例只读观察已刷新："
                    f"已发现 {len(view.discovered_clues)} 条线索，"
                    f"当前可用调查 {len(view.available_investigations)} 项。"
                ),
            )

        if call.name in INVESTIGATION_TOOL_ACTIONS:
            arguments = self._parse_arguments(
                InvestigationToolArguments,
                call.arguments,
            )
            investigation = next(
                (
                    item
                    for item in case.investigations
                    if item.investigation_id == arguments.investigation_id
                ),
                None,
            )
            if investigation is None:
                raise UnknownInvestigationError(
                    f"unknown investigation: {arguments.investigation_id}"
                )
            requested_action = INVESTIGATION_TOOL_ACTIONS[call.name]
            if investigation.action_type is not requested_action:
                raise ActionMismatchError(
                    "tool name does not match the investigation action type"
                )
            result = self.engine.execute(
                case,
                player,
                session,
                InvestigationCommand(
                    investigation_id=investigation.investigation_id,
                    action_type=requested_action,
                    target_id=investigation.target_id,
                    occurred_at=occurred_at,
                ),
            )
            return self._from_engine(result)

        if call.name is ToolName.SUBMIT_DIAGNOSIS:
            arguments = self._parse_arguments(DiagnosisToolArguments, call.arguments)
            if (
                arguments.diagnosis_id in case.diagnosis_candidates
                and self.diagnosis_readiness_policy is not None
            ):
                observation = self.case_observation(
                    case,
                    player,
                    session,
                    proposed_action=action,
                )
                if not observation.can_submit_diagnosis:
                    raise DiagnosisNotReadyError(
                        "the selected runtime policy does not permit diagnosis yet"
                    )
            result = self.engine.execute(
                case,
                player,
                session,
                SubmitDiagnosisCommand(
                    diagnosis_id=arguments.diagnosis_id,
                    evidence_clue_ids=arguments.evidence_clue_ids,
                    occurred_at=occurred_at,
                ),
            )
            return self._from_engine(result)

        if call.name is ToolName.EXECUTE_TREATMENT:
            arguments = self._parse_arguments(TreatmentToolArguments, call.arguments)
            result = self.engine.execute(
                case,
                player,
                session,
                ExecuteTreatmentCommand(
                    treatment_id=arguments.treatment_id,
                    occurred_at=occurred_at,
                ),
            )
            return self._from_engine(result)

        raise ToolCallError(f"unsupported tool: {call.name.value}")

    @staticmethod
    def _parse_arguments(
        model_type: type[ArgumentsT],
        arguments: dict[str, JsonValue],
    ) -> ArgumentsT:
        try:
            return model_type.model_validate(arguments)
        except ValidationError as exc:
            raise InvalidToolArgumentsError("tool arguments failed validation") from exc

    @staticmethod
    def _from_engine(result: EngineResult) -> ToolExecutionResult:
        return ToolExecutionResult(
            session=result.session,
            events=result.events,
            message=result.message,
            score_breakdown=result.score_breakdown,
        )
