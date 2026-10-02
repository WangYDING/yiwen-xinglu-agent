"""Strict contracts for the synthetic M4-P4 memory Gold suite."""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator

from xuanyi_npc.domain.base import Identifier, NonEmptyText
from xuanyi_npc.domain.cases import CaseActionType
from xuanyi_npc.memory.contracts import Sha256Hex, StrictMemoryModel, UtcDateTime
from xuanyi_npc.memory.embeddings import MemoryRetrievalConfig
from xuanyi_npc.memory.projection import DEFAULT_PROJECTION_VERSION


MEMORY_GOLD_SCHEMA_VERSION = "memory_gold_v1"
MEMORY_GOLD_RESULT_VERSION = "memory_gold_result_v1"
REQUIRED_MEMORY_GOLD_SCENARIOS = (
    "memory_relevant_recall_001",
    "memory_irrelevant_exclusion_001",
    "memory_player_isolation_001",
    "memory_empty_001",
    "memory_projection_idempotency_001",
    "memory_projection_conflict_001",
    "memory_invalidation_deletion_001",
    "memory_stable_tie_001",
    "memory_prompt_injection_data_001",
    "memory_hidden_truth_filter_001",
    "memory_v0_isolation_001",
    "memory_v1_readonly_001",
    "memory_vector_rebuild_001",
    "memory_commit_window_recovery_001",
)


class MemoryGoldScenarioKind(str, Enum):
    RETRIEVAL = "retrieval"
    IDEMPOTENCY = "idempotency"
    CONFLICT = "conflict"
    LIFECYCLE = "lifecycle"
    PROMPT_INJECTION = "prompt_injection"
    HIDDEN_FILTER = "hidden_filter"
    V0_ISOLATION = "v0_isolation"
    V1_READONLY = "v1_readonly"
    VECTOR_REBUILD = "vector_rebuild"
    COMMIT_RECOVERY = "commit_recovery"


class MemoryGoldOperationType(str, Enum):
    REPEAT_PROJECTION = "repeat_projection"
    CONFLICT_PROJECTION = "conflict_projection"
    CORRECT = "correct"
    INVALIDATE = "invalidate"
    HARD_DELETE = "hard_delete"
    REBUILD_VECTORS = "rebuild_vectors"
    ATTEMPT_AGENT_WRITE = "attempt_agent_write"
    COMMIT_WINDOW_RECOVERY = "commit_window_recovery"


class MemoryEvaluationFailureCategory(str, Enum):
    PROJECTION_NOT_ALLOWED = "projection_not_allowed"
    PROJECTION_CONFLICT = "projection_conflict"
    MISSING_PROVENANCE = "missing_provenance"
    DUPLICATE_MEMORY = "duplicate_memory"
    CROSS_PLAYER_RECALL = "cross_player_recall"
    INACTIVE_MEMORY_RECALLED = "inactive_memory_recalled"
    HIDDEN_CONTENT_LEAK = "hidden_content_leak"
    UNSTABLE_ORDER = "unstable_order"
    ILLEGAL_PERMANENT_WRITE = "illegal_permanent_write"
    V0_MEMORY_ACCESS = "v0_memory_access"
    REBUILD_MISMATCH = "rebuild_mismatch"
    EVALUATION_CONTRACT_ERROR = "evaluation_contract_error"
    GOLD_MISMATCH = "gold_mismatch"
    CURRENT_EPISODE_RECALLED = "current_episode_recalled"
    DELETION_RESURRECTION = "deletion_resurrection"
    PROMPT_STRUCTURE_CHANGED = "prompt_structure_changed"
    COMMIT_RECOVERY_MISMATCH = "commit_recovery_mismatch"
    UNEXPECTED_ERROR = "unexpected_error"


class SyntheticPlayer(StrictMemoryModel):
    player_id: Identifier
    display_name: NonEmptyText


class SyntheticPublicClue(StrictMemoryModel):
    clue_id: Identifier
    description: NonEmptyText


class SyntheticMemorySource(StrictMemoryModel):
    source_ref: Identifier
    player_id: Identifier
    source_session_id: Identifier
    source_event_type: Literal[
        "investigation_completed",
        "diagnosis_submitted",
        "treatment_executed",
    ]
    source_sequence: Annotated[StrictInt, Field(ge=1)]
    source_revision: Annotated[StrictInt, Field(ge=1)]
    occurred_at: UtcDateTime
    case_id: Identifier
    case_title: NonEmptyText
    action_type: CaseActionType
    action_id: Identifier
    public_action_description: NonEmptyText
    public_clues: tuple[SyntheticPublicClue, ...] = Field(default_factory=tuple)
    public_result: NonEmptyText | None = None

    @model_validator(mode="after")
    def require_event_shape(self) -> "SyntheticMemorySource":
        expected_actions = {
            "investigation_completed": {
                CaseActionType.OBSERVE_PATIENT,
                CaseActionType.QUESTION_PATIENT,
                CaseActionType.INSPECT_OBJECT,
                CaseActionType.OBSERVE_QI,
                CaseActionType.INVESTIGATE_LOCATION,
            },
            "diagnosis_submitted": {CaseActionType.SUBMIT_DIAGNOSIS},
            "treatment_executed": {CaseActionType.EXECUTE_TREATMENT},
        }
        if self.action_type not in expected_actions[self.source_event_type]:
            raise ValueError("source event type does not match action type")
        if self.source_event_type == "treatment_executed":
            if self.public_result is None or self.public_clues:
                raise ValueError("treatment source requires only a public result")
        elif self.public_result is not None:
            raise ValueError("only treatment sources can have a public result")
        clue_ids = [item.clue_id for item in self.public_clues]
        if clue_ids != sorted(set(clue_ids)):
            raise ValueError("public clues must be unique and sorted")
        return self


class MemoryGoldQuery(StrictMemoryModel):
    current_user_message: str
    case_title: NonEmptyText
    case_synopsis: NonEmptyText
    discovered_clue_descriptions: tuple[NonEmptyText, ...] = Field(
        default_factory=tuple
    )
    fixed_lesson: NonEmptyText


class MemoryGoldRetrievalConfig(StrictMemoryModel):
    config_id: Identifier
    top_k: Annotated[StrictInt, Field(ge=1, le=20)]
    min_similarity: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]
    embedding_space_id: Identifier
    query_template_version: Literal["memory_query_v1"] = "memory_query_v1"

    def to_domain(self) -> MemoryRetrievalConfig:
        return MemoryRetrievalConfig(
            top_k=self.top_k,
            min_similarity=self.min_similarity,
            embedding_space_id=self.embedding_space_id,
            query_template_version=self.query_template_version,
        )


class MemoryGoldOperation(StrictMemoryModel):
    operation_type: MemoryGoldOperationType
    target_source_ref: Identifier | None = None
    request_id: Identifier | None = None
    replacement_public_content: NonEmptyText | None = None
    conflicting_public_description: NonEmptyText | None = None

    @model_validator(mode="after")
    def require_operation_fields(self) -> "MemoryGoldOperation":
        target_required = self.operation_type in {
            MemoryGoldOperationType.REPEAT_PROJECTION,
            MemoryGoldOperationType.CONFLICT_PROJECTION,
            MemoryGoldOperationType.CORRECT,
            MemoryGoldOperationType.INVALIDATE,
            MemoryGoldOperationType.HARD_DELETE,
        }
        if target_required != (self.target_source_ref is not None):
            raise ValueError("operation target presence is invalid")
        request_required = self.operation_type in {
            MemoryGoldOperationType.CORRECT,
            MemoryGoldOperationType.INVALIDATE,
            MemoryGoldOperationType.HARD_DELETE,
        }
        if request_required != (self.request_id is not None):
            raise ValueError("lifecycle request_id presence is invalid")
        if (self.operation_type is MemoryGoldOperationType.CORRECT) != (
            self.replacement_public_content is not None
        ):
            raise ValueError("correction replacement content presence is invalid")
        if (self.operation_type is MemoryGoldOperationType.CONFLICT_PROJECTION) != (
            self.conflicting_public_description is not None
        ):
            raise ValueError("conflict description presence is invalid")
        return self


class MemoryGoldScenarioInput(StrictMemoryModel):
    scenario_id: Identifier
    kind: MemoryGoldScenarioKind
    description: NonEmptyText
    player_id: Identifier
    current_session_id: Identifier
    source_refs: tuple[Identifier, ...] = Field(default_factory=tuple)
    query: MemoryGoldQuery
    retrieval_config_id: Identifier
    operations: tuple[MemoryGoldOperation, ...] = Field(default_factory=tuple)
    hidden_sentinel_input: str | None = None


class MemoryGoldSuiteInput(StrictMemoryModel):
    schema_version: Literal["memory_gold_v1"] = MEMORY_GOLD_SCHEMA_VERSION
    suite_id: Identifier
    projection_version: Literal["memory_projection_v1"] = DEFAULT_PROJECTION_VERSION
    players: tuple[SyntheticPlayer, ...] = Field(min_length=2)
    sources: dict[Identifier, SyntheticMemorySource] = Field(min_length=1)
    retrieval_configs: dict[Identifier, MemoryGoldRetrievalConfig] = Field(
        min_length=1
    )
    scenarios: tuple[MemoryGoldScenarioInput, ...] = Field(min_length=14, max_length=14)

    @model_validator(mode="after")
    def validate_suite_references(self) -> "MemoryGoldSuiteInput":
        player_ids = [item.player_id for item in self.players]
        if len(set(player_ids)) != len(player_ids):
            raise ValueError("synthetic players must be unique")
        if len(player_ids) < 2:
            raise ValueError("memory Gold requires at least two players")
        for key, source in self.sources.items():
            if key != source.source_ref:
                raise ValueError("source map key must match source_ref")
            if source.player_id not in player_ids:
                raise ValueError("source references an unknown player")
        for key, config in self.retrieval_configs.items():
            if key != config.config_id:
                raise ValueError("retrieval config map key must match config_id")
        scenario_ids = tuple(item.scenario_id for item in self.scenarios)
        if scenario_ids != REQUIRED_MEMORY_GOLD_SCENARIOS:
            raise ValueError("memory Gold scenarios or order do not match the frozen suite")
        for scenario in self.scenarios:
            if scenario.player_id not in player_ids:
                raise ValueError("scenario references an unknown player")
            if scenario.retrieval_config_id not in self.retrieval_configs:
                raise ValueError("scenario references an unknown retrieval config")
            if any(ref not in self.sources for ref in scenario.source_refs):
                raise ValueError("scenario references an unknown source")
            if any(
                operation.target_source_ref not in self.sources
                for operation in scenario.operations
                if operation.target_source_ref is not None
            ):
                raise ValueError("operation references an unknown source")
        return self


class MemoryGoldProjectionExpectation(StrictMemoryModel):
    input_count: Annotated[StrictInt, Field(ge=0)]
    created_count: Annotated[StrictInt, Field(ge=0)]
    idempotent_count: Annotated[StrictInt, Field(ge=0)]
    conflict_count: Annotated[StrictInt, Field(ge=0)]


class MemoryGoldScenarioExpectation(StrictMemoryModel):
    scenario_id: Identifier
    expected_memory_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    forbidden_memory_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    expected_observed_errors: tuple[MemoryEvaluationFailureCategory, ...] = Field(
        default_factory=tuple
    )
    expected_projection: MemoryGoldProjectionExpectation
    expected_empty: StrictBool = False


class MemoryGoldSuiteExpectation(StrictMemoryModel):
    schema_version: Literal["memory_gold_v1"] = MEMORY_GOLD_SCHEMA_VERSION
    suite_id: Identifier
    scenarios: tuple[MemoryGoldScenarioExpectation, ...] = Field(
        min_length=14,
        max_length=14,
    )

    @model_validator(mode="after")
    def validate_scenario_order(self) -> "MemoryGoldSuiteExpectation":
        if tuple(item.scenario_id for item in self.scenarios) != (
            REQUIRED_MEMORY_GOLD_SCENARIOS
        ):
            raise ValueError("Gold expectations do not match the frozen scenario order")
        return self


class MemoryGoldManifest(StrictMemoryModel):
    schema_version: Literal["memory_gold_manifest_v1"] = "memory_gold_manifest_v1"
    suite_id: Identifier
    scenario_input_sha256: Sha256Hex
    gold_expectation_sha256: Sha256Hex
    retrieval_config_sha256: Sha256Hex


class MemoryMetricSet(StrictMemoryModel):
    recalled_count: Annotated[StrictInt, Field(ge=0)]
    ordered_recalled_memory_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    gold_relevant_count: Annotated[StrictInt, Field(ge=0)]
    true_positive: Annotated[StrictInt, Field(ge=0)]
    false_positive: Annotated[StrictInt, Field(ge=0)]
    false_negative: Annotated[StrictInt, Field(ge=0)]
    precision: StrictFloat | None = None
    recall: StrictFloat | None = None
    f1: StrictFloat | None = None
    false_memory_rate: StrictFloat | None = None
    false_memory_numerator: Annotated[StrictInt, Field(ge=0)]
    false_memory_denominator: Annotated[StrictInt, Field(ge=0)]
    empty_correct: StrictBool

    @model_validator(mode="after")
    def require_finite_metrics(self) -> "MemoryMetricSet":
        for value in (self.precision, self.recall, self.f1, self.false_memory_rate):
            if value is not None and (not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("memory metric must be finite and between zero and one")
        if self.false_memory_denominator == 0 and self.false_memory_rate is not None:
            raise ValueError("zero false-memory denominator requires a missing metric")
        return self


class MemorySafetyCounts(StrictMemoryModel):
    cross_player_recall: Annotated[StrictInt, Field(ge=0)] = 0
    illegal_permanent_write: Annotated[StrictInt, Field(ge=0)] = 0
    hidden_content_leak: Annotated[StrictInt, Field(ge=0)] = 0
    deletion_resurrection: Annotated[StrictInt, Field(ge=0)] = 0
    v0_memory_access: Annotated[StrictInt, Field(ge=0)] = 0
    inactive_memory_recalled: Annotated[StrictInt, Field(ge=0)] = 0
    missing_provenance: Annotated[StrictInt, Field(ge=0)] = 0
    current_episode_recall: Annotated[StrictInt, Field(ge=0)] = 0
    prompt_boundary_violation: Annotated[StrictInt, Field(ge=0)] = 0

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())


class MemoryProjectionCounts(StrictMemoryModel):
    input_count: Annotated[StrictInt, Field(ge=0)] = 0
    created_count: Annotated[StrictInt, Field(ge=0)] = 0
    idempotent_count: Annotated[StrictInt, Field(ge=0)] = 0
    conflict_count: Annotated[StrictInt, Field(ge=0)] = 0
    source_receipt_count: Annotated[StrictInt, Field(ge=0)] = 0
    authoritative_memory_count: Annotated[StrictInt, Field(ge=0)] = 0
    indexed_memory_count: Annotated[StrictInt, Field(ge=0)] = 0


class MemoryEvaluationCallCounts(StrictMemoryModel):
    repository_reads: Annotated[StrictInt, Field(ge=0)] = 0
    repository_writes: Annotated[StrictInt, Field(ge=0)] = 0
    embedding_batches: Annotated[StrictInt, Field(ge=0)] = 0
    retrievals: Annotated[StrictInt, Field(ge=0)] = 0
    query_builds: Annotated[StrictInt, Field(ge=0)] = 0
    llm_calls: Annotated[StrictInt, Field(ge=0)] = 0


class MemoryEvaluationObservation(StrictMemoryModel):
    elapsed_ms: Annotated[StrictFloat, Field(ge=0)]
    sqlite_size_bytes: Annotated[StrictInt, Field(ge=0)]


class MemoryScenarioEvaluationResult(StrictMemoryModel):
    result_version: Literal["memory_gold_result_v1"] = MEMORY_GOLD_RESULT_VERSION
    scenario_id: Identifier
    passed: StrictBool
    metrics: MemoryMetricSet
    safety_counts: MemorySafetyCounts
    projection_counts: MemoryProjectionCounts
    call_counts: MemoryEvaluationCallCounts
    observed_control_errors: tuple[MemoryEvaluationFailureCategory, ...] = Field(
        default_factory=tuple
    )
    failure_categories: tuple[MemoryEvaluationFailureCategory, ...] = Field(
        default_factory=tuple
    )
    safe_reason_code: Identifier | None = None
    memory_content_hashes: tuple[Sha256Hex, ...] = Field(default_factory=tuple)
    source_payload_hashes: tuple[Sha256Hex, ...] = Field(default_factory=tuple)
    lifecycle_statuses: tuple[str, ...] = Field(default_factory=tuple)
    index_status: Identifier | None = None
    logical_snapshot_sha256: Sha256Hex
    deterministic_result_sha256: Sha256Hex
    observation: MemoryEvaluationObservation

    @model_validator(mode="after")
    def require_safe_failure_shape(self) -> "MemoryScenarioEvaluationResult":
        if self.passed:
            if self.failure_categories or self.safe_reason_code is not None:
                raise ValueError("passed result cannot contain a failure reason")
        elif not self.failure_categories or self.safe_reason_code is None:
            raise ValueError("failed result requires a safe failure reason")
        return self


class MemoryAggregateMetrics(StrictMemoryModel):
    macro_precision: StrictFloat | None = None
    macro_recall: StrictFloat | None = None
    macro_f1: StrictFloat | None = None
    macro_precision_scenarios: Annotated[StrictInt, Field(ge=0)]
    macro_recall_scenarios: Annotated[StrictInt, Field(ge=0)]
    macro_f1_scenarios: Annotated[StrictInt, Field(ge=0)]
    micro_true_positive: Annotated[StrictInt, Field(ge=0)]
    micro_false_positive: Annotated[StrictInt, Field(ge=0)]
    micro_false_negative: Annotated[StrictInt, Field(ge=0)]
    micro_precision: StrictFloat | None = None
    micro_recall: StrictFloat | None = None
    micro_f1: StrictFloat | None = None
    false_memory_numerator: Annotated[StrictInt, Field(ge=0)]
    false_memory_denominator: Annotated[StrictInt, Field(ge=0)]
    false_memory_rate: StrictFloat | None = None
    empty_correct_scenarios: Annotated[StrictInt, Field(ge=0)]


class MemoryEvaluationIdentity(StrictMemoryModel):
    code_commit: str
    scenario_input_sha256: Sha256Hex
    gold_expectation_sha256: Sha256Hex
    retrieval_config_sha256: Sha256Hex
    fake_embedding_algorithm: Identifier
    fake_embedding_dimension: Annotated[StrictInt, Field(ge=1)]
    embedding_space_id: Identifier
    projection_version: Identifier
    sqlite_schema_version: Annotated[StrictInt, Field(ge=1)]
    python_version: str
    operating_system: str


class MemoryEvaluationReport(StrictMemoryModel):
    report_version: Literal["memory_gold_report_v1"] = "memory_gold_report_v1"
    suite_id: Identifier
    execution_mode: Literal["synthetic_fake_embedding_offline"] = (
        "synthetic_fake_embedding_offline"
    )
    scenario_count: Literal[14] = 14
    repetition_count: Literal[2] = 2
    all_scenarios_passed: StrictBool
    reproducible: StrictBool
    deterministic_run_hashes: tuple[Sha256Hex, Sha256Hex]
    scenarios: tuple[MemoryScenarioEvaluationResult, ...] = Field(
        min_length=14,
        max_length=14,
    )
    aggregate_metrics: MemoryAggregateMetrics
    safety_totals: MemorySafetyCounts
    identity: MemoryEvaluationIdentity
    latency_sample_count: Annotated[StrictInt, Field(ge=0)]
    latency_percentile_method: Literal["nearest_rank_sorted_n"] = (
        "nearest_rank_sorted_n"
    )
    elapsed_ms_p50: StrictFloat | None = None
    elapsed_ms_p95: StrictFloat | None = None
    sqlite_size_bytes_total: Annotated[StrictInt, Field(ge=0)]
    metric_scope_note: Literal[
        "synthetic Gold with deterministic Fake Embedding only"
    ] = "synthetic Gold with deterministic Fake Embedding only"
