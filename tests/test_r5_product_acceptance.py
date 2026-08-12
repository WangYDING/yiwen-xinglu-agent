from xuanyi_npc.domain.permissions import PermissionLevel
from tests.r4_helpers import answer_exam
from tests.test_r3_adaptive_teaching import complete_taught_case
from tests.test_r5_clinic_service import build_clinic
from tests.r5_helpers import complete_case
from xuanyi_npc.domain.clinic import R5AcceptanceContract
from pathlib import Path
from xuanyi_npc.application.teaching import CreateTeachingSessionInput, TeachingRequest


CASE_ORDER = (
    "old_paper_umbrella", "gray_hearth_inn", "moon_well_echo",
    "lantern_alley_conflicting_testimony", "mist_ferry_borrowed_lantern",
    "returning_contract_nameless_shrine",
)


def test_six_case_product_route_exam_inheritance_and_summary(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("完整路线弟子").player_summary.player_id
    for case_id in CASE_ORDER[:3]:
        teaching = clinic.teaching_service(player)
        complete_taught_case(clinic._service(player), teaching, clinic.store, player, case_id)
    refused = clinic.inheritance.request(player)
    assert not refused.granted and "exam_required" in refused.decision.public_reason_codes
    clinic.permissions.reconcile(player)
    attempt = answer_exam(clinic.exams, clinic.exams.start(player, request_id="r5_full_exam"))
    result = clinic.exams.submit(player_id=player, exam_session_id=attempt.exam_session_id)
    assert result.state.result.passed
    assert clinic.inheritance.request(player).granted
    contract = R5AcceptanceContract.model_validate_json((Path(__file__).parents[1] / "src/xuanyi_npc/resources/clinic/r5_acceptance_v1.json").read_text(encoding="utf-8"))
    for case_contract in contract.advanced_cases:
        service = clinic._service(player)
        session_id, _ = complete_case(service, clinic.store, player, case_contract)
        teaching = clinic.teaching_service(player)
        created = teaching.create(CreateTeachingSessionInput(player_id=player, case_session_id=session_id))
        reviewed = teaching.observe_case_completion(TeachingRequest(player_id=player, teaching_session_id=created.state.teaching_session_id))
        assert reviewed.ok
    view = clinic.home(player)
    plan = clinic.store.load_teaching_plan(player)
    assert {item.case_id for item in clinic._service(player).get_campaign_view(
        __import__("xuanyi_npc.application", fromlist=["CampaignPlayerInput"]).CampaignPlayerInput(player_id=player)
    ).campaign_view.completed_cases} == set(CASE_ORDER)
    assert len(plan.completed_core_lessons) == 6
    assert view.current_recommendation.recommendation_id == "current_training_complete"
    assert view.exam_status == "passed" and view.inheritance_status == "granted"
    assert PermissionLevel.INHERITANCE.value in view.permissions


def test_clinic_state_recovers_in_second_service_instance_without_duplicate_action(tmp_path):
    first = build_clinic(tmp_path)
    player = first.create_player("恢复弟子").player_summary.player_id
    started = first.start_case(player, "lantern_alley_conflicting_testimony")
    from xuanyi_npc.application.clinic import ClinicActionInput
    action = ClinicActionInput(
        player_id=player, case_id=started.case_id, session_id=started.session_id,
        operation_id="op_recover_once", action_type="investigation",
        selection_id="observe_lantern_keeper",
    )
    assert first.submit_case_action(action).session_revision == 1
    second = build_clinic(tmp_path)
    restored = second.resume_case(player, started.case_id, started.session_id)
    assert second.store.load_case_session(started.session_id).revision == 1
    assert {item.clue_id for item in restored.observation.discovered_clues} == {"keeper_timing_notes", "confident_accusation"}
    assert second.home(player).active_case == started.case_id


def test_two_players_keep_teaching_case_exam_and_permission_state_isolated(tmp_path):
    clinic = build_clinic(tmp_path)
    first = clinic.create_player("甲").player_summary.player_id
    second = clinic.create_player("乙").player_summary.player_id
    complete_taught_case(clinic._service(first), clinic.teaching_service(first), clinic.store, first, CASE_ORDER[0])
    first_view, second_view = clinic.home(first), clinic.home(second)
    assert first_view.relationship != second_view.relationship
    assert clinic.store.load_teaching_plan(first).revision > clinic.store.load_teaching_plan(second).revision
    assert not clinic.store.list_exam_sessions()
    assert first_view.permissions == second_view.permissions
