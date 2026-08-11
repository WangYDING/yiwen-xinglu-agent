import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.domain import (
    CurriculumSelectionPolicy,
    LessonDefinition,
    R3AcceptanceContract,
    RemediationDefinition,
    StructuredMemorySelectionPolicy,
)


RESOURCE_DIR = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources" / "curriculum"


def load(name: str) -> str:
    return (RESOURCE_DIR / name).read_text(encoding="utf-8")


def test_three_core_lessons_are_versioned_and_case_bound():
    names = (
        "evidence_before_diagnosis_v1.json",
        "provenance_before_intent_v1.json",
        "corroborate_before_handoff_v1.json",
    )
    lessons = tuple(LessonDefinition.model_validate_json(load(name)) for name in names)
    assert tuple(item.lesson_id for item in lessons) == (
        "evidence_before_diagnosis_v1",
        "provenance_before_intent_v1",
        "corroborate_before_handoff_v1",
    )
    assert tuple(item.assigned_case_id for item in lessons) == (
        "old_paper_umbrella",
        "gray_hearth_inn",
        "moon_well_echo",
    )
    assert all(item.version == "v1" and item.maximum_hints == 2 for item in lessons)


def test_three_fixed_remediations_have_rule_scored_generic_exercises():
    names = (
        "remediate_evidence_completeness_v1.json",
        "remediate_diagnostic_reasoning_v1.json",
        "remediate_treatment_alignment_v1.json",
    )
    items = tuple(RemediationDefinition.model_validate_json(load(name)) for name in names)
    assert tuple(item.remediation_id for item in items) == tuple(name[:-5] for name in names)
    assert all(len(item.answer_options) >= 2 for item in items)
    forbidden_case_answers = {
        "rain_vow_breach",
        "return_token_and_fulfill_vow",
        "displaced_hearth_contract",
        "restore_token_and_clear_flue",
        "misbound_message_handoff",
        "verify_recipient_and_deliver",
    }
    payload = " ".join(load(name) for name in names)
    assert forbidden_case_answers.isdisjoint(payload.split())


def test_curriculum_priority_and_acceptance_expectations_are_frozen():
    policy = CurriculumSelectionPolicy.model_validate_json(
        load("curriculum_selection_v1.json")
    )
    assert tuple(item.ability_ids[0].value for item in policy.improvement_priority) == (
        "ethical_practice",
        "apply_treatment",
        "reason_diagnosis",
        "ask_cause",
    )
    assert policy.core_lesson_order == (
        "evidence_before_diagnosis_v1",
        "provenance_before_intent_v1",
        "corroborate_before_handoff_v1",
    )
    acceptance = R3AcceptanceContract.model_validate_json(load("r3_acceptance_v1.json"))
    expected = {item.scenario_id: item.expected_recommendation_id for item in acceptance.scenarios}
    assert expected["ethics_over_all"] == "remediate_treatment_alignment_v1"
    assert expected["foundation_complete"] == "foundation_complete"


def test_structured_memory_contract_has_no_vector_dependency():
    policy = StructuredMemorySelectionPolicy.model_validate_json(
        load("structured_mentor_memory_selection_v1.json")
    )
    assert policy.default_limit == 3
    assert policy.ordering == ("priority_desc", "occurred_at_desc", "memory_id_asc")
    assert policy.requires_embedding is False
    assert policy.uses_similarity is False


@pytest.mark.parametrize(
    ("model", "resource"),
    (
        (LessonDefinition, "provenance_before_intent_v1.json"),
        (RemediationDefinition, "remediate_evidence_completeness_v1.json"),
        (CurriculumSelectionPolicy, "curriculum_selection_v1.json"),
        (StructuredMemorySelectionPolicy, "structured_mentor_memory_selection_v1.json"),
        (R3AcceptanceContract, "r3_acceptance_v1.json"),
    ),
)
def test_r3_contract_schemas_reject_unknown_fields(model, resource):
    payload = json.loads(load(resource))
    payload["unexpected"] = "must fail"
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_lesson_case_binding_cannot_be_changed():
    payload = json.loads(load("provenance_before_intent_v1.json"))
    payload["assigned_case_id"] = "moon_well_echo"
    with pytest.raises(ValidationError):
        LessonDefinition.model_validate(payload)
