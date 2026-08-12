import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.domain.cases import CaseDefinition, TreatmentOutcome
from xuanyi_npc.domain.clinic import ClinicContract, CurriculumSelectionV2, R5AcceptanceContract
from xuanyi_npc.domain.mentor import LessonDefinition


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"
CASE_IDS = (
    "lantern_alley_conflicting_testimony",
    "mist_ferry_borrowed_lantern",
    "returning_contract_nameless_shrine",
)
LESSON_IDS = (
    "cross_check_conflicting_testimony_v1",
    "bounded_treatment_and_consequence_v1",
    "integrated_causal_reasoning_v1",
)


def read(relative):
    return (ROOT / relative).read_text(encoding="utf-8")


def test_three_advanced_cases_freeze_generic_scale_truth_and_gold():
    acceptance = R5AcceptanceContract.model_validate_json(read("clinic/r5_acceptance_v1.json"))
    contracts = {item.case_id: item for item in acceptance.advanced_cases}
    for case_id in CASE_IDS:
        case = CaseDefinition.model_validate_json(read(f"cases/{case_id}.json"))
        contract = contracts[case_id]
        assert len(case.investigations) >= 6 and len(case.clues) >= 8
        assert sum(item.is_key for item in case.clues.values()) >= 6
        assert sum(item.is_misleading for item in case.clues.values()) >= 2
        assert len(case.diagnosis_candidates) == len(case.treatments) == 3
        assert {item.outcome for item in case.treatments.values()} == set(TreatmentOutcome)
        assert contract.correct_diagnosis_id in case.valid_diagnosis_ids
        assert case.treatments[contract.resolved_treatment_id].outcome is TreatmentOutcome.RESOLVED
        assert len(contract.gold_investigation_orders) >= 2


def test_advanced_lessons_and_curriculum_v2_are_frozen_without_rewriting_v1():
    lessons = tuple(LessonDefinition.model_validate_json(read(f"curriculum/{item}.json")) for item in LESSON_IDS)
    policy = CurriculumSelectionV2.model_validate_json(read("curriculum/curriculum_selection_v2.json"))
    assert tuple(item.lesson_id for item in lessons) == LESSON_IDS
    assert policy.preserves_policy_id == "curriculum_selection_v1"
    assert policy.advanced_lesson_order == LESSON_IDS
    assert all(step.does_not_lock_cases for step in policy.steps)


def test_clinic_contract_is_loopback_idempotent_and_complete():
    contract = ClinicContract.model_validate_json(read("clinic/clinic_contract_v1.json"))
    assert contract.host == "127.0.0.1" and contract.default_port == 0
    assert all(route.idempotency_required for route in contract.routes if route.method == "POST")
    assert "root_cause" in contract.forbidden_public_fields
    assert "correct_option_ids" in contract.forbidden_public_fields


def test_acceptance_freezes_six_case_paths_and_r4_boundary():
    contract = R5AcceptanceContract.model_validate_json(read("clinic/r5_acceptance_v1.json"))
    assert len(contract.case_order) == 6
    assert contract.r4_contract_revision == "r4_contract_v1"
    assert contract.mcp_tool_count_unchanged == 9
    assert contract.external_calls_expected == 0
    shrine = next(item for item in contract.advanced_cases if item.case_id == "returning_contract_nameless_shrine")
    assert shrine.ordinary_path_max_score == shrine.inheritance_path_max_score == 100


def test_r5_contracts_reject_extra_fields_and_public_secret_drift():
    payload = json.loads(read("clinic/clinic_contract_v1.json"))
    payload["external_host"] = "0.0.0.0"
    with pytest.raises(ValidationError):
        ClinicContract.model_validate(payload)
