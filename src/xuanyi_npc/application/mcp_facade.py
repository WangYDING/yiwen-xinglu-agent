"""Safe application boundary shared by in-process MCP tool handlers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol

from pydantic import (
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    ValidationError,
    model_validator,
)

from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseDefinition,
    CaseSessionState,
    PlayerState,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.engine import CaseEngine, RuleViolation
from xuanyi_npc.storage import JsonStateStore, StorageError

from .diagnosis_readiness import FixedV0DiagnosisReadinessPolicy
from .v0_tools import ToolCallError, V0ToolExecutor
from .views import AgentContextFilter, CaseObservation, PlayerView, ViewContextError


class MCPClock(Protocol):
    def now(self) -> datetime:
        """Return a timezone-aware timestamp for a tool invocation."""


class SystemMCPClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class MCPApplicationResult(DomainModel):
    """Least-privilege result returned by every M3-P0 tool."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    ok: StrictBool
    error_code: Identifier | None = None
    message: NonEmptyText
    session_revision: StrictInt = Field(ge=0)
    event_sequences: tuple[StrictInt, ...] = Field(default_factory=tuple)
    player_view: PlayerView | None = None
    case_observation: CaseObservation | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "MCPApplicationResult":
        if self.ok and self.error_code is not None:
            raise ValueError("successful tool results cannot contain an error code")
        if not self.ok and self.error_code is None:
            raise ValueError("rejected tool results require an error code")
        if not self.ok and self.event_sequences:
            raise ValueError("rejected tool results cannot contain events")
        if (
            self.case_observation is not None
            and self.case_observation.session_revision != self.session_revision
        ):
            raise ValueError("result and observation revisions must match")
        return self


SAFE_ERROR_MESSAGES: Mapping[str, str] = {
    "invalid_tool_arguments": "工具参数无效，请使用工具 Schema 和刷新后的公开选项重试。",
    "diagnosis_not_ready": "当前诊断尚未开放，请先使用刷新后的公开调查选项。",
    "unknown_investigation": "该调查不在当前公开可用选项中。",
    "investigation_already_completed": "该调查已经完成，请使用刷新后的公开选项。",
    "action_mismatch": "调查工具与公开调查选项不匹配。",
    "skill_locked": "当前玩家尚未解锁执行该调查所需的能力。",
    "insufficient_skill": "当前玩家能力不足，无法执行该调查。",
    "missing_clue_prerequisite": "该调查的公开前置条件尚未满足。",
    "evidence_not_discovered": "诊断只能引用已经发现的证据。",
    "unknown_diagnosis": "该诊断不在公开候选词表中。",
    "diagnosis_required": "执行处置前必须先提交诊断。",
    "unknown_treatment": "该处置不在当前公开可用选项中。",
    "treatment_prerequisite_missing": "该处置的公开前置条件尚未满足。",
    "session_closed": "病例已经结束，不能继续执行操作。",
    "context_mismatch": "玩家、会话或病例上下文不匹配。",
    "state_unavailable": "当前会话状态不可用。",
    "internal_error": "工具暂时无法完成请求，状态未改变。",
}


class MCPApplicationService:
    """Load, validate, execute and persist without exposing domain internals."""

    def __init__(
        self,
        *,
        state_store: JsonStateStore,
        case_root: Path | str,
        engine: CaseEngine | None = None,
        context_filter: AgentContextFilter | None = None,
        diagnosis_policy: FixedV0DiagnosisReadinessPolicy | None = None,
        clock: MCPClock | None = None,
    ) -> None:
        self.state_store = state_store
        self.case_root = Path(case_root)
        self.context_filter = context_filter or AgentContextFilter()
        self.tool_executor = V0ToolExecutor(
            engine=engine or CaseEngine(),
            context_filter=self.context_filter,
            diagnosis_readiness_policy=(
                diagnosis_policy or FixedV0DiagnosisReadinessPolicy()
            ),
        )
        self.clock = clock or SystemMCPClock()

    def execute_tool(
        self,
        *,
        tool_name: ToolName,
        player_id: str,
        session_id: str,
        tool_arguments: dict[str, JsonValue],
    ) -> MCPApplicationResult:
        """Execute one existing V0 tool and persist only accepted event changes."""

        try:
            player, session, case = self._load_context(player_id, session_id)
            action = AgentAction(
                action_id=f"mcp_{tool_name.value}",
                action_type=AgentActionType.USE_TOOL,
                dialogue="执行公开工具请求。",
                tool_call=ToolCallRequest(
                    name=tool_name,
                    arguments=tool_arguments,
                ),
                confidence=1.0,
            )
            result = self.tool_executor.execute(
                action,
                case,
                player,
                session,
                self.clock.now(),
            )
        except (RuleViolation, ToolCallError) as exc:
            return self._rejection(
                code=exc.code,
                player=locals().get("player"),
                session=locals().get("session"),
                case=locals().get("case"),
            )
        except ViewContextError:
            return self._safe_failure("context_mismatch")
        except (StorageError, ValidationError, OSError, ValueError):
            return self._safe_failure("state_unavailable")
        except Exception:
            return self._safe_failure("internal_error")

        try:
            response = self._result_for_context(
                ok=True,
                code=None,
                message=result.message,
                player=player,
                session=result.session,
                case=case,
                event_sequences=tuple(event.sequence for event in result.events),
            )
        except Exception:
            return self._safe_failure("internal_error")

        if result.events:
            try:
                self.state_store.save_case_session(result.session)
            except StorageError:
                return self._result_for_context(
                    ok=False,
                    code="internal_error",
                    player=player,
                    session=session,
                    case=case,
                )

        return response

    def invalid_arguments(
        self,
        *,
        raw_arguments: object,
    ) -> MCPApplicationResult:
        """Return a schema rejection and refresh views when safe IDs are available."""

        if isinstance(raw_arguments, dict):
            player_id = raw_arguments.get("player_id")
            session_id = raw_arguments.get("session_id")
            if isinstance(player_id, str) and isinstance(session_id, str):
                try:
                    player, session, case = self._load_context(player_id, session_id)
                except Exception:
                    pass
                else:
                    return self._result_for_context(
                        ok=False,
                        code="invalid_tool_arguments",
                        player=player,
                        session=session,
                        case=case,
                    )
        return self._safe_failure("invalid_tool_arguments")

    def internal_failure(self) -> MCPApplicationResult:
        """Map an unexpected handler failure without exposing implementation details."""

        return self._safe_failure("internal_error")

    def _load_context(
        self,
        player_id: str,
        session_id: str,
    ) -> tuple[PlayerState, CaseSessionState, CaseDefinition]:
        player = self.state_store.load_player(player_id)
        session = self.state_store.load_case_session(session_id)
        case_path = self.case_root / f"{session.case_id}.json"
        try:
            case = CaseDefinition.model_validate_json(
                case_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError, ValidationError) as exc:
            raise StorageError("case definition is unavailable") from exc
        self.tool_executor.case_observation(case, player, session)
        return player, session, case

    def _rejection(
        self,
        *,
        code: str,
        player: PlayerState | None,
        session: CaseSessionState | None,
        case: CaseDefinition | None,
    ) -> MCPApplicationResult:
        if player is None or session is None or case is None:
            return self._safe_failure("state_unavailable")
        return self._result_for_context(
            ok=False,
            code=code,
            player=player,
            session=session,
            case=case,
        )

    def _result_for_context(
        self,
        *,
        ok: bool,
        code: str | None,
        player: PlayerState,
        session: CaseSessionState,
        case: CaseDefinition,
        message: str | None = None,
        event_sequences: tuple[int, ...] = (),
    ) -> MCPApplicationResult:
        return MCPApplicationResult(
            ok=ok,
            error_code=code,
            message=(
                message
                if ok
                else SAFE_ERROR_MESSAGES.get(
                    code or "",
                    SAFE_ERROR_MESSAGES["internal_error"],
                )
            ),
            session_revision=session.revision,
            event_sequences=event_sequences,
            player_view=self.context_filter.player_view(player),
            case_observation=self.tool_executor.case_observation(
                case,
                player,
                session,
            ),
        )

    @staticmethod
    def _safe_failure(code: str) -> MCPApplicationResult:
        return MCPApplicationResult(
            ok=False,
            error_code=code,
            message=SAFE_ERROR_MESSAGES.get(
                code,
                SAFE_ERROR_MESSAGES["internal_error"],
            ),
            session_revision=0,
        )
