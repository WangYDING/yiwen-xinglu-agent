import pytest

from xuanyi_npc.application.exams import ExamServiceError
from xuanyi_npc.domain.exams import ExamEventReplayer, ExamSessionStatus
from xuanyi_npc.domain.permissions import PermissionLevel, R4TeachingStage
from tests.r1_helpers import create_player
from tests.r4_helpers import answer_exam, build_r4, complete_excellent_foundation


def test_excellent_route_passes_once_without_answer_leak(tmp_path):
    cases, teaching, store, permissions, exams, _ = build_r4(tmp_path)
    player = create_player(cases)
    with pytest.raises(ExamServiceError) as denied:
        exams.public_questions(player)
    assert denied.value.code == "exam_not_eligible"
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    questions = exams.public_questions(player)
    assert "correct_option" not in str([item.model_dump() for item in questions])
    attempt = answer_exam(exams, exams.start(player, request_id="first"))
    result = exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    assert result.state.status is ExamSessionStatus.PASSED
    public = exams.public_result(player, attempt.exam_session_id)
    assert public.passed and public.total_score == 100
    permission = permissions.public_view(player)
    assert permission.teaching_stage is R4TeachingStage.INNER_DISCIPLE
    assert PermissionLevel.INNER_DISCIPLE in permission.permissions
    assert permission.effective_recognition == 18
    assert ExamEventReplayer().replay(result.state.events) == result.state
    with pytest.raises(ExamServiceError) as repeated:
        exams.start(player, request_id="repeat")
    assert repeated.value.code == "exam_already_passed"


def test_failed_exam_requires_r3_remediation_then_new_attempt(tmp_path):
    cases, teaching, store, permissions, exams, _ = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    first = answer_exam(exams, exams.start(player, request_id="first"), fail_critical=True)
    failed = exams.submit(player_id=player, exam_session_id=first.exam_session_id).state
    assert failed.status is ExamSessionStatus.FAILED
    assert failed.result.critical_failure and not failed.result.passed
    with pytest.raises(ExamServiceError) as blocked:
        exams.start(player, request_id="too_early")
    assert blocked.value.code == "exam_retake_blocked"
    remediation_id = failed.result.required_remediation_ids[0]
    definition = teaching.curriculum.remediations[remediation_id]
    teaching.plan_service.attempt_remediation(
        player_id=player, remediation_id=remediation_id,
        option_id=definition.correct_option_id, request_id="exam_fix",
    )
    second = exams.start(player, request_id="second")
    assert second.attempt_number == 2 and second.attempt_id != first.attempt_id
    second = answer_exam(exams, second)
    passed = exams.submit(player_id=player, exam_session_id=second.exam_session_id).state
    assert passed.status is ExamSessionStatus.PASSED
    attempts = [item for item in store.list_exam_sessions() if item.player_id == player]
    assert len(attempts) == 2


def test_answers_are_immutable_and_cross_player_access_is_rejected(tmp_path):
    cases, teaching, store, permissions, exams, _ = build_r4(tmp_path)
    owner = create_player(cases, "甲")
    other = create_player(cases, "乙")
    complete_excellent_foundation(cases, teaching, store, owner)
    permissions.reconcile(owner)
    state = exams.start(owner, request_id="one")
    question = exams.definition.questions[0]
    state = exams.record_answer(player_id=owner, exam_session_id=state.exam_session_id, question_id=question.question_id, selected_option_ids=question.correct_option_ids)
    with pytest.raises(ExamServiceError) as changed:
        exams.record_answer(player_id=owner, exam_session_id=state.exam_session_id, question_id=question.question_id, selected_option_ids=(question.options[-1].option_id,))
    assert changed.value.code == "exam_answer_already_recorded"
    with pytest.raises(ExamServiceError) as denied:
        exams.public_result(other, state.exam_session_id)
    assert denied.value.code == "exam_player_mismatch"

