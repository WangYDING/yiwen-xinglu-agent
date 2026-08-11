from unittest.mock import patch

import pytest

from xuanyi_npc.application.exams import ExamService
from xuanyi_npc.application.inheritance import InheritanceService
from xuanyi_npc.application.permissions import PermissionCoordinator
from xuanyi_npc.storage import JsonStateStore, StorageError
from tests.r1_helpers import FixedClock, create_player
from tests.r4_helpers import answer_exam, build_r4, complete_excellent_foundation


def test_exam_resumes_in_second_service_process_and_finishes(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    first = exams.start(player, request_id="process_one")
    for question in exams.definition.questions[:2]:
        first = exams.record_answer(
            player_id=player, exam_session_id=first.exam_session_id,
            question_id=question.question_id, selected_option_ids=question.correct_option_ids,
        )
    # A separately constructed service only knows the persisted root.
    store2 = JsonStateStore(tmp_path)
    permissions2 = PermissionCoordinator(store2, FixedClock())
    exams2 = ExamService(store2, permissions2, FixedClock())
    resumed = exams2.start(player, request_id="process_two")
    assert resumed.exam_session_id == first.exam_session_id and resumed.revision == 3
    for question in exams2.definition.questions[2:]:
        resumed = exams2.record_answer(
            player_id=player, exam_session_id=resumed.exam_session_id,
            question_id=question.question_id, selected_option_ids=question.correct_option_ids,
        )
    result = exams2.submit(player_id=player, exam_session_id=resumed.exam_session_id)
    assert result.state.result.passed
    inheritance2 = InheritanceService(store2, permissions2, FixedClock())
    assert inheritance2.request(player).granted
    assert len([item for item in store2.list_exam_sessions() if item.player_id == player]) == 1


def test_exam_commit_survives_permission_projection_failure_and_reconciles(tmp_path):
    cases, teaching, store, permissions, exams, _ = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    attempt = answer_exam(exams, exams.start(player, request_id="fault"))
    with patch.object(store, "save_permission_state", side_effect=StorageError("fault")):
        result = exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    assert result.progression_pending and result.code == "exam_progression_pending"
    assert store.load_exam_session(attempt.exam_session_id).result.passed
    repaired = exams.reconcile(player)
    assert repaired.code == "exam_progression_ready"
    assert store.load_permission_state(player).passed_exam_attempt_id == attempt.attempt_id


def test_exam_result_save_failure_keeps_last_answer_snapshot_retryable(tmp_path):
    cases, teaching, store, permissions, exams, _ = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    attempt = answer_exam(exams, exams.start(player, request_id="save_fault"))
    with patch.object(store, "save_exam_session", side_effect=StorageError("fault")):
        with pytest.raises(StorageError):
            exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    persisted = store.load_exam_session(attempt.exam_session_id)
    assert persisted.result is None and len(persisted.submitted_answers) == 6
    assert exams.submit(player_id=player, exam_session_id=attempt.exam_session_id).state.result.passed


def test_inheritance_save_failure_does_not_create_partial_grant_and_retries(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    attempt = answer_exam(exams, exams.start(player, request_id="grant_fault"))
    exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    before = store.load_permission_state(player)
    with patch.object(store, "save_permission_state", side_effect=StorageError("fault")):
        with pytest.raises(StorageError):
            inheritance.request(player)
    assert store.load_permission_state(player) == before
    assert inheritance.request(player).granted


def test_mentor_explanation_failure_preserves_rule_grant(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    attempt = answer_exam(exams, exams.start(player, request_id="mentor_fault"))
    exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    result = inheritance.request_with_explanation(
        player, lambda *_: (_ for _ in ()).throw(RuntimeError("mentor unavailable"))
    )
    assert result.code == "mentor_explanation_pending"
    assert "trace_vow_restore_v1" in store.load_permission_state(player).granted_inheritance_ids

