"""R2 orchestration for one fixed, recoverable mentor teaching loop."""

from datetime import datetime
from typing import Protocol
from uuid import uuid4

from pydantic import ConfigDict

from xuanyi_npc.agents.mentor import (
    MentorAgentInput,
    MentorAgentInterface,
    RelationshipPublicView,
)
from xuanyi_npc.agents.mentor_contract import MentorActionContractError, validate_mentor_action
from xuanyi_npc.application.assessment import AssessmentBuilder, AssessmentSourceError
from xuanyi_npc.application.multicase import (
    CaseCatalog,
    MultiCaseEpisodeService,
    PublicEpisodeResult,
)
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import CaseSessionStatus, INVESTIGATION_ACTIONS
from xuanyi_npc.domain.mentor import (
    LessonDefinition,
    MentorAction,
    MentorActionType,
    MentorInteractionPhase,
    MentorProfile,
)
from xuanyi_npc.domain.teaching import (
    AssessmentAttached,
    CaseCompletionObserved,
    HintDelivered,
    LessonAssigned,
    MentorBriefingIssued,
    MentorReviewIssued,
    PlayerReflectionSubmitted,
    ReflectionRequested,
    ReflectionStatus,
    TeachingEvent,
    TeachingEventReplayer,
    TeachingPhase,
    TeachingSessionCompleted,
    TeachingSessionState,
)
from xuanyi_npc.resources.runtime import (
    MENTOR_PROFILE_RESOURCE_NAME,
    R2_LESSON_RESOURCE_NAME,
    read_runtime_text,
)
from xuanyi_npc.storage import JsonStateStore, StateNotFoundError, StorageError


class TeachingSessionIdFactory(Protocol):
    def new_teaching_session_id(self) -> str: ...


class UUIDTeachingSessionIdFactory:
    def new_teaching_session_id(self) -> str:
        return f"teaching_{uuid4().hex}"


class TeachingRequest(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    player_id: Identifier
    teaching_session_id: Identifier


class CreateTeachingSessionInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    player_id: Identifier
    case_session_id: Identifier


class SubmitReflectionInput(TeachingRequest):
    reflection_text: NonEmptyText


class TeachingServiceResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    ok: bool
    message: NonEmptyText
    error_code: Identifier | None = None
    state: TeachingSessionState | None = None
    mentor_action: MentorAction | None = None


class MentorTeachingService:
    def __init__(
        self,
        *,
        case_service: MultiCaseEpisodeService,
        mentor_agent: MentorAgentInterface,
        id_factory: TeachingSessionIdFactory | None = None,
    ) -> None:
        self.case_service = case_service
        self.store: JsonStateStore = case_service.state_store
        self.mentor_agent = mentor_agent
        self.id_factory = id_factory or UUIDTeachingSessionIdFactory()
        self.profile = MentorProfile.model_validate_json(
            read_runtime_text(f"mentor/{MENTOR_PROFILE_RESOURCE_NAME}")
        )
        self.lesson = LessonDefinition.model_validate_json(
            read_runtime_text(f"curriculum/{R2_LESSON_RESOURCE_NAME}")
        )
        self.assessment_builder = AssessmentBuilder()

    def create(self, request: CreateTeachingSessionInput) -> TeachingServiceResult:
        try:
            case_session = self.store.load_case_session(request.case_session_id)
            player = self.store.load_player(request.player_id)
            apprenticeship = self.store.load_apprenticeship(request.player_id)
            if case_session.player_id != request.player_id:
                return self._error("teaching_access_denied", "不能访问其他玩家的教学会话。")
            if case_session.case_id != self.lesson.assigned_case_id:
                return self._error("lesson_case_not_allowed", "R2 教学只开放旧纸伞病例。")
            duplicates = tuple(
                item for item in self.store.list_teaching_sessions()
                if item.case_session_id == case_session.session_id
            )
            if duplicates:
                state = duplicates[0]
                if state.player_id != request.player_id:
                    return self._error("teaching_access_denied", "不能访问其他玩家的教学会话。")
                return TeachingServiceResult(ok=True, message="教学会话已经存在。", state=state)
            now = self.case_service.clock.now()
            teaching_id = self.id_factory.new_teaching_session_id()
            assigned = LessonAssigned(
                sequence=1,
                teaching_session_id=teaching_id,
                occurred_at=now,
                player_id=request.player_id,
                mentor_id=self.profile.mentor_id,
                lesson_id=self.lesson.lesson_id,
                case_session_id=case_session.session_id,
            )
            state = TeachingEventReplayer().replay((assigned,))
            agent_input = self._input(
                player=player,
                apprenticeship=apprenticeship,
                phase=MentorInteractionPhase.LESSON_START,
                allowed=(MentorActionType.SPEAK,),
            )
            action = self.mentor_agent.decide(agent_input).action
            try:
                validate_mentor_action(agent_input, action)
            except MentorActionContractError:
                action = MentorAction(
                    action_type=MentorActionType.SPEAK,
                    message="先依次核对可见证据，再下判断。",
                )
            state = self._append(
                state,
                MentorBriefingIssued(
                    sequence=2,
                    teaching_session_id=teaching_id,
                    occurred_at=now,
                    action=action,
                ),
            )
            self.store.save_teaching_session(state)
            return TeachingServiceResult(
                ok=True, message="导师已布置固定课程。", state=state, mentor_action=action
            )
        except (StateNotFoundError, StorageError):
            return self._error("teaching_state_unavailable", "教学会话暂不可用。")

    def resume(self, request: TeachingRequest) -> TeachingServiceResult:
        state = self._owned(request)
        if isinstance(state, TeachingServiceResult):
            return state
        return TeachingServiceResult(ok=True, message="教学会话已恢复。", state=state)

    def request_reflection(self, request: TeachingRequest) -> TeachingServiceResult:
        state = self._owned(request)
        if isinstance(state, TeachingServiceResult):
            return state
        if state.phase is not TeachingPhase.ACTIVE:
            return self._with_state(False, "reflection_not_available", "当前阶段不能请求反思。", state)
        if state.reflection_status is not ReflectionStatus.NOT_REQUESTED:
            return self._with_state(False, "reflection_already_requested", "本课反思已经请求过。", state)
        case_session = self.store.load_case_session(state.case_session_id)
        categories = {
            record.action_type for record in case_session.action_history
            if record.action_type in INVESTIGATION_ACTIONS
        }
        if len(categories) < self.lesson.reflection_checkpoint.minimum_investigation_categories:
            return self._with_state(False, "reflection_checkpoint_not_reached", "完成至少三类调查后再反思。", state)
        agent_input = self._active_input(state, (MentorActionType.ASK_REFLECTION,))
        action = self.mentor_agent.decide(agent_input).action
        try:
            validate_mentor_action(agent_input, action)
        except MentorActionContractError:
            action = MentorAction(
                action_type=MentorActionType.ASK_REFLECTION,
                message=self.lesson.reflection_checkpoint.question,
            )
        updated = self._append(
            state,
            ReflectionRequested(
                sequence=state.revision + 1,
                teaching_session_id=state.teaching_session_id,
                occurred_at=self.case_service.clock.now(),
                action=action,
            ),
        )
        return self._save(updated, "导师已提出一次反思问题。", action)

    def submit_reflection(self, request: SubmitReflectionInput) -> TeachingServiceResult:
        state = self._owned(request)
        if isinstance(state, TeachingServiceResult):
            return state
        if state.reflection_status is not ReflectionStatus.REQUESTED:
            return self._with_state(False, "reflection_not_requested", "当前没有待回答的反思问题。", state)
        updated = self._append(
            state,
            PlayerReflectionSubmitted(
                sequence=state.revision + 1,
                teaching_session_id=state.teaching_session_id,
                occurred_at=self.case_service.clock.now(),
                display_text=request.reflection_text,
            ),
        )
        return self._save(updated, "反思已作为教学显示记录保存。")

    def request_hint(self, request: TeachingRequest) -> TeachingServiceResult:
        state = self._owned(request)
        if isinstance(state, TeachingServiceResult):
            return state
        if state.phase is not TeachingPhase.ACTIVE:
            return self._with_state(False, "hint_not_available", "当前阶段不能请求提示。", state)
        cards = tuple(
            card for card in self.lesson.public_hint_cards
            if card.hint_id not in state.used_hint_ids
        )
        if not cards:
            return self._with_state(False, "hint_limit_reached", "本课两次提示已经用完。", state)
        agent_input = self._active_input(state, (MentorActionType.GIVE_HINT,), cards=cards)
        decision = self.mentor_agent.decide(agent_input)
        action = decision.action
        try:
            validate_mentor_action(agent_input, action)
        except MentorActionContractError:
            return self._with_state(False, "mentor_action_rejected", "导师提示未通过公开契约。", state)
        if action.action_type is not MentorActionType.GIVE_HINT or decision.used_fallback:
            return self._with_state(False, "mentor_action_rejected", "导师提示未通过公开契约。", state)
        card = next(item for item in cards if item.hint_id == action.hint_id)
        trusted_action = action.model_copy(update={"message": card.text})
        updated = self._append(
            state,
            HintDelivered(
                sequence=state.revision + 1,
                teaching_session_id=state.teaching_session_id,
                occurred_at=self.case_service.clock.now(),
                hint_id=card.hint_id,
                action=trusted_action,
            ),
        )
        return self._save(updated, "导师已提供一张公开提示卡。", trusted_action)

    def observe_case_completion(self, request: TeachingRequest) -> TeachingServiceResult:
        state = self._owned(request)
        if isinstance(state, TeachingServiceResult):
            return state
        if state.phase is TeachingPhase.COMPLETED:
            return TeachingServiceResult(ok=True, message="教学会话已经完成。", state=state)
        try:
            case_session = self.store.load_case_session(state.case_session_id)
            if case_session.status is not CaseSessionStatus.COMPLETED:
                return self._with_state(False, "case_not_completed", "病例尚未完成，不能生成师评。", state)
            apprenticeship = self.store.load_apprenticeship(state.player_id)
            if case_session.session_id not in apprenticeship.completed_source_sessions:
                return self._with_state(False, "apprenticeship_projection_pending", "R1 成长尚待协调。", state)
            if state.phase is TeachingPhase.ACTIVE:
                state = self._append(
                    state,
                    CaseCompletionObserved(
                        sequence=state.revision + 1,
                        teaching_session_id=state.teaching_session_id,
                        occurred_at=self.case_service.clock.now(),
                        case_revision=case_session.revision,
                    ),
                )
                try:
                    self.store.save_teaching_session(state)
                except StorageError:
                    return self._with_state(False, "teaching_state_pending", "病例已完成，教学状态尚待协调。", state)
            if state.assessment is None:
                report = self.assessment_builder.build(
                    session=case_session,
                    case=self.case_service.case_catalog.get(case_session.case_id),
                    apprenticeship=apprenticeship,
                    lesson=self.lesson,
                    used_hint_ids=state.used_hint_ids,
                )
                state = self._append(
                    state,
                    AssessmentAttached(
                        sequence=state.revision + 1,
                        teaching_session_id=state.teaching_session_id,
                        occurred_at=self.case_service.clock.now(),
                        assessment=report,
                    ),
                )
                try:
                    self.store.save_teaching_session(state)
                except StorageError:
                    return self._with_state(False, "teaching_assessment_pending", "结构化师评尚待保存。", state)
            if state.phase is TeachingPhase.CASE_COMPLETED:
                review_input = self._review_input(state)
                decision = self.mentor_agent.decide(review_input)
                review_action = decision.action
                try:
                    validate_mentor_action(review_input, review_action)
                except MentorActionContractError:
                    review_action = MentorAction(
                        action_type=MentorActionType.REVIEW_PERFORMANCE,
                        message="本次导师讲评暂不可生成，请查看结构化评测结果。",
                    )
                    decision = decision.model_copy(update={"used_fallback": True})
                next_input = review_input.model_copy(
                    update={"allowed_mentor_actions": (MentorActionType.RECOMMEND_FIXED_NEXT_STEP,)}
                )
                next_action = self.mentor_agent.decide(next_input).action
                try:
                    validate_mentor_action(next_input, next_action)
                except MentorActionContractError:
                    next_action = MentorAction(
                        action_type=MentorActionType.RECOMMEND_FIXED_NEXT_STEP,
                        message=self.lesson.fixed_next_step,
                    )
                next_action = next_action.model_copy(update={"message": self.lesson.fixed_next_step})
                state = self._append(
                    state,
                    MentorReviewIssued(
                        sequence=state.revision + 1,
                        teaching_session_id=state.teaching_session_id,
                        occurred_at=self.case_service.clock.now(),
                        action=review_action,
                        fixed_next_step_action=next_action,
                        used_fallback=decision.used_fallback,
                    ),
                )
                self.store.save_teaching_session(state)
            if state.phase is TeachingPhase.REVIEWED:
                state = self._append(
                    state,
                    TeachingSessionCompleted(
                        sequence=state.revision + 1,
                        teaching_session_id=state.teaching_session_id,
                        occurred_at=self.case_service.clock.now(),
                    ),
                )
                self.store.save_teaching_session(state)
            return TeachingServiceResult(
                ok=True,
                message="病例、R1 成长、结构化师评与导师回顾已形成闭环。",
                state=state,
                mentor_action=state.mentor_review,
            )
        except AssessmentSourceError:
            return self._with_state(False, "apprenticeship_projection_pending", "R1 成长尚待协调。", state)
        except StorageError:
            return self._with_state(False, "teaching_state_pending", "教学状态尚待协调。", state)

    reconcile = observe_case_completion

    def _owned(self, request: TeachingRequest) -> TeachingSessionState | TeachingServiceResult:
        try:
            state = self.store.load_teaching_session(request.teaching_session_id)
        except (StateNotFoundError, StorageError):
            return self._error("teaching_state_unavailable", "教学会话不存在或不可用。")
        if state.player_id != request.player_id:
            return self._error("teaching_access_denied", "不能访问其他玩家的教学会话。")
        return state

    def _active_input(self, state, allowed, cards=()):
        player = self.store.load_player(state.player_id)
        apprenticeship = self.store.load_apprenticeship(state.player_id)
        case_session = self.store.load_case_session(state.case_session_id)
        case = self.case_service.case_catalog.get(case_session.case_id)
        return self._input(
            player=player,
            apprenticeship=apprenticeship,
            phase=MentorInteractionPhase.INVESTIGATION,
            allowed=allowed,
            case_view=self.case_service.context_filter.case_observation(case, player, case_session),
            cards=cards,
        )

    def _review_input(self, state):
        player = self.store.load_player(state.player_id)
        apprenticeship = self.store.load_apprenticeship(state.player_id)
        case_session = self.store.load_case_session(state.case_session_id)
        return self._input(
            player=player,
            apprenticeship=apprenticeship,
            phase=MentorInteractionPhase.CASE_COMPLETE,
            allowed=(MentorActionType.REVIEW_PERFORMANCE,),
            public_result=PublicEpisodeResult(
                status=case_session.status,
                outcome=case_session.outcome,
                score=case_session.score,
                submitted_diagnosis_id=case_session.submitted_diagnosis_id,
                selected_treatment_id=case_session.selected_treatment_id,
            ),
            assessment=state.assessment,
        )

    def _input(self, *, player, apprenticeship, phase, allowed, case_view=None, cards=(), public_result=None, assessment=None):
        view = self.case_service.progression_policy.view(apprenticeship)
        return MentorAgentInput(
            mentor_public_profile=self.profile.public_view(),
            interaction_phase=phase,
            lesson_public_view=self.lesson,
            apprenticeship_public_view=view,
            relationship_public_view=RelationshipPublicView(
                affinity=view.affinity, trust=view.trust, recognition=view.recognition
            ),
            public_case_view=case_view,
            latest_public_case_result=public_result,
            allowed_hint_cards=cards,
            assessment_public_view=assessment,
            allowed_mentor_actions=allowed,
        )

    def _append(self, state: TeachingSessionState, event: TeachingEvent) -> TeachingSessionState:
        return TeachingEventReplayer().replay((*state.events, event))

    def _save(self, state, message, action=None):
        try:
            self.store.save_teaching_session(state)
        except StorageError:
            return self._with_state(False, "teaching_state_pending", "教学状态尚待协调。", state)
        return TeachingServiceResult(ok=True, message=message, state=state, mentor_action=action)

    @staticmethod
    def _error(code, message):
        return TeachingServiceResult(ok=False, error_code=code, message=message)

    @staticmethod
    def _with_state(ok, code, message, state):
        return TeachingServiceResult(ok=ok, error_code=None if ok else code, message=message, state=state)
