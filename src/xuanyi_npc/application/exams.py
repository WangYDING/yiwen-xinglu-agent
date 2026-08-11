"""Deterministic formal-exam application service."""

import hashlib
from dataclasses import dataclass
from datetime import datetime

from pydantic import ConfigDict

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.exams import (
    ExamAnswerRecorded,
    ExamDefinition,
    ExamEvent,
    ExamEventReplayer,
    ExamFailed,
    ExamPassed,
    ExamResult,
    ExamRetakeUnlocked,
    ExamScored,
    ExamSessionState,
    ExamStarted,
    ExamSubmitted,
)
from xuanyi_npc.resources.runtime import read_runtime_text
from xuanyi_npc.storage.json_store import JsonStateStore
from xuanyi_npc.domain.teaching_plan import RemediationAttempted

from .permissions import PermissionCoordinator


class ExamServiceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PublicExamQuestion(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    question_id: Identifier
    section: str
    public_scenario: NonEmptyText
    options: tuple[dict[str, str], ...]
    score: int


class PublicExamResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    exam_id: Identifier
    attempt_id: Identifier
    total_score: int
    section_scores: dict[str, int]
    critical_failure: bool
    passed: bool
    improvement_areas: tuple[Identifier, ...]
    required_remediation_ids: tuple[Identifier, ...]
    submitted_at: datetime


class ExamServiceResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ok: bool
    code: Identifier
    message: NonEmptyText
    state: ExamSessionState | None = None
    progression_pending: bool = False


@dataclass(frozen=True)
class ExamService:
    store: JsonStateStore
    permission_coordinator: PermissionCoordinator
    clock: object

    def __post_init__(self) -> None:
        definition = ExamDefinition.model_validate_json(
            read_runtime_text("exams/foundational_xuanyi_exam_v1.json")
        )
        object.__setattr__(self, "definition", definition)
        object.__setattr__(self, "replayer", ExamEventReplayer())

    def public_questions(self, player_id: str) -> tuple[PublicExamQuestion, ...]:
        state = self.permission_coordinator.reconcile(player_id)
        if not state.exam_eligible and state.passed_exam_attempt_id is None:
            raise ExamServiceError("exam_not_eligible", "尚未获得正式考试资格。")
        return tuple(
            PublicExamQuestion(
                question_id=item.question_id, section=item.section.value,
                public_scenario=item.public_scenario,
                options=tuple({"option_id": opt.option_id, "public_text": opt.public_text} for opt in item.options),
                score=item.score,
            )
            for item in self.definition.questions
        )

    def start(self, player_id: str, *, request_id: str) -> ExamSessionState:
        permission = self.permission_coordinator.reconcile(player_id)
        attempts = tuple(
            sorted(
                (item for item in self.store.list_exam_sessions() if item.player_id == player_id),
                key=lambda item: item.attempt_number,
            )
        )
        active = next((item for item in attempts if item.status.value in {"active", "created"}), None)
        if active is not None:
            return active
        if permission.passed_exam_attempt_id is not None:
            raise ExamServiceError("exam_already_passed", "正式考试已经通过，不能重复获取认可。")
        if not permission.exam_eligible:
            raise ExamServiceError("exam_not_eligible", "尚未获得正式考试资格。")
        if attempts:
            prior = attempts[-1]
            if prior.result is None or prior.result.passed:
                raise ExamServiceError("exam_retake_blocked", "当前不允许创建重考。")
            plan = self.store.load_teaching_plan(player_id)
            required = set(prior.result.required_remediation_ids)
            completed_after_failure = {
                event.remediation_id for event in plan.events
                if isinstance(event, RemediationAttempted) and event.correct
                and event.sequence > next(
                    item.teaching_plan_revision for item in prior.events
                    if isinstance(item, ExamFailed)
                )
            }
            if not required.issubset(completed_after_failure):
                raise ExamServiceError("exam_retake_blocked", "完成指定补课后才可重考。")
            if not any(isinstance(item, ExamRetakeUnlocked) for item in prior.events):
                prior = self._append(prior, ExamRetakeUnlocked(
                    sequence=prior.revision + 1, player_id=player_id,
                    occurred_at=self.clock.now(), prior_attempt_id=prior.attempt_id,
                    completed_remediation_ids=tuple(sorted(completed_after_failure.intersection(required))),
                ))
                self.store.save_exam_session(prior)
        attempt_number = len(attempts) + 1
        seed = f"{player_id}|{request_id}|{attempt_number}"
        digest = hashlib.sha256(seed.encode()).hexdigest()[:20]
        session_id = f"exam_session_{digest}"
        attempt_id = f"exam_attempt_{digest}"
        event = ExamStarted(
            sequence=1, player_id=player_id, occurred_at=self.clock.now(),
            exam_session_id=session_id, exam_id=self.definition.exam_id,
            attempt_id=attempt_id, attempt_number=attempt_number,
        )
        state = self.replayer.replay((event,))
        self.store.save_exam_session(state)
        return state

    def record_answer(
        self, *, player_id: str, exam_session_id: str,
        question_id: str, selected_option_ids: tuple[str, ...],
    ) -> ExamSessionState:
        state = self.store.load_exam_session(exam_session_id)
        self._owner(state, player_id)
        if state.status.value not in {"active", "created"}:
            raise ExamServiceError("exam_answers_locked", "考试提交后不能修改答案。")
        question = next((item for item in self.definition.questions if item.question_id == question_id), None)
        if question is None:
            raise ExamServiceError("exam_question_invalid", "考试题目标识无效。")
        if question_id in state.submitted_answers:
            if state.submitted_answers[question_id] == selected_option_ids:
                return state
            raise ExamServiceError("exam_answer_already_recorded", "已记录的答案不能修改。")
        public_ids = {item.option_id for item in question.options}
        if not selected_option_ids or not set(selected_option_ids).issubset(public_ids):
            raise ExamServiceError("exam_option_invalid", "考试选项无效。")
        event = ExamAnswerRecorded(
            sequence=state.revision + 1, player_id=player_id, occurred_at=self.clock.now(),
            question_id=question_id, selected_option_ids=tuple(sorted(set(selected_option_ids))),
        )
        state = self._append(state, event)
        self.store.save_exam_session(state)
        return state

    def submit(self, *, player_id: str, exam_session_id: str) -> ExamServiceResult:
        state = self.store.load_exam_session(exam_session_id)
        self._owner(state, player_id)
        if state.result is not None:
            return ExamServiceResult(ok=True, code="exam_already_submitted", message="考试结果已提交。", state=state)
        required_questions = {item.question_id for item in self.definition.questions}
        if set(state.submitted_answers) != required_questions:
            raise ExamServiceError("exam_answers_incomplete", "全部题目作答后才能提交。")
        answer_text = "|".join(
            f"{key}:{','.join(state.submitted_answers[key])}" for key in sorted(state.submitted_answers)
        )
        fingerprint = "answer_" + hashlib.sha256(answer_text.encode()).hexdigest()[:24]
        state = self._append(state, ExamSubmitted(
            sequence=state.revision + 1, player_id=player_id,
            occurred_at=self.clock.now(), answer_fingerprint=fingerprint,
        ))
        section_scores = {section: 0 for section in {item.section for item in self.definition.questions}}
        wrong = []
        critical_failure = False
        score = 0
        remediations = []
        for question in self.definition.questions:
            correct = set(state.submitted_answers[question.question_id]) == set(question.correct_option_ids)
            if correct:
                score += question.score
                section_scores[question.section] += question.score
            else:
                wrong.extend(question.targeted_ability_ids)
                remediations.append(question.remediation_id)
                critical_failure = critical_failure or question.critical_safety
        passed = (
            score >= self.definition.passing_score
            and all(value > 0 for value in section_scores.values())
            and not critical_failure
        )
        now = self.clock.now()
        result = ExamResult(
            exam_id=self.definition.exam_id, attempt_id=state.attempt_id, player_id=player_id,
            total_score=score, section_scores=section_scores, critical_failure=critical_failure,
            passed=passed, improvement_areas=tuple(sorted(set(wrong), key=lambda item: item.value)),
            required_remediation_ids=tuple(sorted(set(remediations))), submitted_at=now,
            source_revision=self.definition.source_revision,
        )
        state = self._append(state, ExamScored(
            sequence=state.revision + 1, player_id=player_id, occurred_at=now, result=result,
        ))
        terminal: ExamEvent
        if passed:
            terminal = ExamPassed(sequence=state.revision + 1, player_id=player_id, occurred_at=now, attempt_id=state.attempt_id)
        else:
            plan_revision = self.store.load_teaching_plan(player_id).revision
            terminal = ExamFailed(
                sequence=state.revision + 1, player_id=player_id, occurred_at=now,
                attempt_id=state.attempt_id,
                required_remediation_ids=result.required_remediation_ids,
                teaching_plan_revision=plan_revision,
            )
        state = self._append(state, terminal)
        self.store.save_exam_session(state)
        pending = False
        if passed:
            try:
                self.permission_coordinator.grant_exam_pass(player_id, state.attempt_id)
            except Exception:
                pending = True
        return ExamServiceResult(
            ok=True, code="exam_progression_pending" if pending else ("exam_passed" if passed else "exam_failed"),
            message="考试已通过；晋级尚待协调。" if pending else ("考试通过。" if passed else "考试未通过，请完成指定补课后重考。"),
            state=state, progression_pending=pending,
        )

    def reconcile(self, player_id: str) -> ExamServiceResult:
        passed = next((item for item in self.store.list_exam_sessions() if item.player_id == player_id and item.result is not None and item.result.passed), None)
        if passed is None:
            return ExamServiceResult(ok=True, code="exam_no_pending", message="没有待协调的考试晋级。")
        self.permission_coordinator.grant_exam_pass(player_id, passed.attempt_id)
        return ExamServiceResult(ok=True, code="exam_progression_ready", message="考试晋级已协调。", state=passed)

    def public_result(self, player_id: str, exam_session_id: str) -> PublicExamResult:
        state = self.store.load_exam_session(exam_session_id)
        self._owner(state, player_id)
        if state.result is None:
            raise ExamServiceError("exam_not_submitted", "考试尚未提交。")
        result = state.result
        return PublicExamResult(
            exam_id=result.exam_id, attempt_id=result.attempt_id, total_score=result.total_score,
            section_scores={key.value: value for key, value in result.section_scores.items()},
            critical_failure=result.critical_failure, passed=result.passed,
            improvement_areas=tuple(item.value for item in result.improvement_areas),
            required_remediation_ids=result.required_remediation_ids,
            submitted_at=result.submitted_at,
        )

    @staticmethod
    def _owner(state: ExamSessionState, player_id: str) -> None:
        if state.player_id != player_id:
            raise ExamServiceError("exam_player_mismatch", "不能访问其他玩家的考试。")

    def _append(self, state: ExamSessionState, event: ExamEvent) -> ExamSessionState:
        return self.replayer.replay((*state.events, event))
