from xuanyi_npc.domain.permissions import PermissionEventReplayer, PermissionLevel, R4TeachingStage
from tests.r1_helpers import create_player
from tests.r4_helpers import build_r4, complete_excellent_foundation


def test_stage_and_permissions_are_deterministic_and_replayable(tmp_path):
    cases, teaching, store, permissions, _, _ = build_r4(tmp_path)
    player = create_player(cases)
    initial = permissions.ensure(player)
    assert initial.teaching_stage is R4TeachingStage.PROBATIONARY
    assert initial.permissions == {PermissionLevel.PUBLIC}
    teaching.plan_service.ensure(player)
    started = permissions.reconcile(player)
    assert PermissionLevel.APPRENTICE in started.permissions
    complete_excellent_foundation(cases, teaching, store, player)
    candidate = permissions.reconcile(player)
    assert candidate.teaching_stage is R4TeachingStage.EXAM_CANDIDATE
    assert candidate.exam_eligible
    assert PermissionEventReplayer(permissions.policy).replay(candidate.events) == candidate
    revision = candidate.revision
    assert permissions.reconcile(player).revision == revision


def test_players_are_isolated_and_mentor_secret_never_granted(tmp_path):
    cases, teaching, store, permissions, _, _ = build_r4(tmp_path)
    first = create_player(cases, "甲")
    second = create_player(cases, "乙")
    complete_excellent_foundation(cases, teaching, store, first)
    permissions.reconcile(first)
    other = permissions.ensure(second)
    assert other.permissions == {PermissionLevel.PUBLIC}
    assert PermissionLevel.MENTOR_SECRET not in permissions.public_view(first).permissions

