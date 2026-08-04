"""In-process V0 tools that translate proposals into deterministic commands."""

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

from .views import AgentContextFilter


class ToolCallError(ValueError):
    """Base error for requests rejected before a domain command is formed."""

    code = "tool_call_error"


class InvalidToolArgumentsError(ToolCallError):
    code = "invalid_tool_arguments"


class ToolActionRequiredError(ToolCallError):
    code = "tool_action_required"


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


class V0ToolExecutor:
    """Validate a model proposal and delegate every state change to CaseEngine."""

    def __init__(
        self,
        engine: CaseEngine | None = None,
        context_filter: AgentContextFilter | None = None,
    ) -> None:
        self.engine = engine or CaseEngine()
        self.context_filter = context_filter or AgentContextFilter()

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
            view = self.context_filter.case_observation(case, player, session)
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
