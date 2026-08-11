import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.domain.exams import ExamDefinition, ExamEligibilityPolicy
from xuanyi_npc.domain.inheritance import InheritanceDefinition, R4AcceptanceContract
from xuanyi_npc.domain.permissions import PermissionLevel, PermissionPolicy


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"


def load(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_frozen_exam_is_six_rule_scored_questions_without_hints():
    exam = ExamDefinition.model_validate_json(load("exams/foundational_xuanyi_exam_v1.json"))
    assert len(exam.questions) == 6
    assert exam.passing_score == 80 and exam.hint_limit == 0
    assert sum(item.score for item in exam.questions) == 100
    assert all(item.correct_option_ids for item in exam.questions)


def test_exam_eligibility_contract_is_frozen():
    policy = ExamEligibilityPolicy(
        policy_id="exam_eligibility_v1", version="v1",
        required_core_lessons=("evidence_before_diagnosis_v1","provenance_before_intent_v1","corroborate_before_handoff_v1"),
        mandatory_remediation_ids=("remediate_evidence_completeness_v1","remediate_diagnostic_reasoning_v1","remediate_treatment_alignment_v1"),
        required_positive_evidence_abilities=("inspect_evidence","reason_diagnosis","apply_treatment","ethical_practice"),
        unresolved_serious_abilities=("apply_treatment","ethical_practice"), retake_requires_remediation=True,
    )
    assert policy.retake_requires_remediation


def test_permission_and_inheritance_contracts_are_strict_and_complete():
    permissions = PermissionPolicy.model_validate_json(load("permissions/permission_policy_v1.json"))
    inheritance = InheritanceDefinition.model_validate_json(load("inheritance/trace_vow_restore_v1.json"))
    acceptance = R4AcceptanceContract.model_validate_json(load("inheritance/r4_acceptance_v1.json"))
    assert {item.permission for item in permissions.rules} == set(PermissionLevel)
    assert inheritance.inheritance_id == "trace_vow_restore_v1"
    assert len(acceptance.scenarios) >= 8
    payload = json.loads(load("inheritance/trace_vow_restore_v1.json"))
    payload["hidden_override"] = True
    with pytest.raises(ValidationError):
        InheritanceDefinition.model_validate(payload)


def test_reachability_is_frozen_from_actual_r1_three_case_values():
    definition = InheritanceDefinition.model_validate_json(load("inheritance/trace_vow_restore_v1.json"))
    routes = {item.route_id: item for item in definition.reachability_audit}
    assert routes["excellent_three_case"].expected_inheritance_eligible_after_exam
    assert routes["excellent_three_case"].ability_values["reason_diagnosis"] == 26
    assert routes["excellent_three_case"].relationship_values["recognition"] == 18
    assert not routes["one_wrong_diagnosis"].expected_inheritance_eligible_after_exam
    assert not routes["one_dangerous_treatment"].expected_inheritance_eligible_after_exam


def test_exam_schema_rejects_score_or_section_drift():
    payload = json.loads(load("exams/foundational_xuanyi_exam_v1.json"))
    payload["questions"][0]["score"] = 14
    with pytest.raises(ValidationError):
        ExamDefinition.model_validate(payload)
