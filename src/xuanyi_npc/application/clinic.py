"""Composition-only local clinic application service for ordinary players."""

from dataclasses import dataclass
import re
from threading import Lock
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import ConfigDict, Field

from xuanyi_npc.domain.cooperation import (
    CooperativeTurnResult,
    PendingActionConfirmation,
    PlayerContribution,
    PlayerContributionType,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import CaseActionType
from xuanyi_npc.storage import (
    CooperativeHistoryError,
    CooperativePayloadConflict,
    JsonStateStore,
    SQLiteCooperativeHistoryRepository,
    StateNotFoundError,
)
from xuanyi_npc.agents.context import RequiredContextTooLargeError

from .multicase import (
    CampaignPlayerInput, CampaignRuleSet, CaseCatalog, CreatePlayerInput, ListCasesInput, ListPlayersInput,
    MultiCaseEpisodeService, ResumeEpisodeInput, StartEpisodeInput, SubmitActionInput,
)
from .case_dialogue import CaseDialogueStore, ChatMessage, asks_participant_identity, case_participants, load_guides
from .player_experience import classify_case_message, propose_investigation
from .cooperative_runtime import (
    CooperativePostCommitError,
    CooperativeRuntime,
    CooperativeTurnInput,
)
from .cooperative_context import (
    RequiredCooperativeContextTooLarge,
    build_context_snapshot,
)


_PROCESS_INSTANCE_ID = uuid4().hex
_ACTIVE_OPERATION_LOCK = Lock()
_ACTIVE_OPERATIONS: dict[tuple[str, str, str, str, str], str] = {}
_ORDINARY_OPERATION_LOCK = Lock()
_ORDINARY_OPERATION_RECEIPTS: dict[
    tuple[str, str, str, str, str], tuple[str, object]
] = {}


_CASE_ACTION_VERBS = (
    "检查", "查看", "调查", "观察", "询问", "盘问", "问问", "搜查", "检验",
    "核对", "分析", "追查", "探查", "勘查", "前往", "诊断", "辨证", "治疗", "处置", "执行",
)
_CASE_ACTION_PATTERN = re.compile("|".join(map(re.escape, _CASE_ACTION_VERBS)))
_NEGATED_CASE_ACTION_PATTERN = re.compile(
    rf"(?:不要|别|不用|无需|先别|暂时不|不必).{{0,4}}(?:{'|'.join(map(re.escape, _CASE_ACTION_VERBS))})"
)
_QUESTION_ONLY_ACTION_PATTERN = re.compile(
    rf"(?:为什么|为何|怎么|如何|是否).{{0,10}}(?:{'|'.join(map(re.escape, _CASE_ACTION_VERBS))})"
)


def message_requests_case_action(text: str) -> bool:
    """Return whether natural-language chat explicitly authorizes a case action."""

    compact = "".join(text.split())
    if not compact or not _CASE_ACTION_PATTERN.search(compact):
        return False
    if _NEGATED_CASE_ACTION_PATTERN.search(compact):
        return False
    if _QUESTION_ONLY_ACTION_PATTERN.search(compact) and not re.search(
        r"(?:请|先|再|去|帮我|麻烦|建议|要不|可以|应该)", compact
    ):
        return False
    return True


def _claim_live_operation(key: tuple[str, str, str, str, str], fingerprint: str) -> str:
    with _ACTIVE_OPERATION_LOCK:
        existing = _ACTIVE_OPERATIONS.get(key)
        if existing is not None:
            return "conflict" if existing != fingerprint else "in_progress"
        _ACTIVE_OPERATIONS[key] = fingerprint
        return "claimed"


def _release_live_operation(key: tuple[str, str, str, str, str]) -> None:
    with _ACTIVE_OPERATION_LOCK:
        _ACTIVE_OPERATIONS.pop(key, None)


class ClinicError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class ClinicPlayerSummary(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    player_id: Identifier
    display_name: NonEmptyText


class ClinicCaseView(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    case_id: Identifier
    title: NonEmptyText
    synopsis: NonEmptyText
    status: str
    recommended: bool
    can_start: bool = False
    active_session_id: Identifier | None = None


class ClinicView(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    player_summary: ClinicPlayerSummary
    visible_cases: tuple[ClinicCaseView, ...]
    active_case: Identifier | None = None
    recent_public_history: tuple[NonEmptyText, ...]
    pending_operations: tuple[Identifier, ...] = ()


class ClinicActionInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    operation_id: Identifier
    action_type: Literal["investigation", "diagnosis", "treatment"]
    selection_id: Identifier
    evidence_clue_ids: tuple[Identifier, ...] = ()


class ClinicContributionInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    player_id: Identifier
    case_id: Identifier
    session_id: Identifier
    operation_id: Identifier
    text: NonEmptyText
    contribution_type: PlayerContributionType = PlayerContributionType.SUGGESTION
    responds_to_decision_id: Identifier | None = None
    pending_confirmation_id: Identifier | None = None


@dataclass
class ClinicService:
    store: JsonStateStore
    base_catalog: CaseCatalog
    campaign_path: object
    clock: object
    player_id_factory: object | None = None
    session_id_factory: object | None = None
    game_npc_agent: object | None = None
    cooperative_memory_service: object | None = None
    memory_coordinator: object | None = None
    memory_index_service: object | None = None
    memory_mode: str = "disabled"
    reflection_service: object | None = None
    cooperative_history_repository: object | None = None
    cooperative_record_enabled: bool = False
    cooperative_context_v2_enabled: bool = False

    def __post_init__(self) -> None:
        if self.game_npc_agent is None:
            raise ValueError("ClinicService requires an explicit game_npc_agent")
        if self.cooperative_context_v2_enabled and not self.cooperative_record_enabled:
            raise ValueError("cooperative context v2 requires cooperative recording")
        kwargs = {"state_store": self.store, "case_catalog": self.base_catalog,
                  "campaign_rules": CampaignRuleSet.load(self.campaign_path, self.base_catalog),
                  "clock": self.clock, "memory_coordinator": self.memory_coordinator,
                  "memory_index_service": self.memory_index_service,
                  }
        if self.player_id_factory is not None:
            kwargs["player_id_factory"] = self.player_id_factory
        if self.session_id_factory is not None:
            kwargs["session_id_factory"] = self.session_id_factory
        self.base_service = MultiCaseEpisodeService(**kwargs)
        self.case_guides = load_guides()
        self.case_dialogues = CaseDialogueStore(self.store.root)
        self._player_creation_lock = Lock()
        self.cooperative_pending: dict[str, PendingActionConfirmation] = {}
        self._cooperative_pending_lock = Lock()
        if self.cooperative_record_enabled and self.cooperative_history_repository is None:
            self.cooperative_history_repository = SQLiteCooperativeHistoryRepository(
                self.store.root / "cooperative_conversation.sqlite3"
            )

    def create_player(self, display_name: str):
        request = CreatePlayerInput(display_name=display_name)
        normalized_name = request.display_name.casefold()
        with self._player_creation_lock:
            if any(
                player.display_name.casefold() == normalized_name
                for player in self.store.list_players()
            ):
                raise ClinicError(
                    "player_name_exists",
                    "这个玩家名已经有调查档案，请从恢复调查档案中进入。",
                )
            result = None
            for _ in range(8):
                candidate = self.base_service.create_player(request)
                if candidate.ok or candidate.error_code != "id_conflict":
                    result = candidate
                    break
            if result is None:
                raise ClinicError(
                    "player_id_unavailable",
                    "暂时无法生成新的档案编号，请重新点击创建。",
                )
        if not result.ok or result.player_id is None:
            raise ClinicError("player_create_failed", result.message)
        return self.home(result.player_id)

    def list_players(self) -> tuple[ClinicPlayerSummary, ...]:
        result = self.base_service.list_players(ListPlayersInput())
        return tuple(ClinicPlayerSummary(player_id=item.player_id, display_name=item.display_name) for item in result.players)

    def _service(self, player_id: str) -> MultiCaseEpisodeService:
        kwargs = {"state_store": self.store, "case_catalog": self.base_catalog,
                  "campaign_rules": CampaignRuleSet.load(self.campaign_path, self.base_catalog),
                  "clock": self.clock, "memory_coordinator": self.memory_coordinator,
                  "memory_index_service": self.memory_index_service,
                  }
        if self.session_id_factory is not None:
            kwargs["session_id_factory"] = self.session_id_factory
        return MultiCaseEpisodeService(**kwargs)

    def home(self, player_id: str) -> ClinicView:
        try:
            player = self.store.load_player(player_id)
        except StateNotFoundError as exc:
            raise ClinicError("player_not_found", "未找到该玩家。") from exc
        service = self._service(player_id)
        cases = service.list_cases(ListCasesInput(player_id=player_id))
        campaign = service.get_campaign_view(CampaignPlayerInput(player_id=player_id))
        completed = frozenset(item.case_id for item in (campaign.campaign_view.completed_cases if campaign.campaign_view else ()))
        active = next((item.case_id for item in cases.cases if item.play_status.value == "active"), None)
        history = tuple(
            item.public_text for item in (campaign.campaign_view.active_facts if campaign.campaign_view else ())
        )[-3:]
        return ClinicView(
            player_summary=ClinicPlayerSummary(player_id=player_id, display_name=player.display_name),
            visible_cases=tuple(ClinicCaseView(
                case_id=item.case_id,
                title=item.title,
                synopsis=item.synopsis,
                status=item.play_status.value,
                recommended=item.is_recommended_next,
                can_start=item.can_start,
                active_session_id=item.active_session_id,
            ) for item in cases.cases),
            active_case=active,
            recent_public_history=history,
        )

    def start_case(self, player_id: str, case_id: str, *, cooperative: bool = False):
        result = self._service(player_id).start_episode(StartEpisodeInput(player_id=player_id, case_id=case_id))
        if not result.ok:
            raise ClinicError(result.error_code or "case_start_failed", result.message)
        return result

    def case_experience(self, player_id: str, case_id: str, session_id: str):
        resumed=self.resume_case(player_id,case_id,session_id)
        session=self.store.load_case_session(session_id); case=self._service(player_id).case_catalog.get(case_id)
        guide=self.case_guides[case_id]
        performed={x.reference_id for x in session.action_history}
        stages=[]; current=guide.stages[-1]
        for stage in guide.stages:
            done=set(stage.completion_requirement_ids).issubset(performed)
            stages.append((stage,done))
            if not done and current is guide.stages[-1]: current=stage
        dialogue=self.case_dialogues.load(session_id,player_id,case_id)
        if not dialogue.current_target:
            dialogue=dialogue.model_copy(update={"current_target":case.patient.patient_id})
        abilities=()
        return resumed,guide,tuple(stages),current,dialogue,abilities

    def case_chat_message(self,player_id:str,case_id:str,session_id:str,operation_id:str,raw_message:str):
        resumed,guide,stages,current,dialogue,abilities=self.case_experience(player_id,case_id,session_id)
        participants=case_participants(case_id)
        classification=classify_case_message(raw_message,dialogue.current_target,participants)
        recipient=classification.recipient_id or "system";text=classification.message_text
        player_msg=ChatMessage(speaker_id="player",recipient_id=recipient,message_type="player",public_text=text)
        memory_proposal=None
        if classification.intent=="clarification_needed":
            response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text=classification.message)
        elif classification.intent=="off_topic":
            response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text="此事与当前异象关系不明。请围绕受影响者、契物、现场痕迹或炁息说明要查什么。")
            dialogue=dialogue.model_copy(update={"off_track_count":dialogue.off_track_count+1})
        elif classification.intent in {
            "investigation_action", "diagnosis_statement", "treatment_statement",
        }:
            response=ChatMessage(speaker_id="system",recipient_id="player",message_type="system",public_text="案中人物聊天只用于普通人物问答；调查、判断、建议和授权请使用上方“与调查搭档协作”入口。")
        elif classification.intent in {"diagnosis_statement","treatment_statement"}:
            label="辨证" if classification.intent=="diagnosis_statement" else "处置"
            response=ChatMessage(speaker_id="system",recipient_id="player",message_type="system",public_text=f"已识别为{label}陈述。请在“辨证与处置”抽屉中核对系统理解并确认；本条消息没有直接执行。")
        elif classification.intent=="investigation_action":
            case=self._service(player_id).case_catalog.get(case_id)
            proposal=propose_investigation(text,case.investigations)
            if proposal.kind!="investigation":
                response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text=proposal.message)
            else:
                before={x.clue_id for x in resumed.observation.discovered_clues}
                try:self.submit_case_action(ClinicActionInput(player_id=player_id,case_id=case_id,session_id=session_id,operation_id=operation_id,action_type="investigation",selection_id=proposal.selection_id))
                except ClinicError as exc:
                    response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text=str(exc))
                    if exc.code in {"skill_locked","insufficient_skill"}:
                        interim=dialogue.model_copy(update={"recent_messages":(*dialogue.recent_messages,player_msg,response)[-16:],"revision":dialogue.revision+1})
                        self.case_dialogues.save(interim);return response,self.case_dialogues.load(session_id,player_id,case_id)
                else:
                    after=self.resume_case(player_id,case_id,session_id).observation
                    revealed=[x.description for x in after.discovered_clues if x.clue_id not in before]
                    response=ChatMessage(speaker_id="system",recipient_id="player",message_type="clue",public_text=("调查结果："+"；".join(revealed)) if revealed else "这项调查先前已经完成，没有新增线索。")
                    dialogue=dialogue.model_copy(update={"off_track_count":0})
        else:
            case=self._service(player_id).case_catalog.get(case_id)
            participant=next(x for x in participants if x.participant_id==recipient)
            targeted=tuple(x for x in case.investigations if x.target_id==recipient)
            global_proposal=propose_investigation(text,case.investigations)
            if asks_participant_identity(text):
                response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="known_complete_answer",public_text=participant.public_intro)
                dialogue=dialogue.model_copy(update={"off_track_count":0})
            elif any(word in text for word in ("正确辨证","正确处置","直接告诉我真相","替我隐瞒")):
                response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="refuses_to_answer",public_text="这不是我能替你断定或隐瞒的事。你若要查案，请问我亲眼所见的经过。")
            elif not targeted:
                response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="understood_but_unknown",public_text="这件事我没有看清，你可以问某位可能知情的人。")
            else:
                generic=set("我你他她它的是了和与在问询请想要查核对什么如何情况")
                topical=max((len((set(text)-generic)&(set(x.public_description)-generic)) for x in targeted),default=0)
                proposal=propose_investigation(text,targeted) if topical>=2 else None
                if proposal is None or proposal.kind!="investigation":
                    if global_proposal.kind=="investigation":
                        response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="understood_but_unknown",public_text="这件事我没有看清，你可以问某位可能知情的人。")
                    else:
                        response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="clarification_needed",public_text="我没听明白你具体想核对什么。请说明事件、时间或你要确认的事实。")
                        dialogue=dialogue.model_copy(update={"off_track_count":dialogue.off_track_count+1})
                else:
                    before={x.clue_id for x in resumed.observation.discovered_clues}
                    if proposal.selection_id in {x.reference_id for x in self.store.load_case_session(session_id).action_history}:
                        response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type="known_complete_answer",public_text="这部分情况先前已经核对过，没有新增事实。")
                    else:
                        try:self.submit_case_action(ClinicActionInput(player_id=player_id,case_id=case_id,session_id=session_id,operation_id=operation_id,action_type="investigation",selection_id=proposal.selection_id))
                        except ClinicError as exc:
                            if exc.code in {"skill_locked","insufficient_skill"}:
                                response=ChatMessage(speaker_id="system",recipient_id="player",message_type="rejection",public_text=str(exc))
                                interim=dialogue.model_copy(update={"recent_messages":(*dialogue.recent_messages,player_msg,response)[-16:],"revision":dialogue.revision+1})
                                self.case_dialogues.save(interim);return response,self.case_dialogues.load(session_id,player_id,case_id)
                            raise
                        after=self.resume_case(player_id,case_id,session_id).observation
                        revealed=[x.description for x in after.discovered_clues if x.clue_id not in before]
                        answer_type="known_complete_answer" if revealed else "known_partial_answer"
                        response=ChatMessage(speaker_id=recipient,recipient_id="player",message_type="case_character",response_type=answer_type,public_text=("据我所知，"+"；".join(revealed)) if revealed else "我只记得这些，暂时想不起更多细节。")
                    dialogue=dialogue.model_copy(update={"off_track_count":0})
            dialogue=dialogue.model_copy(update={"current_target":recipient})
        updated=dialogue.model_copy(update={"recent_messages":(*dialogue.recent_messages,player_msg,response)[-16:],"revision":dialogue.revision+1})
        self.case_dialogues.save(updated)
        return response,self.case_dialogues.load(session_id,player_id,case_id)

    def resume_case(self, player_id: str, case_id: str, session_id: str):
        result = self._service(player_id).resume_episode(ResumeEpisodeInput(player_id=player_id, case_id=case_id, session_id=session_id))
        if not result.ok:
            raise ClinicError(result.error_code or "case_resume_failed", result.message)
        return result

    def cooperative_turn_history(
        self,
        player_id: str,
        case_id: str,
        session_id: str,
        *,
        limit: int = 16,
    ) -> tuple[tuple[PlayerContribution, CooperativeTurnResult], ...]:
        """Load completed, player-visible cooperative turns for a case page."""
        if not self.cooperative_record_enabled or self.cooperative_history_repository is None:
            return ()
        session = self.store.load_case_session(session_id)
        if (session.player_id, session.case_id) != (player_id, case_id):
            raise ClinicError(
                "cooperative_scope_ownership_mismatch",
                "该协作记录不属于当前玩家或案件。",
            )
        try:
            records = self.cooperative_history_repository.completed_for_session(
                player_id, case_id, session_id, limit=limit
            )
        except CooperativeHistoryError as exc:
            raise ClinicError("cooperative_history_unavailable", str(exc)) from exc
        turns: list[tuple[PlayerContribution, CooperativeTurnResult]] = []
        for record in records:
            if not record.contribution_json or not record.result_json:
                continue
            try:
                contribution = PlayerContribution.model_validate_json(
                    record.contribution_json
                )
                result = CooperativeTurnResult.model_validate_json(record.result_json)
            except ValueError:
                continue
            turns.append((contribution, result))
        return tuple(turns)

    def submit_player_contribution(self, request: ClinicContributionInput) -> CooperativeTurnResult:
        if self.cooperative_record_enabled:
            repository = self.cooperative_history_repository
            stable_request = {
                "player_id": request.player_id,
                "case_id": request.case_id,
                "session_id": request.session_id,
                "operation_id": request.operation_id,
                "text": request.text,
                "contribution_type": request.contribution_type.value,
                "responds_to_decision_id": request.responds_to_decision_id,
                "pending_confirmation_id": request.pending_confirmation_id,
            }
            fingerprint = SQLiteCooperativeHistoryRepository.fingerprint(stable_request)
            database_identity = str(getattr(repository, "path", id(repository)))
            operation_key = (
                database_identity,
                request.player_id,
                request.case_id,
                request.session_id,
                request.operation_id,
            )
            claim = _claim_live_operation(operation_key, fingerprint)
            if claim == "in_progress":
                raise ClinicError(
                    "operation_in_progress", "同一协作操作仍在处理中，请稍后重试。"
                )
            if claim == "conflict":
                raise ClinicError(
                    "operation_payload_conflict",
                    "operation_id 已用于不同的协作请求。",
                )
            try:
                with self.store.session_write_lock(request.session_id):
                    return self._submit_player_contribution(
                        request, operation_claimed=True
                    )
            except Exception:
                _release_live_operation(operation_key)
                raise
        with self.store.session_write_lock(request.session_id):
            return self._submit_player_contribution(request)

    def _submit_player_contribution(
        self,
        request: ClinicContributionInput,
        *,
        operation_claimed: bool = False,
    ) -> CooperativeTurnResult:
        session = self.store.load_case_session(request.session_id)
        self.store.load_player(request.player_id)
        if (session.player_id, session.case_id) != (request.player_id, request.case_id):
            raise ClinicError(
                "cooperative_scope_ownership_mismatch",
                "该协作操作不属于当前玩家、病例或会话。",
            )
        def current_pending(*, require_current_revision: bool = False):
            if request.pending_confirmation_id is None:
                return None
            with self._cooperative_pending_lock:
                value = self.cooperative_pending.get(request.pending_confirmation_id)
            if value is None:
                raise ClinicError(
                    "confirmation_unavailable",
                    "该协商请求已失效，请依据最新病例状态重新讨论。",
                )
            if (value.player_id, value.case_id, value.session_id) != (
                request.player_id, request.case_id, request.session_id
            ):
                raise ClinicError(
                    "confirmation_ownership_mismatch",
                    "该协商请求不属于当前玩家或病例。",
                )
            if require_current_revision and value.case_revision != session.revision:
                raise ClinicError(
                    "confirmation_unavailable",
                    "该协商请求已因病例状态变化而失效，请重新讨论。",
                )
            return value
        pending = None
        if not self.cooperative_record_enabled:
            # Preserve the pre-CE-2A validation/clock ordering when recording
            # is disabled.
            pending = current_pending()
        contribution = PlayerContribution(
            contribution_id=request.operation_id,
            player_id=request.player_id,
            case_id=request.case_id,
            session_id=request.session_id,
            contribution_type=request.contribution_type,
            public_text=request.text,
            responds_to_decision_id=request.responds_to_decision_id,
            created_at=self.clock.now(),
        )
        allow_world_action = (
            request.contribution_type is not PlayerContributionType.GENERAL_MESSAGE
            or message_requests_case_action(request.text)
        )
        if not self.cooperative_record_enabled:
            runtime = CooperativeRuntime(
                service=self._service(request.player_id),
                agent=self.game_npc_agent,
                memory_service=self.cooperative_memory_service,
                reflection_service=self.reflection_service,
            )
            result = runtime.handle(CooperativeTurnInput(
                contribution=contribution,
                pending_action=pending,
                allow_world_action=allow_world_action,
            ))
            with self._cooperative_pending_lock:
                if pending is not None:
                    self.cooperative_pending.pop(pending.confirmation_id, None)
                if result.pending_action is not None:
                    self.cooperative_pending[result.pending_action.confirmation_id] = result.pending_action
            return result

        repository = self.cooperative_history_repository
        assert isinstance(repository, SQLiteCooperativeHistoryRepository) or all(
            callable(getattr(repository, name, None))
            for name in ("begin", "mark_prepared", "complete")
        )
        stable_request = {
            "player_id": request.player_id,
            "case_id": request.case_id,
            "session_id": request.session_id,
            "operation_id": request.operation_id,
            "text": request.text,
            "contribution_type": request.contribution_type.value,
            "responds_to_decision_id": request.responds_to_decision_id,
            "pending_confirmation_id": request.pending_confirmation_id,
        }
        fingerprint = SQLiteCooperativeHistoryRepository.fingerprint(stable_request)
        database_identity = str(getattr(repository, "path", id(repository)))
        operation_key = (
            database_identity, request.player_id, request.case_id,
            request.session_id, request.operation_id,
        )
        if not operation_claimed:
            claim = _claim_live_operation(operation_key, fingerprint)
            if claim == "in_progress":
                raise ClinicError("operation_in_progress", "同一协作操作仍在处理中，请稍后重试。")
            if claim == "conflict":
                raise ClinicError("operation_payload_conflict", "operation_id 已用于不同的协作请求。")

        record = None
        prepared = False
        try:
            try:
                record, created = repository.begin(
                    player_id=request.player_id,
                    case_id=request.case_id,
                    session_id=request.session_id,
                    operation_id=request.operation_id,
                    stable_request=stable_request,
                    contribution_json=contribution.model_dump_json(),
                    owner_process_id=_PROCESS_INSTANCE_ID,
                )
            except CooperativePayloadConflict as exc:
                raise ClinicError("operation_payload_conflict", str(exc)) from exc
            except CooperativeHistoryError as exc:
                raise ClinicError("cooperative_history_unavailable", str(exc)) from exc

            if not created:
                if record.lifecycle == "completed" and record.result_json:
                    stored = CooperativeTurnResult.model_validate_json(record.result_json)
                    current_pending = None
                    if stored.pending_action is not None:
                        with self._cooperative_pending_lock:
                            live = self.cooperative_pending.get(stored.pending_action.confirmation_id)
                        if (
                            live is not None
                            and live == stored.pending_action
                            and live.case_revision == session.revision
                        ):
                            current_pending = live
                    return stored.model_copy(update={"pending_action": current_pending})
                if record.lifecycle in ("started", "prepared"):
                    repository.require_recovery(record, "interrupted_operation_uncertain")
                    raise ClinicError(
                        "operation_recovery_uncertain",
                        "发现重启后遗留的未完成操作；无法确认执行结果，未自动重放。",
                    )
                if record.lifecycle == "recovery_required":
                    if (record.failure_code or "").startswith("committed_"):
                        raise ClinicError(
                            "operation_committed_followup_incomplete",
                            "该操作已提交世界状态，但后续处理未完成；同 operation 不会重放工具。",
                        )
                    raise ClinicError(
                        "operation_recovery_uncertain",
                        "该操作结果无法安全确认，未自动重放模型或工具。",
                    )
                raise ClinicError(
                    "operation_previously_failed",
                    "该 operation_id 的协作操作此前已在公开回复前失败。",
                )

            # Only a genuinely new operation needs a currently valid pending.
            # Completed replay and other existing lifecycle states above never
            # use historical results as authorization.
            try:
                pending = current_pending(require_current_revision=True)
            except ClinicError as exc:
                try:
                    repository.fail_before_reply(record, exc.code)
                except CooperativeHistoryError as storage_exc:
                    raise ClinicError(
                        "cooperative_history_unavailable", str(storage_exc)
                    ) from storage_exc
                raise

            snapshot = None
            history_messages = ()
            if self.cooperative_context_v2_enabled:
                with self._cooperative_pending_lock:
                    pending_snapshot = tuple(self.cooperative_pending.values())
                try:
                    snapshot, history_messages = build_context_snapshot(
                        repository,
                        record,
                        pending_snapshot,
                        contribution=contribution,
                        case_revision=session.revision,
                        responds_to_confirmation_id=request.pending_confirmation_id,
                    )
                except RequiredCooperativeContextTooLarge as exc:
                    repository.fail_before_reply(record, "required_context_too_large")
                    raise ClinicError("required_context_too_large", str(exc)) from exc

            def prepared_hook(decision) -> None:
                nonlocal prepared
                repository.mark_prepared(record, decision.model_dump_json())
                prepared = True

            runtime = CooperativeRuntime(
                service=self._service(request.player_id),
                agent=self.game_npc_agent,
                memory_service=self.cooperative_memory_service,
                reflection_service=self.reflection_service,
                cooperative_context=snapshot,
                cooperative_history_messages=history_messages,
                decision_prepared_hook=prepared_hook,
            )
            try:
                result = runtime.handle(
                    CooperativeTurnInput(
                        contribution=contribution,
                        pending_action=pending,
                        allow_world_action=allow_world_action,
                    )
                )
            except Exception as exc:
                if isinstance(exc, RequiredContextTooLargeError):
                    try:
                        repository.fail_before_reply(record, "required_context_too_large")
                    except CooperativeHistoryError:
                        pass
                    raise ClinicError("required_context_too_large", str(exc)) from exc
                if isinstance(exc, CooperativePostCommitError):
                    try:
                        repository.require_recovery(
                            record, f"committed_{exc.stage}_failed"
                        )
                    except CooperativeHistoryError:
                        pass
                    raise ClinicError(
                        "operation_committed_followup_incomplete",
                        "世界状态已提交，但协作后续处理未完成；同 operation 不会重放工具。",
                    ) from exc
                try:
                    repository.require_recovery(record, "runtime_result_uncertain")
                except CooperativeHistoryError:
                    pass
                if isinstance(exc, ClinicError):
                    raise
                raise ClinicError(
                    "operation_recovery_uncertain",
                    "协作操作未能完成，且无法安全断言世界状态未改变；同 operation 不会自动重放。",
                ) from exc
            if not prepared:
                # Early safe-return branches cannot execute a tool. Record their
                # final public decision before marking the turn completed.
                repository.mark_prepared(record, result.decision.model_dump_json())
            with self._cooperative_pending_lock:
                if pending is not None:
                    self.cooperative_pending.pop(pending.confirmation_id, None)
            try:
                repository.complete(record, result.model_dump_json())
            except CooperativeHistoryError as exc:
                try:
                    repository.require_recovery(record, "completion_write_failed")
                except CooperativeHistoryError:
                    pass
                raise ClinicError(
                    "operation_recovery_uncertain",
                    "世界状态可能已经提交，但协作结果记录失败；同 operation 不会自动重放。",
                ) from exc
            with self._cooperative_pending_lock:
                if result.pending_action is not None:
                    self.cooperative_pending[result.pending_action.confirmation_id] = result.pending_action
            return result
        finally:
            _release_live_operation(operation_key)

    def submit_case_action(self, request: ClinicActionInput):
        with self.store.session_write_lock(request.session_id):
            return self._submit_case_action(request)

    def _submit_case_action(self, request: ClinicActionInput):
        from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
        service = self._service(request.player_id)
        case = service.case_catalog.get(request.case_id)
        if case is None:
            raise ClinicError("case_not_found", "病例不存在。")
        operation_key = (
            str(self.store.root.resolve()),
            request.player_id,
            request.case_id,
            request.session_id,
            request.operation_id,
        )
        fingerprint = request.model_dump_json()
        with _ORDINARY_OPERATION_LOCK:
            stored = _ORDINARY_OPERATION_RECEIPTS.get(operation_key)
        if stored is not None:
            stored_fingerprint, receipt = stored
            if stored_fingerprint != fingerprint:
                raise ClinicError(
                    "operation_payload_conflict",
                    "operation_id 已用于不同的普通行动请求。",
                )
        else:
            receipt = None
        if request.action_type == "investigation":
            investigation = next((item for item in case.investigations if item.investigation_id == request.selection_id), None)
            if investigation is None:
                raise ClinicError("investigation_not_available", "该调查当前不可用。")
            tool = {CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT, CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT, CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT, CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI, CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION}[investigation.action_type]
            arguments = {"investigation_id": request.selection_id}
        elif request.action_type == "diagnosis":
            tool, arguments = ToolName.SUBMIT_DIAGNOSIS, {"diagnosis_id": request.selection_id, "evidence_clue_ids": list(request.evidence_clue_ids)}
        else:
            tool, arguments = ToolName.EXECUTE_TREATMENT, {"treatment_id": request.selection_id}
        action = AgentAction(action_id=request.operation_id, action_type=AgentActionType.USE_TOOL, dialogue="玩家通过异案页面选择了公开行动。", tool_call=ToolCallRequest(name=tool, arguments=arguments), confidence=1.0)
        if receipt is None:
            receipt = service.submit_action_with_receipt(SubmitActionInput(
                player_id=request.player_id,
                case_id=request.case_id,
                session_id=request.session_id,
                action=action,
            ))
            with _ORDINARY_OPERATION_LOCK:
                _ORDINARY_OPERATION_RECEIPTS[operation_key] = (fingerprint, receipt)
        result = receipt.result
        if receipt.world_commit_status == "unknown":
            raise ClinicError(
                "world_commit_uncertain",
                "无法确认世界状态是否已提交；同一进程内不会自动重放该 operation。",
            )
        if not result.ok:
            raise ClinicError(result.error_code or "case_action_rejected", result.message)
        return result
