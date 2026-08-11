import pytest
from unittest.mock import patch

from xuanyi_npc.application.permissions import PermissionAccessError
from xuanyi_npc.domain import AbilityId
from xuanyi_npc.domain.permissions import PermissionEventReplayer, PermissionLevel
from tests.r1_helpers import create_player
from tests.r4_helpers import answer_exam, build_r4, complete_excellent_foundation
from tests.test_r3_adaptive_teaching import complete_taught_case


def test_first_refusal_is_zero_write_then_exam_enables_single_grant(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    files = tuple(sorted(tmp_path.rglob("*")))
    before = {path: path.read_bytes() for path in files if path.is_file()}
    refused = inheritance.request(player)
    after = {path: path.read_bytes() for path in files if path.is_file()}
    assert not refused.granted
    assert "exam_required" in refused.decision.public_reason_codes
    assert "80" not in refused.message and "13" not in refused.message
    assert before == after
    attempt = answer_exam(exams, exams.start(player, request_id="inherit"))
    exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    granted = inheritance.request(player)
    assert granted.granted
    state = store.load_permission_state(player)
    assert PermissionLevel.INHERITANCE in state.permissions
    assert "trace_vow_restore_v1" in state.granted_inheritance_ids
    assert PermissionEventReplayer(permissions.policy).replay(state.events) == state
    revision = state.revision
    repeated = inheritance.request(player)
    assert repeated.granted and store.load_permission_state(player).revision == revision
    content = inheritance.read_content(player, "trace_vow_restore_teaching_v1")
    assert content.title == "溯契还因"


def test_guessed_content_secret_and_cross_player_are_denied_without_write(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases, "甲")
    other = create_player(cases, "乙")
    permissions.ensure(player)
    permissions.ensure(other)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    for operation in (
        lambda: inheritance.read_content(player, "guessed_inheritance_content"),
        lambda: inheritance.read_content(other, "trace_vow_restore_teaching_v1"),
        lambda: inheritance.read_mentor_secret(player),
    ):
        with pytest.raises(PermissionAccessError):
            operation()
    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert before == after


def test_mentor_context_is_public_filtered_and_has_no_answers_or_thresholds(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    context = inheritance.build_mentor_context(player)
    serialized = context.model_dump_json()
    assert "EXAM_CANDIDATE" in serialized
    assert "correct_option" not in serialized
    assert "restricted_description" not in serialized
    assert "minimum_proficiency" not in serialized
    assert "MENTOR_SECRET" not in serialized


def test_exam_pass_cannot_bypass_low_trust_or_ability(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    complete_taught_case(
        cases, teaching, store, player, "old_paper_umbrella",
        diagnosis_id="exam_exhaustion",
    )
    remediation = teaching.curriculum.remediations["remediate_diagnostic_reasoning_v1"]
    teaching.plan_service.attempt_remediation(
        player_id=player, remediation_id=remediation.remediation_id,
        option_id=remediation.correct_option_id, request_id="fix_wrong_diagnosis",
    )
    for case_id in ("gray_hearth_inn", "moon_well_echo"):
        complete_taught_case(cases, teaching, store, player, case_id)
    permissions.reconcile(player)
    attempt = answer_exam(exams, exams.start(player, request_id="low_trust"))
    exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    refused = inheritance.request(player)
    assert not refused.granted
    assert "trust_insufficient" in refused.decision.public_reason_codes
    assert "ability_evidence_insufficient" in refused.decision.public_reason_codes


def test_unresolved_ethics_has_priority_even_after_exam_pass(tmp_path):
    cases, teaching, store, permissions, exams, inheritance = build_r4(tmp_path)
    player = create_player(cases)
    complete_excellent_foundation(cases, teaching, store, player)
    permissions.reconcile(player)
    attempt = answer_exam(exams, exams.start(player, request_id="ethics_priority"))
    exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    plan = store.load_teaching_plan(player).model_copy(
        update={"unresolved_improvement_areas": (AbilityId.ETHICAL_PRACTICE,)}
    )
    with patch.object(store, "load_teaching_plan", return_value=plan):
        decision = inheritance.policy.decide(player)
    assert not decision.eligible
    assert decision.public_reason_codes[0] == "ethics_unresolved"
