"""Immutable case truth and mutable case session state."""

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .base import DomainModel, Identifier, NonEmptyText


BoundedScore = Annotated[StrictInt, Field(ge=0, le=100)]


class CaseActionType(str, Enum):
    OBSERVE_PATIENT = "observe_patient"
    QUESTION_PATIENT = "question_patient"
    INSPECT_OBJECT = "inspect_object"
    OBSERVE_QI = "observe_qi"
    INVESTIGATE_LOCATION = "investigate_location"
    SUBMIT_DIAGNOSIS = "submit_diagnosis"
    EXECUTE_TREATMENT = "execute_treatment"


INVESTIGATION_ACTIONS = frozenset(
    {
        CaseActionType.OBSERVE_PATIENT,
        CaseActionType.QUESTION_PATIENT,
        CaseActionType.INSPECT_OBJECT,
        CaseActionType.OBSERVE_QI,
        CaseActionType.INVESTIGATE_LOCATION,
    }
)


class TreatmentOutcome(str, Enum):
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"
    WORSENED = "worsened"


class CaseSessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"


class PatientDefinition(DomainModel):
    patient_id: Identifier
    display_name: NonEmptyText
    public_profile: NonEmptyText
    hidden_information: tuple[NonEmptyText, ...] = Field(default_factory=tuple)


class ClueDefinition(DomainModel):
    clue_id: Identifier
    description: NonEmptyText
    is_key: StrictBool
    is_misleading: StrictBool = False

    @model_validator(mode="after")
    def validate_clue_role(self) -> "ClueDefinition":
        if self.is_key and self.is_misleading:
            raise ValueError("a clue cannot be both key and misleading")
        return self


class InvestigationDefinition(DomainModel):
    investigation_id: Identifier
    action_type: CaseActionType
    target_id: Identifier
    reveals_clue_ids: frozenset[Identifier] = Field(min_length=1)
    required_skill_id: Identifier | None = None
    minimum_skill_level: BoundedScore = 0
    required_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def validate_investigation(self) -> "InvestigationDefinition":
        if self.action_type not in INVESTIGATION_ACTIONS:
            raise ValueError("investigation must use an investigation action type")
        if self.required_skill_id is None and self.minimum_skill_level != 0:
            raise ValueError("minimum_skill_level requires required_skill_id")
        return self


class TreatmentDefinition(DomainModel):
    treatment_id: Identifier
    description: NonEmptyText
    outcome: TreatmentOutcome
    required_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)


class HintDefinition(DomainModel):
    level: Literal[1, 2, 3]
    text: NonEmptyText
    score_penalty: BoundedScore


class ScoringRule(DomainModel):
    key_clue_points: BoundedScore
    correct_diagnosis_points: BoundedScore
    correct_treatment_points: BoundedScore
    unsafe_treatment_penalty: BoundedScore
    max_score: Annotated[StrictInt, Field(gt=0, le=100)] = 100


class CaseDefinition(DomainModel):
    """World truth. A loaded definition is immutable during a case session."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=True,
    )

    case_id: Identifier
    title: NonEmptyText
    synopsis: NonEmptyText
    difficulty: Annotated[StrictInt, Field(ge=1, le=5)]
    patient: PatientDefinition
    root_cause: Identifier
    causal_chain: tuple[NonEmptyText, ...] = Field(min_length=1)
    clues: dict[Identifier, ClueDefinition] = Field(min_length=1)
    investigations: tuple[InvestigationDefinition, ...] = Field(min_length=1)
    valid_diagnosis_ids: frozenset[Identifier] = Field(min_length=1)
    treatments: dict[Identifier, TreatmentDefinition] = Field(min_length=1)
    hints: tuple[HintDefinition, ...] = Field(min_length=3, max_length=3)
    scoring: ScoringRule

    @model_validator(mode="after")
    def validate_references(self) -> "CaseDefinition":
        clue_ids = set(self.clues)

        for key, clue in self.clues.items():
            if key != clue.clue_id:
                raise ValueError(f"clue map key {key!r} does not match clue_id")

        investigation_ids: set[str] = set()
        for investigation in self.investigations:
            if investigation.investigation_id in investigation_ids:
                raise ValueError("investigation_id values must be unique")
            investigation_ids.add(investigation.investigation_id)

            unknown = (
                investigation.reveals_clue_ids | investigation.required_clue_ids
            ).difference(clue_ids)
            if unknown:
                raise ValueError(
                    f"investigation {investigation.investigation_id!r} references unknown clues"
                )

        resolved_treatments = 0
        for key, treatment in self.treatments.items():
            if key != treatment.treatment_id:
                raise ValueError(f"treatment map key {key!r} does not match treatment_id")
            if not treatment.required_clue_ids.issubset(clue_ids):
                raise ValueError(f"treatment {key!r} references unknown clues")
            if treatment.outcome is TreatmentOutcome.RESOLVED:
                resolved_treatments += 1

        if resolved_treatments != 1:
            raise ValueError("a technical case must have exactly one resolving treatment")

        if self.root_cause not in self.valid_diagnosis_ids:
            raise ValueError("root_cause must be included in valid_diagnosis_ids")

        if {hint.level for hint in self.hints} != {1, 2, 3}:
            raise ValueError("hint levels must contain exactly 1, 2, and 3")

        return self


class ActionRecord(DomainModel):
    sequence: Annotated[StrictInt, Field(ge=1)]
    action_type: CaseActionType
    reference_id: Identifier
    target_id: Identifier
    revealed_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    evidence_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def require_aware_timestamp(self) -> "ActionRecord":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        if self.action_type not in INVESTIGATION_ACTIONS and self.revealed_clue_ids:
            raise ValueError("only investigation actions can reveal clues")
        if (
            self.action_type is not CaseActionType.SUBMIT_DIAGNOSIS
            and self.evidence_clue_ids
        ):
            raise ValueError("only diagnosis actions can cite evidence")
        return self


class CaseSessionState(DomainModel):
    session_id: Identifier
    case_id: Identifier
    player_id: Identifier
    status: CaseSessionStatus = CaseSessionStatus.ACTIVE
    discovered_clue_ids: frozenset[Identifier] = Field(default_factory=frozenset)
    action_history: tuple[ActionRecord, ...] = Field(default_factory=tuple)
    submitted_diagnosis_id: Identifier | None = None
    selected_treatment_id: Identifier | None = None
    outcome: TreatmentOutcome | None = None
    score: BoundedScore | None = None
    revision: Annotated[StrictInt, Field(ge=0)] = 0

    @model_validator(mode="after")
    def validate_session_consistency(self) -> "CaseSessionState":
        sequences = [record.sequence for record in self.action_history]
        if sequences != list(range(1, len(sequences) + 1)):
            raise ValueError("action sequence values must be contiguous and start at 1")

        revealed = set().union(
            *(record.revealed_clue_ids for record in self.action_history)
        ) if self.action_history else set()
        if revealed != set(self.discovered_clue_ids):
            raise ValueError(
                "discovered_clue_ids must exactly match clues revealed by action history"
            )

        completed_fields = (
            self.submitted_diagnosis_id,
            self.selected_treatment_id,
            self.outcome,
            self.score,
        )
        if self.status is CaseSessionStatus.COMPLETED and any(
            field is None for field in completed_fields
        ):
            raise ValueError("a completed session requires diagnosis, treatment, outcome, and score")
        if self.status is CaseSessionStatus.ACTIVE and (
            self.outcome is not None or self.score is not None
        ):
            raise ValueError("an active session cannot have a final outcome or score")
        return self
