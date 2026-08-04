"""Strict contracts for the supplier-independent M2b-P0 dev suite."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from xuanyi_npc.domain import AgentAction, TreatmentOutcome
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.engine import ScoreBreakdown

from .episode import EpisodeStatus


class DevModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DevFailureCategory(str, Enum):
    CASE_MISMATCH = "case_mismatch"
    EPISODE_NOT_COMPLETED = "episode_not_completed"
    EVENT_SEQUENCE_INVALID = "event_sequence_invalid"
    EVENT_REPLAY_FAILED = "event_replay_failed"
    EVENT_COUNT_MISMATCH = "event_count_mismatch"
    RULE_REJECTION = "rule_rejection"
    DIAGNOSIS_MISSING = "diagnosis_missing"
    WRONG_HYPOTHESIS = "wrong_hypothesis"
    TREATMENT_MISSING = "treatment_missing"
    TREATMENT_MISMATCH = "treatment_mismatch"
    OUTCOME_MISMATCH = "outcome_mismatch"
    SCORE_MISMATCH = "score_mismatch"
    REQUIRED_RECOVERY_MISSING = "required_recovery_missing"
    FORMAT_RECOVERY_FAILED = "format_recovery_failed"
    UNEXPECTED_MEASURED_USAGE = "unexpected_measured_usage"


class DevGroundTruth(DevModel):
    """Evaluator-only truth. This object must never enter DoctorAgent input."""

    case_id: Identifier
    valid_diagnosis_ids: frozenset[Identifier] = Field(min_length=1)
    resolving_treatment_id: Identifier
    expected_outcome: TreatmentOutcome
    expected_score_breakdown: ScoreBreakdown


class DevSuccessCriteria(DevModel):
    expected_status: Literal[EpisodeStatus.COMPLETED] = EpisodeStatus.COMPLETED
    expected_event_count: Annotated[StrictInt, Field(ge=1, le=100)]
    require_contiguous_events: StrictBool = True
    require_replay_match: StrictBool = True
    minimum_repaired_steps: Annotated[StrictInt, Field(ge=0, le=2)] = 0
    maximum_rejected_steps: Annotated[StrictInt, Field(ge=0, le=100)] = 0
    maximum_fallback_steps: Annotated[StrictInt, Field(ge=0, le=100)] = 0
    require_unmeasured_usage: StrictBool = True


class DevFailureCondition(DevModel):
    category: DevFailureCategory
    description: NonEmptyText


class ScriptedActionOutput(DevModel):
    output_type: Literal["action"] = "action"
    action_ref: Identifier


class ScriptedRawOutput(DevModel):
    output_type: Literal["raw"] = "raw"
    content: NonEmptyText


DevScriptedOutput = Annotated[
    ScriptedActionOutput | ScriptedRawOutput,
    Field(discriminator="output_type"),
]


class DevScript(DevModel):
    script_id: Identifier
    outputs: tuple[DevScriptedOutput, ...] = Field(min_length=1)


class DevTrajectoryRole(str, Enum):
    REFERENCE = "reference"
    EXPLICIT_ERROR = "explicit_error"


class DevTrajectoryExpectation(DevModel):
    task_passed: StrictBool
    required_failure_categories: frozenset[DevFailureCategory] = Field(
        default_factory=frozenset
    )
    forbidden_failure_categories: frozenset[DevFailureCategory] = Field(
        default_factory=frozenset
    )

    @model_validator(mode="after")
    def validate_expectation(self) -> "DevTrajectoryExpectation":
        if self.task_passed and self.required_failure_categories:
            raise ValueError("passing trajectories cannot require failure categories")
        overlap = self.required_failure_categories.intersection(
            self.forbidden_failure_categories
        )
        if overlap:
            raise ValueError("required and forbidden failure categories cannot overlap")
        return self


class DevTrajectorySpec(DevModel):
    trajectory_id: Identifier
    role: DevTrajectoryRole
    script_id: Identifier
    expectation: DevTrajectoryExpectation


class DevScenario(DevModel):
    scenario_id: Identifier
    title: NonEmptyText
    initial_user_message: NonEmptyText
    max_steps: Annotated[StrictInt, Field(ge=1, le=100)]
    ground_truth: DevGroundTruth
    success_conditions: DevSuccessCriteria
    failure_conditions: tuple[DevFailureCondition, ...] = Field(min_length=1)
    forbidden_prompt_fragments: tuple[NonEmptyText, ...] = Field(min_length=1)
    trajectories: tuple[DevTrajectorySpec, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_trajectory_roles(self) -> "DevScenario":
        references = [
            trajectory
            for trajectory in self.trajectories
            if trajectory.role is DevTrajectoryRole.REFERENCE
        ]
        errors = [
            trajectory
            for trajectory in self.trajectories
            if trajectory.role is DevTrajectoryRole.EXPLICIT_ERROR
        ]
        if len(references) != 1:
            raise ValueError("each dev scenario requires exactly one reference trajectory")
        if not errors:
            raise ValueError("each dev scenario requires an explicit error trajectory")
        if not references[0].expectation.task_passed:
            raise ValueError("the reference trajectory must be expected to pass")
        if any(trajectory.expectation.task_passed for trajectory in errors):
            raise ValueError("explicit error trajectories must be expected to fail")
        condition_categories = {
            condition.category for condition in self.failure_conditions
        }
        required_categories = set().union(
            *(
                trajectory.expectation.required_failure_categories
                for trajectory in errors
            )
        )
        if not required_categories.issubset(condition_categories):
            raise ValueError(
                "trajectory failure expectations must be declared as failure conditions"
            )
        return self


class DevSuiteDefinition(DevModel):
    suite_id: Identifier
    actions: dict[Identifier, AgentAction] = Field(min_length=1)
    scripts: dict[Identifier, DevScript] = Field(min_length=1)
    scenarios: tuple[DevScenario, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_references(self) -> "DevSuiteDefinition":
        for key, script in self.scripts.items():
            if key != script.script_id:
                raise ValueError("script map key must match script_id")
        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(set(scenario_ids)) != len(scenario_ids):
            raise ValueError("scenario_id values must be unique")
        unknown_scripts = {
            trajectory.script_id
            for scenario in self.scenarios
            for trajectory in scenario.trajectories
            if trajectory.script_id not in self.scripts
        }
        if unknown_scripts:
            raise ValueError("dev trajectories reference unknown scripts")
        unknown_actions = {
            output.action_ref
            for script in self.scripts.values()
            for output in script.outputs
            if isinstance(output, ScriptedActionOutput)
            and output.action_ref not in self.actions
        }
        if unknown_actions:
            raise ValueError("dev scripts reference unknown actions")
        return self


class DevEvaluationResult(DevModel):
    scenario_id: Identifier
    trajectory_id: Identifier
    task_passed: StrictBool
    failure_categories: tuple[DevFailureCategory, ...] = Field(default_factory=tuple)
    episode_status: EpisodeStatus
    final_score: Annotated[StrictInt, Field(ge=0, le=100)] | None = None
    step_count: Annotated[StrictInt, Field(ge=0)]
    event_count: Annotated[StrictInt, Field(ge=0)]
    final_revision: Annotated[StrictInt, Field(ge=0)]
    replay_consistent: StrictBool
    rejected_steps: Annotated[StrictInt, Field(ge=0)]
    repaired_steps: Annotated[StrictInt, Field(ge=0)]
    fallback_steps: Annotated[StrictInt, Field(ge=0)]
    usage_measured: StrictBool


class DevTrajectoryRunResult(DevModel):
    scenario_id: Identifier
    trajectory_id: Identifier
    role: DevTrajectoryRole
    expectation_matched: StrictBool
    context_safe: StrictBool
    leaked_prompt_fragments: tuple[NonEmptyText, ...] = Field(default_factory=tuple)
    evaluation: DevEvaluationResult


class DevSuiteRunResult(DevModel):
    suite_id: Identifier
    execution_mode: Literal["fake_llm_deterministic"] = "fake_llm_deterministic"
    measurement_status: Literal["not_measured"] = "not_measured"
    scenario_count: Annotated[StrictInt, Field(ge=1)]
    trajectory_count: Annotated[StrictInt, Field(ge=1)]
    all_expectations_matched: StrictBool
    results: tuple[DevTrajectoryRunResult, ...] = Field(min_length=1)
