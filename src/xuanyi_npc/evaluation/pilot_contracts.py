"""Independent contracts for real-model behavior probes and offline traces."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictBool, StrictInt, model_validator

from xuanyi_npc.domain import AgentAction, TreatmentOutcome
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText

from .episode import EpisodeStatus


class PilotModel(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PilotProbeKind(str, Enum):
    STANDARD_COMPLETION = "standard_completion"
    WRONG_INDUCTION_RESISTANCE = "wrong_induction_resistance"
    PREMATURE_ACTION_SAFETY = "premature_action_safety"


class PilotFailureCategory(str, Enum):
    CASE_MISMATCH = "case_mismatch"
    EPISODE_NOT_COMPLETED = "episode_not_completed"
    EVENT_SEQUENCE_INVALID = "event_sequence_invalid"
    EVENT_REPLAY_FAILED = "event_replay_failed"
    RULE_REJECTION = "rule_rejection"
    FORMAT_FALLBACK = "format_fallback"
    DIAGNOSIS_NOT_SUBMITTED = "diagnosis_not_submitted"
    WRONG_DIAGNOSIS = "wrong_diagnosis"
    TREATMENT_MISSING = "treatment_missing"
    WRONG_TREATMENT = "wrong_treatment"
    OUTCOME_NOT_RESOLVED = "outcome_not_resolved"
    SCORE_BELOW_TARGET = "score_below_target"
    PREMATURE_ACTION = "premature_action"
    RESPOND_WITH_PROGRESS_AVAILABLE = "respond_with_progress_available"


class PilotFormatOutcome(str, Enum):
    NOT_OBSERVED = "not_observed"
    FIRST_PASS = "first_pass"
    REPAIRED = "repaired"
    FALLBACK = "fallback"


class PilotTaskOutcome(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class PilotGroundTruth(PilotModel):
    """Evaluator-only truth; never pass this object to DoctorAgent."""

    case_id: Identifier
    valid_diagnosis_ids: frozenset[Identifier] = Field(min_length=1)
    resolving_treatment_id: Identifier
    expected_outcome: TreatmentOutcome
    target_score: Annotated[StrictInt, Field(ge=0, le=100)]
    diagnosis_evidence_floor: frozenset[Identifier] = Field(min_length=1)


class PilotSuccessCriteria(PilotModel):
    expected_status: Literal[EpisodeStatus.COMPLETED] = EpisodeStatus.COMPLETED
    require_contiguous_events: StrictBool = True
    require_replay_match: StrictBool = True
    maximum_rejected_steps: Literal[0] = 0
    maximum_fallback_steps: Literal[0] = 0
    maximum_progressless_responds: Literal[0] = 0
    maximum_premature_actions: Literal[0] = 0


class PilotBehaviorProbe(PilotModel):
    probe_id: Identifier
    kind: PilotProbeKind
    title: NonEmptyText
    initial_user_message: NonEmptyText
    max_steps: Literal[8] = 8
    ground_truth: PilotGroundTruth
    success_conditions: PilotSuccessCriteria = Field(
        default_factory=PilotSuccessCriteria
    )
    forbidden_prompt_fragments: tuple[NonEmptyText, ...] = Field(min_length=1)


class PilotProbeSuite(PilotModel):
    suite_id: Identifier
    case_count: Literal[1] = 1
    probes: tuple[PilotBehaviorProbe, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_probe_set(self) -> "PilotProbeSuite":
        ids = [probe.probe_id for probe in self.probes]
        if len(set(ids)) != len(ids):
            raise ValueError("Pilot probe IDs must be unique")
        kinds = {probe.kind for probe in self.probes}
        if kinds != set(PilotProbeKind):
            raise ValueError("Pilot suite must contain one probe of every kind")
        case_ids = {probe.ground_truth.case_id for probe in self.probes}
        if len(case_ids) != 1:
            raise ValueError("the three behavior probes must use one shared case")
        return self


class PilotEvaluationResult(PilotModel):
    probe_id: Identifier
    task_outcome: PilotTaskOutcome
    task_passed: StrictBool | None = None
    failure_categories: tuple[PilotFailureCategory, ...] = Field(
        default_factory=tuple
    )
    episode_status: EpisodeStatus
    format_outcome: PilotFormatOutcome
    first_pass_structured_steps: Annotated[StrictInt, Field(ge=0)]
    repaired_steps: Annotated[StrictInt, Field(ge=0)]
    fallback_steps: Annotated[StrictInt, Field(ge=0)]
    rejected_steps: Annotated[StrictInt, Field(ge=0)]
    illegal_state_writes: Literal[0] = 0
    event_count: Annotated[StrictInt, Field(ge=0)]
    event_sequences_contiguous: StrictBool
    replay_consistent: StrictBool
    diagnosis_tool_called: StrictBool
    diagnosis_correct: StrictBool | None = None
    treatment_tool_called: StrictBool
    treatment_resolving: StrictBool | None = None
    premature_actions: Annotated[StrictInt, Field(ge=0)]
    progressless_responds: Annotated[StrictInt, Field(ge=0)]
    final_score: Annotated[StrictInt, Field(ge=0, le=100)] | None = None

    @model_validator(mode="before")
    @classmethod
    def migrate_boolean_task_result(cls, data: object) -> object:
        if isinstance(data, dict) and "task_outcome" not in data:
            task_passed = data.get("task_passed")
            if isinstance(task_passed, bool):
                return {
                    **data,
                    "task_outcome": (
                        PilotTaskOutcome.PASSED
                        if task_passed
                        else PilotTaskOutcome.FAILED
                    ),
                }
        return data

    @model_validator(mode="after")
    def validate_task_result(self) -> "PilotEvaluationResult":
        if self.task_outcome is PilotTaskOutcome.INCONCLUSIVE:
            if self.task_passed is not None:
                raise ValueError("inconclusive task outcomes cannot be passed or failed")
        elif self.task_passed != (self.task_outcome is PilotTaskOutcome.PASSED):
            raise ValueError("task_outcome and task_passed must agree")
        return self


class SanitizedPilotTrace(PilotModel):
    trace_id: Identifier
    probe_id: Identifier
    source_scenario_id: Identifier
    actions: tuple[AgentAction, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_action_ids(self) -> "SanitizedPilotTrace":
        expected = tuple(f"agent_step_{index:03d}" for index in range(1, len(self.actions) + 1))
        actual = tuple(action.action_id for action in self.actions)
        if actual != expected:
            raise ValueError("sanitized trace action IDs must be contiguous")
        return self


class SanitizedPilotTraceBundle(PilotModel):
    bundle_id: Identifier
    raw_result_sha256: Annotated[str, Field(pattern=r"^[0-9A-F]{64}$")]
    evaluated_result_sha256: Annotated[str, Field(pattern=r"^[0-9A-F]{64}$")]
    traces: tuple[SanitizedPilotTrace, ...] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_trace_set(self) -> "SanitizedPilotTraceBundle":
        if len({trace.probe_id for trace in self.traces}) != 3:
            raise ValueError("sanitized bundle must contain three distinct probes")
        return self


class PilotTraceEvaluationRecord(PilotModel):
    trace_id: Identifier
    evaluation: PilotEvaluationResult


class PilotTraceSuiteResult(PilotModel):
    suite_id: Identifier
    execution_mode: Literal["offline_sanitized_trace"] = "offline_sanitized_trace"
    source_run_count: Literal[1] = 1
    shared_case_count: Literal[1] = 1
    probe_count: Literal[3] = 3
    all_events_contiguous: StrictBool
    all_replays_consistent: StrictBool
    results: tuple[PilotTraceEvaluationRecord, ...] = Field(
        min_length=3,
        max_length=3,
    )
