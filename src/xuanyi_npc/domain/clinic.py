"""Strict frozen R5 clinic, curriculum-v2, and acceptance contracts."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from .base import DomainModel, Identifier, NonEmptyText
from .permissions import PermissionLevel


class ClinicModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CurriculumV2Step(ClinicModel):
    priority: Annotated[StrictInt, Field(ge=1)]
    condition_code: Identifier
    recommendation_kind: Identifier
    recommendation_id: Identifier
    does_not_lock_cases: Literal[True] = True


class CurriculumSelectionV2(ClinicModel):
    policy_id: Literal["curriculum_selection_v2"]
    version: Literal["v2"]
    preserves_policy_id: Literal["curriculum_selection_v1"]
    foundation_lesson_order: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    advanced_lesson_order: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    steps: tuple[CurriculumV2Step, ...] = Field(min_length=7)
    completion_recommendation_id: Literal["current_training_complete"]

    @model_validator(mode="after")
    def stable_priority(self) -> "CurriculumSelectionV2":
        priorities = tuple(item.priority for item in self.steps)
        if priorities != tuple(sorted(priorities)) or len(priorities) != len(set(priorities)):
            raise ValueError("curriculum v2 priorities must be unique and ascending")
        return self


class ClinicPage(str, Enum):
    START = "start"
    HOME = "home"
    TEACHING = "teaching"
    CASE = "case"
    EXAM = "exam"
    INHERITANCE = "inheritance"
    ASSESSMENT = "assessment"


class ClinicRoute(ClinicModel):
    method: Literal["GET", "POST"]
    path: str
    page: ClinicPage
    operation_id: Identifier
    idempotency_required: StrictBool


class ClinicContract(ClinicModel):
    contract_id: Literal["clinic_contract_v1"]
    version: Literal["v1"]
    host: Literal["127.0.0.1"]
    default_port: Literal[0]
    mentor_mode: Literal["fake"]
    semantic_memory: Literal["off"]
    entrypoint: Literal["xuanyi-clinic"]
    pages: tuple[ClinicPage, ...] = Field(min_length=7, max_length=7)
    routes: tuple[ClinicRoute, ...] = Field(min_length=12)
    forbidden_public_fields: tuple[Identifier, ...] = Field(min_length=10)
    static_asset_names: tuple[str, ...] = Field(min_length=2)
    fictional_safety_notice: NonEmptyText

    @model_validator(mode="after")
    def validate_routes(self) -> "ClinicContract":
        if set(self.pages) != set(ClinicPage):
            raise ValueError("clinic contract must define every frozen page")
        keys = {(item.method, item.path) for item in self.routes}
        if len(keys) != len(self.routes):
            raise ValueError("clinic routes must be unique")
        if any(item.method == "POST" and not item.idempotency_required for item in self.routes):
            raise ValueError("all clinic writes require idempotency")
        return self


class AdvancedCaseContract(ClinicModel):
    case_id: Identifier
    lesson_id: Identifier
    correct_diagnosis_id: Identifier
    resolved_treatment_id: Identifier
    suppressed_treatment_id: Identifier
    worsened_treatment_id: Identifier
    gold_investigation_orders: tuple[tuple[Identifier, ...], ...] = Field(min_length=2)
    inheritance_investigation_id: Identifier | None = None
    inheritance_permission: PermissionLevel | None = None
    ordinary_path_max_score: Literal[100]
    inheritance_path_max_score: Literal[100]

    @model_validator(mode="after")
    def inheritance_pair(self) -> "AdvancedCaseContract":
        if (self.inheritance_investigation_id is None) != (self.inheritance_permission is None):
            raise ValueError("inheritance investigation and permission must be paired")
        return self


class R5AcceptanceScenario(ClinicModel):
    scenario_id: Identifier
    steps: tuple[NonEmptyText, ...] = Field(min_length=1)
    expected_case_ids: tuple[Identifier, ...]
    expected_score: Annotated[StrictInt, Field(ge=0, le=100)] | None = None
    expected_public_facts: tuple[NonEmptyText, ...]
    forbidden_public_facts: tuple[NonEmptyText, ...]


class R5AcceptanceContract(ClinicModel):
    contract_id: Literal["r5_acceptance_v1"]
    version: Literal["v1"]
    case_order: tuple[Identifier, ...] = Field(min_length=6, max_length=6)
    advanced_cases: tuple[AdvancedCaseContract, ...] = Field(min_length=3, max_length=3)
    scenarios: tuple[R5AcceptanceScenario, ...] = Field(min_length=7)
    mcp_tool_count_unchanged: Literal[9]
    r4_contract_revision: Literal["r4_contract_v1"]
    external_calls_expected: Literal[0]

