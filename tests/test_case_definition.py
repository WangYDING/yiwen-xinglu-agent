import pytest
from pydantic import ValidationError

from xuanyi_npc.domain import CaseActionType, CaseDefinition, TreatmentOutcome


def test_example_case_meets_minimum_technical_spec(
    case_definition: CaseDefinition,
) -> None:
    key_clues = [clue for clue in case_definition.clues.values() if clue.is_key]
    misleading_clues = [
        clue for clue in case_definition.clues.values() if clue.is_misleading
    ]
    investigation_types = {
        investigation.action_type for investigation in case_definition.investigations
    }
    resolving_treatments = [
        treatment
        for treatment in case_definition.treatments.values()
        if treatment.outcome is TreatmentOutcome.RESOLVED
    ]
    error_treatments = [
        treatment
        for treatment in case_definition.treatments.values()
        if treatment.outcome is not TreatmentOutcome.RESOLVED
    ]

    assert 4 <= len(key_clues) <= 6
    assert len(misleading_clues) == 2
    assert len(investigation_types) >= 4
    assert resolving_treatments and len(resolving_treatments) == 1
    assert len(error_treatments) == 2
    assert {hint.level for hint in case_definition.hints} == {1, 2, 3}
    assert case_definition.valid_diagnosis_ids.issubset(
        case_definition.diagnosis_candidates
    )
    assert set(case_definition.diagnosis_candidates).difference(
        case_definition.valid_diagnosis_ids
    )
    assert all(
        investigation.public_description
        for investigation in case_definition.investigations
    )
    assert all(
        treatment.public_description
        for treatment in case_definition.treatments.values()
    )


def test_case_rejects_unknown_action(case_definition: CaseDefinition) -> None:
    data = case_definition.model_dump(mode="json")
    data["investigations"][0]["action_type"] = "invent_truth"

    with pytest.raises(ValidationError):
        CaseDefinition.model_validate(data)


def test_case_rejects_missing_required_field(case_definition: CaseDefinition) -> None:
    data = case_definition.model_dump(mode="json")
    del data["root_cause"]

    with pytest.raises(ValidationError):
        CaseDefinition.model_validate(data)


def test_case_rejects_unknown_clue_reference(case_definition: CaseDefinition) -> None:
    data = case_definition.model_dump(mode="json")
    data["investigations"][0]["reveals_clue_ids"].append("imaginary_clue")

    with pytest.raises(ValidationError, match="unknown clues"):
        CaseDefinition.model_validate(data)


def test_valid_diagnoses_must_reference_public_candidates(
    case_definition: CaseDefinition,
) -> None:
    data = case_definition.model_dump(mode="json")
    data["valid_diagnosis_ids"] = ["different_cause"]

    with pytest.raises(ValidationError, match="public diagnosis candidates"):
        CaseDefinition.model_validate(data)


def test_public_diagnosis_vocabulary_requires_an_incorrect_hypothesis(
    case_definition: CaseDefinition,
) -> None:
    data = case_definition.model_dump(mode="json")
    data["valid_diagnosis_ids"] = list(data["diagnosis_candidates"])

    with pytest.raises(ValidationError, match="incorrect hypothesis"):
        CaseDefinition.model_validate(data)


def test_case_definition_is_immutable(case_definition: CaseDefinition) -> None:
    with pytest.raises(ValidationError):
        case_definition.difficulty = 5


def test_case_investigations_do_not_include_state_mutation_actions(
    case_definition: CaseDefinition,
) -> None:
    forbidden = {
        CaseActionType.SUBMIT_DIAGNOSIS,
        CaseActionType.EXECUTE_TREATMENT,
    }
    assert all(
        investigation.action_type not in forbidden
        for investigation in case_definition.investigations
    )
