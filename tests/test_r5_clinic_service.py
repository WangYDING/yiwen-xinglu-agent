from pathlib import Path

import pytest

from xuanyi_npc.application.clinic import ClinicActionInput, ClinicError, ClinicService
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.domain.clinic import R5AcceptanceContract
from xuanyi_npc.domain.permissions import PermissionLevel
from xuanyi_npc.storage import JsonStateStore
from tests.r1_helpers import FixedClock, FixedPlayerIds, FixedSessionIds


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"


def build_clinic(tmp_path):
    return ClinicService(
        store=JsonStateStore(tmp_path), base_catalog=CaseCatalog(ROOT / "cases"),
        campaign_path=ROOT / "campaign" / "cross_episode_rules_v2.json",
        clock=FixedClock(), player_id_factory=FixedPlayerIds(), session_id_factory=FixedSessionIds(),
    )


def test_clinic_home_combines_public_state_without_hidden_fields(tmp_path):
    clinic = build_clinic(tmp_path)
    view = clinic.create_player("医馆弟子")
    assert len(view.visible_cases) == 6
    assert view.teaching_stage == "PROBATIONARY"
    serialized = view.model_dump_json()
    for forbidden in ("root_cause", "valid_diagnosis_ids", "hidden_information", "correct_option_ids", "MENTOR_SECRET"):
        assert forbidden not in serialized


def test_clinic_natural_action_reuses_formal_service_and_rejects_cross_player(tmp_path):
    clinic = build_clinic(tmp_path)
    first = clinic.create_player("甲").player_summary.player_id
    second = clinic.create_player("乙").player_summary.player_id
    started = clinic.start_case(first, "lantern_alley_conflicting_testimony")
    result = clinic.submit_case_action(ClinicActionInput(
        player_id=first, case_id=started.case_id, session_id=started.session_id,
        operation_id="clinic_action_one", action_type="investigation",
        selection_id="observe_lantern_keeper",
    ))
    assert result.ok and result.session_revision == 1
    before = clinic.store.load_case_session(started.session_id).model_dump_json()
    with pytest.raises(ClinicError):
        clinic.submit_case_action(ClinicActionInput(
            player_id=second, case_id=started.case_id, session_id=started.session_id,
            operation_id="clinic_action_cross", action_type="investigation",
            selection_id="question_witness_yu",
        ))
    assert clinic.store.load_case_session(started.session_id).model_dump_json() == before


def test_inheritance_investigation_is_absent_then_visible_as_generic_action(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("传承路径").player_summary.player_id
    ordinary = clinic._service(player).case_catalog.get("returning_contract_nameless_shrine")
    assert "trace_contract_handoff_with_inheritance" not in {item.investigation_id for item in ordinary.investigations}
    state = clinic.permissions.ensure(player)
    state = clinic.permissions._append(state, __import__("xuanyi_npc.domain.permissions", fromlist=["PermissionGranted"]).PermissionGranted(
        sequence=state.revision + 1, player_id=player, occurred_at=FixedClock().now(),
        permission=PermissionLevel.INHERITANCE, source_reference_id="test_inheritance_access",
    ))
    clinic.store.save_permission_state(state)
    inherited = clinic._service(player).case_catalog.get("returning_contract_nameless_shrine")
    extra = next(item for item in inherited.investigations if item.investigation_id == "trace_contract_handoff_with_inheritance")
    assert extra.reveals_clue_ids == {"hidden_witness_rubbing"}
    assert inherited.valid_diagnosis_ids == ordinary.valid_diagnosis_ids
    assert inherited.scoring == ordinary.scoring


def test_curriculum_v2_starts_with_foundation_and_does_not_lock_six_cases(tmp_path):
    clinic = build_clinic(tmp_path)
    view = clinic.create_player("选课弟子")
    assert view.current_recommendation.recommendation_id == "evidence_before_diagnosis_v1"
    assert view.current_recommendation.does_not_lock_cases
    assert {item.status for item in view.visible_cases} == {"available"}
