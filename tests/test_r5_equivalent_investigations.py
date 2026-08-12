from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.application.clinic import ClinicActionInput
from xuanyi_npc.domain import CaseDefinition
from xuanyi_npc.domain.cases import CaseSessionState
from xuanyi_npc.domain.permissions import PermissionGranted, PermissionLevel
from xuanyi_npc.engine.replay import CaseEventReplayer
from tests.r1_helpers import FixedClock
from tests.test_play_cli import replay_events
from tests.test_r5_clinic_service import build_clinic


ROOT = Path(__file__).parents[1] / "src/xuanyi_npc/resources"
CASE_ID = "returning_contract_nameless_shrine"
ORDINARY = "investigate_hidden_witness_mark"
INHERITED = "trace_contract_handoff_with_inheritance"


def definition_payload():
    import json
    return json.loads((ROOT / "cases" / f"{CASE_ID}.json").read_text(encoding="utf-8"))


def grant_inheritance(clinic, player):
    state = clinic.permissions.ensure(player)
    state = clinic.permissions._append(state, PermissionGranted(
        sequence=state.revision + 1, player_id=player, occurred_at=FixedClock().now(),
        permission=PermissionLevel.INHERITANCE, source_reference_id="equivalent_path_test",
    ))
    clinic.store.save_permission_state(state)


def act(clinic, player, session, investigation, index):
    return clinic.submit_case_action(ClinicActionInput(
        player_id=player, case_id=CASE_ID, session_id=session,
        operation_id=f"equivalent_action_{index}", action_type="investigation",
        selection_id=investigation,
    ))


def finish(clinic, player, session, index):
    state = clinic.store.load_case_session(session)
    diagnosed = clinic.submit_case_action(ClinicActionInput(
        player_id=player, case_id=CASE_ID, session_id=session,
        operation_id=f"equivalent_diagnosis_{index}", action_type="diagnosis",
        selection_id="misordered_return_contract_and_erased_witness",
        evidence_clue_ids=tuple(sorted(state.discovered_clue_ids)),
    ))
    assert diagnosed.ok
    return clinic.submit_case_action(ClinicActionInput(
        player_id=player, case_id=CASE_ID, session_id=session,
        operation_id=f"equivalent_treatment_{index}", action_type="treatment",
        selection_id="restore_witness_name_and_return_contract",
    ))


def run_path(clinic, player, chosen):
    started = clinic.start_case(player, CASE_ID)
    case = clinic._service(player).case_catalog.get(CASE_ID)
    selected = [item.investigation_id for item in case.investigations if item.investigation_id not in {ORDINARY, INHERITED}]
    selected.append(chosen)
    for index, investigation in enumerate(selected, 1):
        act(clinic, player, started.session_id, investigation, index)
    resumed = clinic.resume_case(player, CASE_ID, started.session_id)
    assert resumed.observation.can_submit_diagnosis
    assert ORDINARY not in {item.investigation_id for item in resumed.observation.available_investigations}
    assert INHERITED not in {item.investigation_id for item in resumed.observation.available_investigations}
    result = finish(clinic, player, started.session_id, 20)
    state = clinic.store.load_case_session(started.session_id)
    replayed = CaseEventReplayer().replay(
        CaseSessionState(session_id=state.session_id, case_id=state.case_id, player_id=state.player_id),
        replay_events(case, state),
    )
    assert replayed == state
    return result, state


def test_schema_normalizes_single_member_requirements_for_legacy_cases():
    case = CaseDefinition.model_validate_json((ROOT / "cases/old_paper_umbrella.json").read_text(encoding="utf-8"))
    requirements = case.normalized_investigation_requirements()
    assert len(requirements) == len(case.investigations)
    assert all(len(item.satisfying_investigation_ids) == 1 for item in requirements)


@pytest.mark.parametrize("mutation", ["empty", "unknown", "duplicate", "overlap"])
def test_invalid_requirement_groups_are_rejected(mutation):
    payload = definition_payload()
    groups = payload["investigation_requirements"]
    if mutation == "empty": groups[0]["satisfying_investigation_ids"] = []
    elif mutation == "unknown": groups[0]["satisfying_investigation_ids"] = ["unknown_investigation"]
    elif mutation == "duplicate": groups[1]["requirement_id"] = groups[0]["requirement_id"]
    else: groups[1]["satisfying_investigation_ids"] = [groups[0]["satisfying_investigation_ids"][0]]
    with pytest.raises(ValidationError):
        CaseDefinition.model_validate(payload)


def test_ordinary_and_inheritance_paths_are_equivalent_resolved_100_and_replay(tmp_path):
    ordinary_clinic = build_clinic(tmp_path / "ordinary")
    ordinary_player = ordinary_clinic.create_player("普通路径").player_summary.player_id
    ordinary_result, ordinary_state = run_path(ordinary_clinic, ordinary_player, ORDINARY)
    inherited_clinic = build_clinic(tmp_path / "inherited")
    inherited_player = inherited_clinic.create_player("传承路径").player_summary.player_id
    grant_inheritance(inherited_clinic, inherited_player)
    inherited_result, inherited_state = run_path(inherited_clinic, inherited_player, INHERITED)
    assert ordinary_result.episode_result.score == inherited_result.episode_result.score == 100
    assert ordinary_result.episode_result.outcome.value == inherited_result.episode_result.outcome.value == "resolved"
    assert ordinary_state.revision == inherited_state.revision == 8
    assert INHERITED not in {item.reference_id for item in ordinary_state.action_history}
    assert ORDINARY not in {item.reference_id for item in inherited_state.action_history}
    assert ordinary_state.discovered_clue_ids == inherited_state.discovered_clue_ids


@pytest.mark.parametrize("first,second", [(ORDINARY, INHERITED), (INHERITED, ORDINARY)])
def test_equivalent_second_investigation_is_hidden_and_zero_write_rejected(tmp_path, first, second):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("去重路径").player_summary.player_id
    grant_inheritance(clinic, player)
    started = clinic.start_case(player, CASE_ID)
    prerequisites = ["observe_shrine_visitor", "question_shrine_keeper", "inspect_nameless_stele", "inspect_return_ledger", "observe_shrine_qi"]
    for index, item in enumerate(prerequisites, 1): act(clinic, player, started.session_id, item, index)
    act(clinic, player, started.session_id, first, 10)
    observation = clinic.resume_case(player, CASE_ID, started.session_id).observation
    assert second not in {item.investigation_id for item in observation.available_investigations}
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(Exception) as rejected:
        act(clinic, player, started.session_id, second, 11)
    assert getattr(rejected.value, "code", None) == "investigation_requirement_already_satisfied"
    after = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after


def test_permission_overlay_does_not_change_truth_candidates_or_score(tmp_path):
    clinic = build_clinic(tmp_path); player = clinic.create_player("边界").player_summary.player_id
    ordinary = clinic._service(player).case_catalog.get(CASE_ID)
    grant_inheritance(clinic, player); inherited = clinic._service(player).case_catalog.get(CASE_ID)
    assert ordinary.root_cause == inherited.root_cause
    assert ordinary.causal_chain == inherited.causal_chain
    assert ordinary.diagnosis_candidates == inherited.diagnosis_candidates
    assert ordinary.treatments == inherited.treatments
    assert ordinary.scoring == inherited.scoring
