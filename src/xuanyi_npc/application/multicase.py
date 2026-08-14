"""M5-P1 application boundary for playable, persistent case Episodes."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Mapping, Protocol

from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    AbilityId,
    CampaignState,
    CaseDefinition,
    CaseEvent,
    CaseSessionState,
    CaseSessionStatus,
    KnowledgeUnlock,
    PlayerState,
    RelationshipState,
    SkillState,
    ToolName,
    TreatmentOutcome,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.engine import CaseEngine, RuleViolation, ScoreBreakdown
from xuanyi_npc.storage import (
    JsonStateStore,
    StateCorruptionError,
    StateNotFoundError,
    StorageError,
)

from .diagnosis_readiness import FixedV0DiagnosisReadinessPolicy
from .campaign import (
    CampaignCoordinator,
    CampaignError,
    CampaignRuleSet,
    CampaignSourceError,
    CampaignView,
    KnowledgeView,
)
from .progression import (
    AbilityChangeView,
    ApprenticeshipCoordinator,
    ApprenticeshipView,
    ProgressionError,
    ProgressionPolicy,
    ProgressionSourceError,
    RelationshipChangeView,
)
from .v0_tools import INVESTIGATION_TOOL_ACTIONS, ToolCallError, V0ToolExecutor
from .views import (
    AgentContextFilter,
    CaseObservation,
    DiagnosisCandidateView,
    InvestigationOptionView,
    TreatmentOptionView,
    ViewContextError,
)


DISPLAY_NAME_MAX_LENGTH = 40
MUTATING_CASE_TOOLS = frozenset(
    {
        *INVESTIGATION_TOOL_ACTIONS,
        ToolName.SUBMIT_DIAGNOSIS,
        ToolName.EXECUTE_TREATMENT,
    }
)


class MultiCaseContract(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


def normalize_display_name(value: str) -> str:
    """Normalize visible whitespace while rejecting invisible control input."""

    if not isinstance(value, str):
        raise TypeError("display name must be a string")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("display name cannot contain control characters")
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split())
    if not normalized:
        raise ValueError("display name cannot be empty")
    if len(normalized) > DISPLAY_NAME_MAX_LENGTH:
        raise ValueError("display name is too long")
    return normalized


class CreatePlayerInput(MultiCaseContract):
    display_name: str

    @field_validator("display_name", mode="before")
    @classmethod
    def validate_display_name(cls, value: object) -> str:
        return normalize_display_name(value)  # type: ignore[arg-type]


class ListPlayersInput(MultiCaseContract):
    pass


class ListCasesInput(MultiCaseContract):
    player_id: Identifier


class CampaignPlayerInput(MultiCaseContract):
    player_id: Identifier


class ReconcileCampaignInput(MultiCaseContract):
    player_id: Identifier


class ApprenticeshipPlayerInput(MultiCaseContract):
    player_id: Identifier


class StartEpisodeInput(MultiCaseContract):
    player_id: Identifier
    case_id: Identifier


class ResumeEpisodeInput(MultiCaseContract):
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier


class SubmitActionInput(MultiCaseContract):
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    action: AgentAction


class FinishEpisodeInput(MultiCaseContract):
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier


class QuitInput(MultiCaseContract):
    player_id: Identifier | None = None
    case_id: Identifier | None = None
    session_id: Identifier | None = None

    @model_validator(mode="after")
    def require_complete_context(self) -> "QuitInput":
        supplied = (self.player_id, self.case_id, self.session_id)
        if any(item is not None for item in supplied) and any(
            item is None for item in supplied
        ):
            raise ValueError("quit context must be fully specified or fully omitted")
        return self


class CasePlayStatus(str, Enum):
    AVAILABLE = "available"
    ACTIVE = "active"
    COMPLETED = "completed"


class CampaignProjectionStatus(str, Enum):
    READY = "ready"
    PENDING = "pending"


class ApprenticeshipProjectionStatus(str, Enum):
    READY = "ready"
    PENDING = "pending"


class PlayerSummary(MultiCaseContract):
    player_id: Identifier
    display_name: NonEmptyText
    revision: Annotated[StrictInt, Field(ge=0)]


class CaseCatalogEntry(MultiCaseContract):
    case_id: Identifier
    title: NonEmptyText
    synopsis: NonEmptyText
    play_status: CasePlayStatus
    can_start: StrictBool
    active_session_id: Identifier | None = None
    completed_session_id: Identifier | None = None
    is_recommended_next: StrictBool = False
    recommendation_reason: NonEmptyText | None = None
    related_knowledge: tuple[KnowledgeView, ...] = Field(default_factory=tuple)


class PublicActionOptions(MultiCaseContract):
    investigations: tuple[InvestigationOptionView, ...] = Field(default_factory=tuple)
    diagnoses: tuple[DiagnosisCandidateView, ...] = Field(default_factory=tuple)
    treatments: tuple[TreatmentOptionView, ...] = Field(default_factory=tuple)


class PublicEpisodeResult(MultiCaseContract):
    status: CaseSessionStatus
    outcome: TreatmentOutcome | None = None
    score: Annotated[StrictInt, Field(ge=0, le=100)] | None = None
    submitted_diagnosis_id: Identifier | None = None
    selected_treatment_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_completion_fields(self) -> "PublicEpisodeResult":
        final_values = (self.outcome, self.score, self.selected_treatment_id)
        if self.status is CaseSessionStatus.COMPLETED and any(
            value is None for value in final_values
        ):
            raise ValueError("completed public result requires final fields")
        if self.status is CaseSessionStatus.ACTIVE and any(
            value is not None for value in (self.outcome, self.score)
        ):
            raise ValueError("active public result cannot contain outcome or score")
        return self


class MultiCaseServiceResult(MultiCaseContract):
    """One least-privilege result shape shared by all M5-P1 operations."""

    ok: StrictBool
    error_code: Identifier | None = None
    message: NonEmptyText
    player_id: Identifier | None = None
    case_id: Identifier | None = None
    session_id: Identifier | None = None
    player_revision: Annotated[StrictInt, Field(ge=0)] | None = None
    session_revision: Annotated[StrictInt, Field(ge=0)] | None = None
    observation: CaseObservation | None = None
    action_options: PublicActionOptions | None = None
    episode_result: PublicEpisodeResult | None = None
    players: tuple[PlayerSummary, ...] = Field(default_factory=tuple)
    cases: tuple[CaseCatalogEntry, ...] = Field(default_factory=tuple)
    campaign_view: CampaignView | None = None
    campaign_status: CampaignProjectionStatus | None = None
    campaign_error_code: Identifier | None = None
    campaign_event_sequences: tuple[
        Annotated[StrictInt, Field(ge=1)], ...
    ] = Field(default_factory=tuple)
    history_reaction: NonEmptyText | None = None
    recommended_investigation_id: Identifier | None = None
    investigation_recommendation_reason: NonEmptyText | None = None
    newly_unlocked_knowledge: tuple[KnowledgeView, ...] = Field(default_factory=tuple)
    apprenticeship_view: ApprenticeshipView | None = None
    apprenticeship_status: ApprenticeshipProjectionStatus | None = None
    apprenticeship_error_code: Identifier | None = None
    apprenticeship_event_sequences: tuple[
        Annotated[StrictInt, Field(ge=1)], ...
    ] = Field(default_factory=tuple)
    ability_changes: tuple[AbilityChangeView, ...] = Field(default_factory=tuple)
    relationship_changes: tuple[RelationshipChangeView, ...] = Field(default_factory=tuple)
    event_sequences: tuple[Annotated[StrictInt, Field(ge=1)], ...] = Field(
        default_factory=tuple
    )

    @model_validator(mode="after")
    def validate_result_shape(self) -> "MultiCaseServiceResult":
        if self.ok and self.error_code is not None:
            raise ValueError("successful result cannot include an error code")
        if not self.ok and self.error_code is None:
            raise ValueError("failed result requires an error code")
        if not self.ok and self.event_sequences:
            raise ValueError("failed result cannot include events")
        if self.campaign_status is CampaignProjectionStatus.PENDING:
            if self.campaign_error_code != "campaign_projection_pending":
                raise ValueError("pending campaign result requires stable error code")
        elif self.campaign_error_code is not None:
            raise ValueError("campaign error code requires pending status")
        if self.apprenticeship_status is ApprenticeshipProjectionStatus.PENDING:
            if self.apprenticeship_error_code != "apprenticeship_projection_pending":
                raise ValueError("pending apprenticeship result requires stable error code")
        elif self.apprenticeship_error_code is not None:
            raise ValueError("apprenticeship error code requires pending status")
        if self.observation is not None:
            if self.session_revision != self.observation.session_revision:
                raise ValueError("observation and result revisions must match")
            if self.case_id != self.observation.case_id:
                raise ValueError("observation and result case IDs must match")
        return self


class MultiCaseActionReceipt(MultiCaseContract):
    """Internal orchestration receipt without widening the public CLI contract."""

    result: MultiCaseServiceResult
    events: tuple[CaseEvent, ...] = Field(default_factory=tuple)
    score_breakdown: ScoreBreakdown | None = None

    @model_validator(mode="after")
    def validate_receipt(self) -> "MultiCaseActionReceipt":
        sequences = tuple(event.sequence for event in self.events)
        if sequences != self.result.event_sequences:
            raise ValueError("receipt events must match the public event sequences")
        if not self.result.ok and self.events:
            raise ValueError("rejected actions cannot carry domain events")
        return self


class CaseCatalogError(RuntimeError):
    """Raised before interactive startup when trusted case data is unusable."""


class CaseCatalog:
    """Validated in-memory definitions loaded once from a trusted directory."""

    def __init__(self, case_dir: Path | str) -> None:
        root = Path(case_dir)
        if not root.is_dir():
            raise CaseCatalogError("case directory is unavailable")
        try:
            case_files = tuple(sorted(root.glob("*.json"), key=lambda path: path.name))
        except OSError as exc:
            raise CaseCatalogError("case directory cannot be read") from exc
        if not case_files:
            raise CaseCatalogError("case directory contains no case definitions")

        definitions: dict[str, CaseDefinition] = {}
        for case_file in case_files:
            try:
                definition = CaseDefinition.model_validate_json(
                    case_file.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, ValidationError) as exc:
                raise CaseCatalogError("case data validation failed") from exc
            if definition.case_id in definitions:
                raise CaseCatalogError("duplicate case_id in case catalog")
            definitions[definition.case_id] = definition
        self._definitions = definitions

    def case_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._definitions))

    def get(self, case_id: str) -> CaseDefinition | None:
        return self._definitions.get(case_id)


class PlayerIdFactory(Protocol):
    def new_player_id(self) -> str:
        """Return one Identifier-compatible player ID."""


class SessionIdFactory(Protocol):
    def new_session_id(self) -> str:
        """Return one Identifier-compatible session ID."""


class UUIDPlayerIdFactory:
    def new_player_id(self) -> str:
        return f"player_{uuid.uuid4().hex}"


class UUIDSessionIdFactory:
    def new_session_id(self) -> str:
        return f"session_{uuid.uuid4().hex}"


class EpisodeClock(Protocol):
    def now(self) -> datetime:
        """Return a timezone-aware application-owned timestamp."""


class SystemEpisodeClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


SAFE_SERVICE_MESSAGES: Mapping[str, str] = {
    "player_not_found": "未找到该玩家，请刷新玩家列表后重试。",
    "case_not_found": "未找到该病例，请刷新病例目录后重试。",
    "session_not_found": "未找到该病例进度，请刷新病例目录后重试。",
    "session_player_mismatch": "该病例进度不属于当前玩家。",
    "session_case_mismatch": "病例进度与所选病例不一致。",
    "active_episode_exists": "该玩家在此病例中已有未完成进度，请继续原进度。",
    "case_already_completed": "该玩家已经完成此病例，可以查看公开结果。",
    "multiple_active_sessions": "检测到相互冲突的未完成进度，已停止操作。",
    "episode_not_completed": "病例尚未完成，不能查看最终结果。",
    "unsupported_action": "该操作不属于当前可执行的病例行动。",
    "id_conflict": "无法创建唯一标识，请稍后重试。",
    "state_corrupt": "本地存档无法安全读取，请停止操作并检查存档。",
    "state_unavailable": "本地存档暂时不可用，状态未改变。",
    "context_mismatch": "玩家、病例或会话上下文不匹配。",
    "internal_error": "操作未能安全完成，状态未改变。",
    "diagnosis_not_ready": "当前诊断尚未开放，请先使用刷新后的公开调查选项。",
    "unknown_investigation": "该调查不在当前病例中。",
    "investigation_already_completed": "该调查已经完成，请使用刷新后的公开选项。",
    "investigation_requirement_already_satisfied": "该项调查要求已经通过等价路径满足，请使用刷新后的公开选项。",
    "action_mismatch": "调查类型与公开选项不匹配。",
    "skill_locked": "当前玩家尚未解锁执行该调查所需的能力。",
    "insufficient_skill": "当前玩家能力不足，无法执行该调查。",
    "missing_clue_prerequisite": "该调查的公开前置条件尚未满足。",
    "evidence_not_discovered": "诊断只能引用已经发现的证据。",
    "unknown_diagnosis": "该诊断不在公开候选词表中。",
    "diagnosis_required": "执行处置前必须先提交诊断。",
    "unknown_treatment": "该处置不在当前公开可用选项中。",
    "treatment_prerequisite_missing": "该处置的公开前置条件尚未满足。",
    "session_closed": "病例已经结束，不能继续执行操作。",
    "invalid_tool_arguments": "行动参数无效，请使用刷新后的公开选项。",
    "campaign_state_corrupt": "玩家历程存档无法安全读取，不能当作空历程继续。",
    "campaign_projection_pending": "病例结果已经保存，但玩家历程尚待协调补齐。",
    "campaign_source_invalid": "已提交病例与玩家历程来源不一致，已停止协调。",
    "campaign_source_missing": "玩家历程引用的病例存档缺失，已停止协调。",
    "campaign_source_conflict": "玩家历程与病例存档不一致，已停止协调。",
    "apprenticeship_state_corrupt": "弟子长期成长存档无法安全读取，不能当作空状态继续。",
    "apprenticeship_projection_pending": "病例和玩家历程已经保存，但本次成长尚待协调补齐。",
    "apprenticeship_source_invalid": "已提交病例与成长来源不一致，已停止协调。",
    "apprenticeship_source_missing": "成长记录引用的病例存档缺失，已停止协调。",
    "apprenticeship_source_conflict": "成长记录与病例存档不一致，已停止协调。",
}


class MultiCaseEpisodeService:
    """Application facade for M5-P1; CLI never mutates persistence directly."""

    def __init__(
        self,
        *,
        state_store: JsonStateStore,
        case_catalog: CaseCatalog,
        player_id_factory: PlayerIdFactory | None = None,
        session_id_factory: SessionIdFactory | None = None,
        clock: EpisodeClock | None = None,
        engine: CaseEngine | None = None,
        context_filter: AgentContextFilter | None = None,
        campaign_rules: CampaignRuleSet | None = None,
        progression_policy: ProgressionPolicy | None = None,
        legacy_auto_foundation: bool = False,
    ) -> None:
        self.state_store = state_store
        self.case_catalog = case_catalog
        self.player_id_factory = player_id_factory or UUIDPlayerIdFactory()
        self.session_id_factory = session_id_factory or UUIDSessionIdFactory()
        self.clock = clock or SystemEpisodeClock()
        self.context_filter = context_filter or AgentContextFilter()
        self.tool_executor = V0ToolExecutor(
            engine=engine or CaseEngine(),
            context_filter=self.context_filter,
            diagnosis_readiness_policy=FixedV0DiagnosisReadinessPolicy(),
        )
        self.campaign_rules = campaign_rules or CampaignRuleSet.empty(case_catalog)
        self.campaign_coordinator = CampaignCoordinator(
            state_store,
            self.campaign_rules,
        )
        self.progression_policy = progression_policy or ProgressionPolicy.load_default()
        self.legacy_auto_foundation = legacy_auto_foundation
        self.apprenticeship_coordinator = ApprenticeshipCoordinator(
            state_store,
            case_catalog,
            self.progression_policy,
        )

    def create_player(self, request: CreatePlayerInput) -> MultiCaseServiceResult:
        try:
            player_id = self.player_id_factory.new_player_id()
            if any(
                player.player_id == player_id
                for player in self.state_store.list_players()
            ):
                return self._error("id_conflict")
            player = self._initial_player(player_id, request.display_name)
            self.state_store.save_player(player)
            apprenticeship = self.apprenticeship_coordinator.initialize(
                player.player_id,
                self.clock.now(),
            )
            if self.legacy_auto_foundation:
                for exercise in self.progression_policy.config.foundation_exercises:
                    apprenticeship=self.complete_foundation_exercise(player.player_id,exercise.exercise_id,exercise.required_action_id).apprenticeship_view
                apprenticeship=self.state_store.load_apprenticeship(player.player_id)
            return MultiCaseServiceResult(
                ok=True,
                message="玩家已创建。",
                player_id=player.player_id,
                player_revision=player.revision,
                players=(self._player_summary(player),),
                apprenticeship_view=self.progression_policy.view(apprenticeship),
                apprenticeship_status=ApprenticeshipProjectionStatus.READY,
            )
        except StateCorruptionError:
            return self._error("state_corrupt")
        except StorageError:
            return self._error("state_unavailable")
        except (ValidationError, ValueError, TypeError):
            return self._error("id_conflict")
        except Exception:
            return self._error("internal_error")

    def list_players(self, request: ListPlayersInput) -> MultiCaseServiceResult:
        del request
        try:
            players = tuple(
                self._player_summary(player)
                for player in self.state_store.list_players()
            )
        except StateCorruptionError:
            return self._error("state_corrupt")
        except StorageError:
            return self._error("state_unavailable")
        return MultiCaseServiceResult(
            ok=True,
            message=("请选择玩家。" if players else "尚未创建玩家。"),
            players=players,
        )

    def list_cases(self, request: ListCasesInput) -> MultiCaseServiceResult:
        player_or_error = self._load_player(request.player_id)
        if isinstance(player_or_error, MultiCaseServiceResult):
            return player_or_error
        player = player_or_error
        campaign_or_error = self._load_campaign(player)
        if isinstance(campaign_or_error, MultiCaseServiceResult):
            return campaign_or_error
        campaign = campaign_or_error
        apprenticeship_or_error = self._load_apprenticeship(player)
        if isinstance(apprenticeship_or_error, MultiCaseServiceResult):
            return apprenticeship_or_error
        try:
            sessions = self._sessions_for_player(player.player_id)
            entries = tuple(
                self._catalog_entry(case_id, sessions, campaign)
                for case_id in self.case_catalog.case_ids()
            )
        except StateCorruptionError:
            return self._error("state_corrupt", player=player)
        except StorageError:
            return self._error("state_unavailable", player=player)
        except ValueError:
            return self._error("multiple_active_sessions", player=player)
        return MultiCaseServiceResult(
            ok=True,
            message="病例目录已刷新。",
            player_id=player.player_id,
            player_revision=player.revision,
            cases=entries,
            campaign_view=self.campaign_rules.view(campaign),
            campaign_status=CampaignProjectionStatus.READY,
            apprenticeship_view=self.progression_policy.view(apprenticeship_or_error),
            apprenticeship_status=ApprenticeshipProjectionStatus.READY,
        )

    def start_episode(self, request: StartEpisodeInput) -> MultiCaseServiceResult:
        player_or_error = self._load_player(request.player_id)
        if isinstance(player_or_error, MultiCaseServiceResult):
            return player_or_error
        player = player_or_error
        case = self.case_catalog.get(request.case_id)
        if case is None:
            return self._error("case_not_found", player=player, case_id=request.case_id)
        campaign_or_error = self._load_campaign(player)
        if isinstance(campaign_or_error, MultiCaseServiceResult):
            return campaign_or_error
        campaign = campaign_or_error
        try:
            sessions = self._sessions_for_player(player.player_id)
            active = tuple(
                session
                for session in sessions
                if session.case_id == case.case_id
                and session.status is CaseSessionStatus.ACTIVE
            )
            if len(active) > 1:
                return self._error("multiple_active_sessions", player=player)
            if active:
                return self._context_result(
                    ok=False,
                    code="active_episode_exists",
                    player=player,
                    case=case,
                    session=active[0],
                    campaign_state=campaign,
                )
            completed = tuple(
                session
                for session in sessions
                if session.case_id == case.case_id
                and session.status is CaseSessionStatus.COMPLETED
            )
            if completed:
                latest = max(
                    completed,
                    key=lambda session: (session.revision, session.session_id),
                )
                return self._context_result(
                    ok=False,
                    code="case_already_completed",
                    player=player,
                    case=case,
                    session=latest,
                    campaign_state=campaign,
                )
            session_id = self.session_id_factory.new_session_id()
            if any(
                session.session_id == session_id
                for session in self.state_store.list_case_sessions()
            ):
                return self._error("id_conflict", player=player, case_id=case.case_id)
            session = CaseSessionState(
                session_id=session_id,
                case_id=case.case_id,
                player_id=player.player_id,
            )
            result = self._context_result(
                ok=True,
                code=None,
                message="病例进度已创建。",
                player=player,
                case=case,
                session=session,
                campaign_state=campaign,
            )
            self.state_store.save_case_session(session)
            return result
        except StateCorruptionError:
            return self._error("state_corrupt", player=player, case_id=case.case_id)
        except StorageError:
            return self._error("state_unavailable", player=player, case_id=case.case_id)
        except (ValidationError, ValueError, TypeError):
            return self._error("id_conflict", player=player, case_id=case.case_id)
        except Exception:
            return self._error("internal_error", player=player, case_id=case.case_id)

    def resume_episode(self, request: ResumeEpisodeInput) -> MultiCaseServiceResult:
        context = self._load_context(
            player_id=request.player_id,
            case_id=request.case_id,
            session_id=request.session_id,
        )
        if isinstance(context, MultiCaseServiceResult):
            return context
        player, case, session, campaign = context
        return self._context_result(
            ok=True,
            code=None,
            message=(
                "已恢复未完成病例。"
                if session.status is CaseSessionStatus.ACTIVE
                else "已读取完成病例的公开结果。"
            ),
            player=player,
            case=case,
            session=session,
            campaign_state=campaign,
        )

    def submit_action(self, request: SubmitActionInput) -> MultiCaseServiceResult:
        return self.submit_action_with_receipt(request).result

    def submit_action_with_receipt(
        self,
        request: SubmitActionInput,
    ) -> MultiCaseActionReceipt:
        context = self._load_context(
            player_id=request.player_id,
            case_id=request.case_id,
            session_id=request.session_id,
        )
        if isinstance(context, MultiCaseServiceResult):
            return MultiCaseActionReceipt(result=context)
        player, case, session, campaign = context
        action = request.action
        if session.status is CaseSessionStatus.COMPLETED:
            return MultiCaseActionReceipt(
                result=self._context_result(
                    ok=False,
                    code="session_closed",
                    player=player,
                    case=case,
                    session=session,
                    campaign_state=campaign,
                )
            )
        if (
            action.action_type is not AgentActionType.USE_TOOL
            or action.tool_call is None
            or action.tool_call.name not in MUTATING_CASE_TOOLS
        ):
            return MultiCaseActionReceipt(
                result=self._context_result(
                    ok=False,
                    code="unsupported_action",
                    player=player,
                    case=case,
                    session=session,
                    campaign_state=campaign,
                )
            )

        try:
            execution = self.tool_executor.execute(
                action,
                case,
                player,
                session,
                self.clock.now(),
            )
        except (RuleViolation, ToolCallError) as exc:
            return MultiCaseActionReceipt(
                result=self._context_result(
                    ok=False,
                    code=exc.code,
                    player=player,
                    case=case,
                    session=session,
                    campaign_state=campaign,
                )
            )
        except ViewContextError:
            return MultiCaseActionReceipt(
                result=self._context_result(
                    ok=False,
                    code="context_mismatch",
                    player=player,
                    case=case,
                    session=session,
                    campaign_state=campaign,
                )
            )
        except Exception:
            return MultiCaseActionReceipt(
                result=self._context_result(
                    ok=False,
                    code="internal_error",
                    player=player,
                    case=case,
                    session=session,
                    campaign_state=campaign,
                )
            )

        try:
            self.state_store.save_case_session(execution.session)
        except StorageError:
            return MultiCaseActionReceipt(
                result=self._context_result(
                    ok=False,
                    code="state_unavailable",
                    player=player,
                    case=case,
                    session=session,
                    campaign_state=campaign,
                )
            )
        except Exception:
            return MultiCaseActionReceipt(
                result=self._context_result(
                    ok=False,
                    code="internal_error",
                    player=player,
                    case=case,
                    session=session,
                    campaign_state=campaign,
                )
            )

        if execution.session.status is CaseSessionStatus.COMPLETED:
            result = self._project_completed_result(
                player=player,
                case=case,
                session=execution.session,
                prior_campaign=campaign,
                message=execution.message,
                event_sequences=tuple(
                    event.sequence for event in execution.events
                ),
            )
            return MultiCaseActionReceipt(
                result=result,
                events=execution.events,
                score_breakdown=execution.score_breakdown,
            )
        result = self._context_result(
            ok=True,
            code=None,
            message=execution.message,
            player=player,
            case=case,
            session=execution.session,
            campaign_state=campaign,
            event_sequences=tuple(event.sequence for event in execution.events),
        )
        return MultiCaseActionReceipt(
            result=result,
            events=execution.events,
            score_breakdown=execution.score_breakdown,
        )

    def finish_episode(self, request: FinishEpisodeInput) -> MultiCaseServiceResult:
        context = self._load_context(
            player_id=request.player_id,
            case_id=request.case_id,
            session_id=request.session_id,
        )
        if isinstance(context, MultiCaseServiceResult):
            return context
        player, case, session, campaign = context
        if session.status is not CaseSessionStatus.COMPLETED:
            return self._context_result(
                ok=False,
                code="episode_not_completed",
                player=player,
                case=case,
                session=session,
                campaign_state=campaign,
            )
        return self._project_completed_result(
            player=player,
            case=case,
            session=session,
            prior_campaign=campaign,
            message="病例公开结果已确认。",
        )

    def get_campaign_view(
        self,
        request: CampaignPlayerInput,
    ) -> MultiCaseServiceResult:
        return self._read_campaign_result(request.player_id, "玩家历程已刷新。")

    def get_apprenticeship_view(
        self,
        request: ApprenticeshipPlayerInput,
    ) -> MultiCaseServiceResult:
        player_or_error = self._load_player(request.player_id)
        if isinstance(player_or_error, MultiCaseServiceResult):
            return player_or_error
        state_or_error = self._load_apprenticeship(player_or_error)
        if isinstance(state_or_error, MultiCaseServiceResult):
            return state_or_error
        return MultiCaseServiceResult(
            ok=True,
            message="弟子长期成长已刷新。",
            player_id=player_or_error.player_id,
            player_revision=player_or_error.revision,
            apprenticeship_view=self.progression_policy.view(state_or_error),
            apprenticeship_status=ApprenticeshipProjectionStatus.READY,
        )

    def complete_foundation_exercise(self,player_id:str,exercise_id:str,action_id:str)->MultiCaseServiceResult:
        """Apply a deterministic exercise result; text and mentor output are never inputs."""
        player_or_error=self._load_player(player_id)
        if isinstance(player_or_error,MultiCaseServiceResult):return player_or_error
        try:
            result=self.apprenticeship_coordinator.complete_foundation_exercise(player_id,exercise_id,action_id,self.clock.now())
            return MultiCaseServiceResult(ok=True,message="入门练习已经由规则确认。",player_id=player_id,player_revision=player_or_error.revision,apprenticeship_view=self.progression_policy.view(result.state),apprenticeship_status=ApprenticeshipProjectionStatus.READY)
        except ProgressionSourceError:
            return self._error("apprenticeship_source_invalid",player=player_or_error)

    def list_completed_cases(
        self,
        request: CampaignPlayerInput,
    ) -> MultiCaseServiceResult:
        return self._read_campaign_result(request.player_id, "已完成病例已刷新。")

    def list_unlocked_knowledge(
        self,
        request: CampaignPlayerInput,
    ) -> MultiCaseServiceResult:
        return self._read_campaign_result(request.player_id, "已解锁知识已刷新。")

    def recommended_next_case(
        self,
        request: CampaignPlayerInput,
    ) -> MultiCaseServiceResult:
        return self._read_campaign_result(request.player_id, "推荐下一案已刷新。")

    def reconcile_campaign(
        self,
        request: ReconcileCampaignInput,
    ) -> MultiCaseServiceResult:
        player_or_error = self._load_player(request.player_id)
        if isinstance(player_or_error, MultiCaseServiceResult):
            return player_or_error
        player = player_or_error
        current_or_error = self._load_campaign(player)
        if isinstance(current_or_error, MultiCaseServiceResult):
            return current_or_error
        current = current_or_error
        try:
            result = self.campaign_coordinator.reconcile(player)
        except CampaignSourceError as exc:
            return MultiCaseServiceResult(
                ok=False,
                error_code=exc.code,
                message=SAFE_SERVICE_MESSAGES.get(
                    exc.code,
                    SAFE_SERVICE_MESSAGES["campaign_source_invalid"],
                ),
                player_id=player.player_id,
                player_revision=player.revision,
                campaign_view=self.campaign_rules.view(current),
                campaign_status=CampaignProjectionStatus.READY,
            )
        except StateCorruptionError:
            return self._error(
                "campaign_state_corrupt",
                player=player,
            )
        except StorageError:
            return MultiCaseServiceResult(
                ok=False,
                error_code="campaign_projection_pending",
                message=SAFE_SERVICE_MESSAGES["campaign_projection_pending"],
                player_id=player.player_id,
                player_revision=player.revision,
                campaign_view=self.campaign_rules.view(current),
                campaign_status=CampaignProjectionStatus.PENDING,
                campaign_error_code="campaign_projection_pending",
            )
        except CampaignError:
            return self._error("campaign_source_invalid", player=player)
        try:
            growth = self.apprenticeship_coordinator.reconcile(
                player,
                self.clock.now(),
            )
        except (StorageError, ProgressionError):
            return MultiCaseServiceResult(
                ok=True,
                message=(
                    "玩家历程已协调；"
                    f"{SAFE_SERVICE_MESSAGES['apprenticeship_projection_pending']}"
                ),
                player_id=player.player_id,
                player_revision=player.revision,
                campaign_view=self.campaign_rules.view(result.state),
                campaign_status=CampaignProjectionStatus.READY,
                campaign_event_sequences=tuple(
                    range(current.revision + 1, result.state.revision + 1)
                ),
                newly_unlocked_knowledge=self._knowledge_views(
                    result.newly_unlocked
                ),
                apprenticeship_status=ApprenticeshipProjectionStatus.PENDING,
                apprenticeship_error_code="apprenticeship_projection_pending",
            )
        return MultiCaseServiceResult(
            ok=True,
            message=(
                "玩家历程已补齐。" if result.changed else "玩家历程已经是最新状态。"
            ),
            player_id=player.player_id,
            player_revision=player.revision,
            campaign_view=self.campaign_rules.view(result.state),
            campaign_status=CampaignProjectionStatus.READY,
            campaign_event_sequences=tuple(
                range(current.revision + 1, result.state.revision + 1)
            ),
            newly_unlocked_knowledge=self._knowledge_views(
                result.newly_unlocked
            ),
            apprenticeship_view=self.progression_policy.view(growth.state),
            apprenticeship_status=ApprenticeshipProjectionStatus.READY,
            apprenticeship_event_sequences=growth.event_sequences,
            ability_changes=growth.ability_changes,
            relationship_changes=growth.relationship_changes,
        )

    def reconcile_apprenticeship(
        self,
        request: ApprenticeshipPlayerInput,
    ) -> MultiCaseServiceResult:
        return self.reconcile_campaign(
            ReconcileCampaignInput(player_id=request.player_id)
        )

    def quit(self, request: QuitInput) -> MultiCaseServiceResult:
        if request.player_id is None:
            return MultiCaseServiceResult(ok=True, message="进度已保存，可以安全退出。")
        context = self._load_context(
            player_id=request.player_id,
            case_id=request.case_id or "",
            session_id=request.session_id or "",
        )
        if isinstance(context, MultiCaseServiceResult):
            return context
        player, case, session, campaign = context
        return self._context_result(
            ok=True,
            code=None,
            message="当前进度已保存，可以安全退出。",
            player=player,
            case=case,
            session=session,
            campaign_state=campaign,
        )

    def _load_player(self, player_id: str) -> PlayerState | MultiCaseServiceResult:
        try:
            player=self.state_store.load_player(player_id)
            apprenticeship=self.state_store.load_apprenticeship(player_id)
            mapping={"observe_form":AbilityId.OBSERVE_FORM,"ask_cause":AbilityId.ASK_CAUSE,"inspect_object":AbilityId.INSPECT_EVIDENCE,"inspect_evidence":AbilityId.INSPECT_EVIDENCE,"observe_qi":AbilityId.OBSERVE_QI,"reason_diagnosis":AbilityId.REASON_DIAGNOSIS,"apply_treatment":AbilityId.APPLY_TREATMENT,"ethical_practice":AbilityId.ETHICAL_PRACTICE}
            skills={key:value.model_copy(update={"proficiency":apprenticeship.abilities[ability].proficiency,"unlocked":apprenticeship.abilities[ability].unlocked}) for key,value in player.skills.items() for ability in (mapping[key],)}
            return player.model_copy(update={"skills":skills})
        except StateNotFoundError:
            return self._error("player_not_found", player_id=player_id)
        except StateCorruptionError:
            return self._error("state_corrupt", player_id=player_id)
        except StorageError:
            return self._error("state_unavailable", player_id=player_id)

    def _load_campaign(
        self,
        player: PlayerState,
    ) -> CampaignState | MultiCaseServiceResult:
        try:
            campaign = self.campaign_coordinator.load_or_empty(player.player_id)
        except StateCorruptionError:
            return self._error("campaign_state_corrupt", player=player)
        except StorageError:
            return self._error("state_unavailable", player=player)
        if campaign.player_id != player.player_id:
            return self._error("campaign_source_invalid", player=player)
        return campaign

    def _load_apprenticeship(
        self,
        player: PlayerState,
    ):
        try:
            state = self.apprenticeship_coordinator.load_or_initialize(
                player.player_id,
                self.clock.now(),
            )
        except StateCorruptionError:
            return self._error("apprenticeship_state_corrupt", player=player)
        except StorageError:
            return self._error("state_unavailable", player=player)
        if state.player_id != player.player_id:
            return self._error("apprenticeship_source_invalid", player=player)
        return state

    def _read_campaign_result(
        self,
        player_id: str,
        message: str,
    ) -> MultiCaseServiceResult:
        player_or_error = self._load_player(player_id)
        if isinstance(player_or_error, MultiCaseServiceResult):
            return player_or_error
        player = player_or_error
        campaign_or_error = self._load_campaign(player)
        if isinstance(campaign_or_error, MultiCaseServiceResult):
            return campaign_or_error
        return MultiCaseServiceResult(
            ok=True,
            message=message,
            player_id=player.player_id,
            player_revision=player.revision,
            campaign_view=self.campaign_rules.view(campaign_or_error),
            campaign_status=CampaignProjectionStatus.READY,
        )

    def _project_completed_result(
        self,
        *,
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
        prior_campaign: CampaignState,
        message: str,
        event_sequences: tuple[int, ...] = (),
    ) -> MultiCaseServiceResult:
        try:
            projection = self.campaign_coordinator.project_completed(
                player,
                case,
                session,
            )
        except StorageError:
            return self._context_result(
                ok=True,
                code=None,
                message=(
                    f"{message} {SAFE_SERVICE_MESSAGES['campaign_projection_pending']}"
                ),
                player=player,
                case=case,
                session=session,
                campaign_state=prior_campaign,
                event_sequences=event_sequences,
                campaign_status=CampaignProjectionStatus.PENDING,
                campaign_error_code="campaign_projection_pending",
            )
        except CampaignSourceError as exc:
            return self._context_result(
                ok=True,
                code=None,
                message=(
                    f"{message} "
                    f"{SAFE_SERVICE_MESSAGES.get(exc.code, SAFE_SERVICE_MESSAGES['campaign_source_invalid'])}"
                ),
                player=player,
                case=case,
                session=session,
                campaign_state=prior_campaign,
                event_sequences=event_sequences,
                campaign_status=CampaignProjectionStatus.PENDING,
                campaign_error_code="campaign_projection_pending",
            )
        try:
            growth = self.apprenticeship_coordinator.project_completed(
                player,
                case,
                session,
                session.action_history[-1].occurred_at,
            )
        except (StorageError, ProgressionSourceError, ProgressionError):
            apprenticeship_view = None
            try:
                apprenticeship_view = self.progression_policy.view(
                    self.state_store.load_apprenticeship(player.player_id)
                )
            except StorageError:
                pass
            return self._context_result(
                ok=True,
                code=None,
                message=(
                    f"{message} "
                    f"{SAFE_SERVICE_MESSAGES['apprenticeship_projection_pending']}"
                ),
                player=player,
                case=case,
                session=session,
                campaign_state=projection.state,
                event_sequences=event_sequences,
                campaign_status=CampaignProjectionStatus.READY,
                campaign_event_sequences=(
                    (projection.event.sequence,) if projection.event is not None else ()
                ),
                newly_unlocked_knowledge=self._knowledge_views(
                    projection.newly_unlocked
                ),
                apprenticeship_view=apprenticeship_view,
                apprenticeship_status=ApprenticeshipProjectionStatus.PENDING,
                apprenticeship_error_code="apprenticeship_projection_pending",
            )
        return self._context_result(
            ok=True,
            code=None,
            message=message,
            player=player,
            case=case,
            session=session,
            campaign_state=projection.state,
            event_sequences=event_sequences,
            campaign_status=CampaignProjectionStatus.READY,
            campaign_event_sequences=(
                (projection.event.sequence,) if projection.event is not None else ()
            ),
            newly_unlocked_knowledge=self._knowledge_views(
                projection.newly_unlocked
            ),
            apprenticeship_view=self.progression_policy.view(growth.state),
            apprenticeship_status=ApprenticeshipProjectionStatus.READY,
            apprenticeship_event_sequences=growth.event_sequences,
            ability_changes=growth.ability_changes,
            relationship_changes=growth.relationship_changes,
        )

    @staticmethod
    def _knowledge_views(
        values: tuple[KnowledgeUnlock, ...],
    ) -> tuple[KnowledgeView, ...]:
        return tuple(
            KnowledgeView(
                knowledge_id=item.knowledge_id,
                public_description=item.public_description,
                unlocked_at=item.unlocked_at,
            )
            for item in values
        )

    def _load_context(
        self,
        *,
        player_id: str,
        case_id: str,
        session_id: str,
    ) -> (
        tuple[PlayerState, CaseDefinition, CaseSessionState, CampaignState]
        | MultiCaseServiceResult
    ):
        player_or_error = self._load_player(player_id)
        if isinstance(player_or_error, MultiCaseServiceResult):
            return player_or_error
        player = player_or_error
        try:
            session = self.state_store.load_case_session(session_id)
        except StateNotFoundError:
            return self._error(
                "session_not_found",
                player=player,
                case_id=case_id,
                session_id=session_id,
            )
        except StateCorruptionError:
            return self._error("state_corrupt", player=player)
        except StorageError:
            return self._error("state_unavailable", player=player)
        if session.player_id != player.player_id:
            return self._error(
                "session_player_mismatch",
                player=player,
                case_id=case_id,
                session_id=session_id,
            )
        if session.case_id != case_id:
            return self._error(
                "session_case_mismatch",
                player=player,
                case_id=case_id,
                session_id=session_id,
            )
        case = self.case_catalog.get(case_id)
        if case is None:
            return self._error(
                "case_not_found",
                player=player,
                case_id=case_id,
                session_id=session_id,
            )
        try:
            self.tool_executor.case_observation(case, player, session)
        except ViewContextError:
            return self._error("context_mismatch", player=player)
        campaign_or_error = self._load_campaign(player)
        if isinstance(campaign_or_error, MultiCaseServiceResult):
            return campaign_or_error
        return player, case, session, campaign_or_error

    def _sessions_for_player(self, player_id: str) -> tuple[CaseSessionState, ...]:
        sessions = tuple(
            session
            for session in self.state_store.list_case_sessions()
            if session.player_id == player_id
        )
        if any(self.case_catalog.get(session.case_id) is None for session in sessions):
            raise StateCorruptionError("session references an unavailable case")
        return sessions

    def _catalog_entry(
        self,
        case_id: str,
        sessions: tuple[CaseSessionState, ...],
        campaign: CampaignState,
    ) -> CaseCatalogEntry:
        definition = self.case_catalog.get(case_id)
        if definition is None:
            raise ValueError("catalog changed during listing")
        active = tuple(
            session
            for session in sessions
            if session.case_id == case_id and session.status is CaseSessionStatus.ACTIVE
        )
        if len(active) > 1:
            raise ValueError("multiple active sessions exist for one player and case")
        completed = tuple(
            sorted(
                (
                    session
                    for session in sessions
                    if session.case_id == case_id
                    and session.status is CaseSessionStatus.COMPLETED
                ),
                key=lambda session: (session.revision, session.session_id),
            )
        )
        status = (
            CasePlayStatus.ACTIVE
            if active
            else CasePlayStatus.COMPLETED
            if completed
            else CasePlayStatus.AVAILABLE
        )
        recommended = self.campaign_rules.recommended_next(campaign)
        context = self.campaign_rules.context_for(case_id, campaign)
        return CaseCatalogEntry(
            case_id=definition.case_id,
            title=definition.title,
            synopsis=definition.synopsis,
            play_status=status,
            can_start=not active and not completed,
            active_session_id=active[0].session_id if active else None,
            completed_session_id=completed[-1].session_id if completed else None,
            is_recommended_next=(
                recommended is not None and recommended.case_id == case_id
            ),
            recommendation_reason=(
                recommended.public_reason
                if recommended is not None and recommended.case_id == case_id
                else None
            ),
            related_knowledge=context.related_knowledge,
        )

    def _context_result(
        self,
        *,
        ok: bool,
        code: str | None,
        player: PlayerState,
        case: CaseDefinition,
        session: CaseSessionState,
        campaign_state: CampaignState,
        message: str | None = None,
        event_sequences: tuple[int, ...] = (),
        campaign_status: CampaignProjectionStatus = CampaignProjectionStatus.READY,
        campaign_error_code: str | None = None,
        campaign_event_sequences: tuple[int, ...] = (),
        newly_unlocked_knowledge: tuple[KnowledgeView, ...] = (),
        apprenticeship_view: ApprenticeshipView | None = None,
        apprenticeship_status: ApprenticeshipProjectionStatus | None = None,
        apprenticeship_error_code: str | None = None,
        apprenticeship_event_sequences: tuple[int, ...] = (),
        ability_changes: tuple[AbilityChangeView, ...] = (),
        relationship_changes: tuple[RelationshipChangeView, ...] = (),
    ) -> MultiCaseServiceResult:
        observation = self.tool_executor.case_observation(case, player, session)
        campaign_context = self.campaign_rules.context_for(
            case.case_id,
            campaign_state,
        )
        options = PublicActionOptions(
            investigations=observation.available_investigations,
            diagnoses=(
                observation.diagnosis_candidates
                if observation.can_submit_diagnosis
                else ()
            ),
            treatments=observation.available_treatments,
        )
        return MultiCaseServiceResult(
            ok=ok,
            error_code=code,
            message=(
                message
                if ok and message is not None
                else SAFE_SERVICE_MESSAGES.get(code or "", SAFE_SERVICE_MESSAGES["internal_error"])
            ),
            player_id=player.player_id,
            case_id=case.case_id,
            session_id=session.session_id,
            player_revision=player.revision,
            session_revision=session.revision,
            observation=observation,
            action_options=options,
            episode_result=self._public_episode_result(session),
            event_sequences=event_sequences,
            campaign_view=self.campaign_rules.view(campaign_state),
            campaign_status=campaign_status,
            campaign_error_code=campaign_error_code,
            campaign_event_sequences=campaign_event_sequences,
            history_reaction=campaign_context.history_reaction,
            recommended_investigation_id=(
                campaign_context.recommended_investigation_id
            ),
            investigation_recommendation_reason=(
                campaign_context.recommendation_reason
            ),
            newly_unlocked_knowledge=newly_unlocked_knowledge,
            apprenticeship_view=apprenticeship_view,
            apprenticeship_status=apprenticeship_status,
            apprenticeship_error_code=apprenticeship_error_code,
            apprenticeship_event_sequences=apprenticeship_event_sequences,
            ability_changes=ability_changes,
            relationship_changes=relationship_changes,
        )

    @staticmethod
    def _public_episode_result(session: CaseSessionState) -> PublicEpisodeResult:
        return PublicEpisodeResult(
            status=session.status,
            outcome=session.outcome,
            score=session.score,
            submitted_diagnosis_id=session.submitted_diagnosis_id,
            selected_treatment_id=session.selected_treatment_id,
        )

    @staticmethod
    def _initial_player(player_id: str, display_name: str) -> PlayerState:
        return PlayerState(
            player_id=player_id,
            display_name=display_name,
            skills={
                "observe_form": SkillState(
                    skill_id="observe_form", proficiency=0, unlocked=False
                ),
                "ask_cause": SkillState(
                    skill_id="ask_cause", proficiency=0, unlocked=False
                ),
                "inspect_evidence": SkillState(
                    skill_id="inspect_evidence",
                    proficiency=0,
                    unlocked=False,
                    prerequisite_ids={"observe_form"},
                ),
                "observe_qi": SkillState(
                    skill_id="observe_qi",
                    proficiency=0,
                    unlocked=False,
                    prerequisite_ids={"observe_form", "inspect_evidence"},
                ),
                "reason_diagnosis":SkillState(skill_id="reason_diagnosis",proficiency=0,unlocked=False),
                "apply_treatment":SkillState(skill_id="apply_treatment",proficiency=0,unlocked=False),
                "ethical_practice":SkillState(skill_id="ethical_practice",proficiency=0,unlocked=False),
            },
            relationship=RelationshipState(),
        )

    @staticmethod
    def _player_summary(player: PlayerState) -> PlayerSummary:
        return PlayerSummary(
            player_id=player.player_id,
            display_name=player.display_name,
            revision=player.revision,
        )

    @staticmethod
    def _error(
        code: str,
        *,
        player: PlayerState | None = None,
        player_id: str | None = None,
        case_id: str | None = None,
        session_id: str | None = None,
    ) -> MultiCaseServiceResult:
        return MultiCaseServiceResult(
            ok=False,
            error_code=code,
            message=SAFE_SERVICE_MESSAGES.get(code, SAFE_SERVICE_MESSAGES["internal_error"]),
            player_id=player.player_id if player is not None else player_id,
            case_id=case_id,
            session_id=session_id,
            player_revision=player.revision if player is not None else None,
        )
