"""Strict contracts for the frozen M4.5 real-semantic memory Pilot."""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator

from xuanyi_npc.domain.base import Identifier, NonEmptyText
from xuanyi_npc.memory.contracts import Sha256Hex, StrictMemoryModel

from .memory_contracts import MemoryGoldQuery, SyntheticMemorySource


SEMANTIC_GOLD_SCHEMA_VERSION = "m45_semantic_gold_v1"
SEMANTIC_METRICS_VERSION = "m45_semantic_metrics_v1"
SEMANTIC_RESULT_VERSION = "m45_semantic_result_v1"
REQUIRED_SEMANTIC_SCENARIOS = (
    "semantic_zh_synonym_001",
    "semantic_action_paraphrase_001",
    "semantic_lexical_distractor_001",
    "semantic_wrong_diagnosis_provenance_001",
    "semantic_current_episode_exclusion_001",
    "semantic_player_isolation_001",
    "semantic_empty_001",
    "semantic_correction_001",
    "semantic_invalidation_001",
    "semantic_hard_delete_001",
    "semantic_prompt_injection_data_001",
    "semantic_mixed_language_entity_001",
    "semantic_short_text_001",
    "semantic_long_text_001",
    "semantic_no_lexical_overlap_001",
)


class SemanticCandidateSetup(str, Enum):
    ACTIVE = "active"
    CORRECT = "correct"
    INVALIDATE = "invalidate"
    HARD_DELETE = "hard_delete"


class SemanticCandidateInput(StrictMemoryModel):
    candidate_id: Identifier
    source: SyntheticMemorySource
    setup: SemanticCandidateSetup = SemanticCandidateSetup.ACTIVE
    replacement_public_content: NonEmptyText | None = None

    @model_validator(mode="after")
    def require_setup_shape(self) -> "SemanticCandidateInput":
        if (self.setup is SemanticCandidateSetup.CORRECT) != (
            self.replacement_public_content is not None
        ):
            raise ValueError("correction replacement content presence is invalid")
        return self


class SemanticScenarioInput(StrictMemoryModel):
    scenario_id: Identifier
    description: NonEmptyText
    player_id: Identifier
    current_session_id: Identifier
    query: MemoryGoldQuery
    candidates: tuple[SemanticCandidateInput, ...] = Field(
        min_length=4,
        max_length=4,
    )
    require_long_text_truncation: StrictBool = False

    @model_validator(mode="after")
    def require_unique_candidates(self) -> "SemanticScenarioInput":
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario candidate IDs must be unique")
        return self


class SemanticGoldSuiteInput(StrictMemoryModel):
    schema_version: Literal["m45_semantic_gold_v1"] = SEMANTIC_GOLD_SCHEMA_VERSION
    suite_id: Identifier
    scenarios: tuple[SemanticScenarioInput, ...] = Field(
        min_length=15,
        max_length=15,
    )

    @model_validator(mode="after")
    def require_frozen_shape(self) -> "SemanticGoldSuiteInput":
        ids = tuple(scenario.scenario_id for scenario in self.scenarios)
        if ids != REQUIRED_SEMANTIC_SCENARIOS:
            raise ValueError("semantic scenarios or order do not match the frozen suite")
        candidate_ids = [
            candidate.candidate_id
            for scenario in self.scenarios
            for candidate in scenario.candidates
        ]
        if len(candidate_ids) != 60 or len(set(candidate_ids)) != 60:
            raise ValueError("semantic Gold requires exactly 60 unique candidates")
        source_refs = [
            candidate.source.source_ref
            for scenario in self.scenarios
            for candidate in scenario.candidates
        ]
        if len(set(source_refs)) != 60:
            raise ValueError("semantic candidate source receipts must be unique")
        if sum(scenario.require_long_text_truncation for scenario in self.scenarios) != 1:
            raise ValueError("exactly one frozen long-text scenario is required")
        return self


class SemanticScenarioExpectation(StrictMemoryModel):
    scenario_id: Identifier
    relevant_candidate_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    forbidden_candidate_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    expected_empty: StrictBool

    @model_validator(mode="after")
    def require_disjoint_sets(self) -> "SemanticScenarioExpectation":
        if len(set(self.relevant_candidate_ids)) != len(self.relevant_candidate_ids):
            raise ValueError("relevant candidate IDs must be unique")
        if len(set(self.forbidden_candidate_ids)) != len(self.forbidden_candidate_ids):
            raise ValueError("forbidden candidate IDs must be unique")
        if set(self.relevant_candidate_ids) & set(self.forbidden_candidate_ids):
            raise ValueError("relevant and forbidden candidate IDs must be disjoint")
        if self.expected_empty != (not self.relevant_candidate_ids):
            raise ValueError("empty expectation must match the relevant set")
        return self


class SemanticGoldSuiteExpectation(StrictMemoryModel):
    schema_version: Literal["m45_semantic_gold_v1"] = SEMANTIC_GOLD_SCHEMA_VERSION
    suite_id: Identifier
    scenarios: tuple[SemanticScenarioExpectation, ...] = Field(
        min_length=15,
        max_length=15,
    )

    @model_validator(mode="after")
    def require_frozen_order(self) -> "SemanticGoldSuiteExpectation":
        if tuple(item.scenario_id for item in self.scenarios) != REQUIRED_SEMANTIC_SCENARIOS:
            raise ValueError("semantic expectations do not match the frozen order")
        return self


class SemanticPreregisteredConfig(StrictMemoryModel):
    model_repository: Literal["BAAI/bge-m3"]
    model_revision: Literal["142964af7e05de16511657561de8e8750fc153a0"]
    model_manifest_sha256: Sha256Hex
    dependency_lock_sha256: Sha256Hex
    embedding_space_id: Literal[
        "bge_m3_142964af7e05_dense_fp32_d1024_cuda_l512_v1"
    ]
    precision: Literal["fp32"]
    device: Literal["cuda"]
    dimension: Literal[1024]
    max_input_characters: Literal[4096]
    max_length_tokens: Literal[512]
    batch_size: Annotated[StrictInt, Field(ge=1, le=64)]
    query_template_version: Literal["memory_query_v1"]
    ranking_top_k: Literal[3]
    ranking_min_similarity: Literal[-1.0]
    calibration_scenario_ids: tuple[Identifier, ...] = Field(min_length=1)
    test_scenario_ids: tuple[Identifier, ...] = Field(min_length=1)
    empty_threshold_grid: tuple[StrictFloat, ...] = Field(min_length=2)
    threshold_selection_version: Literal[
        "empty_accuracy_then_macro_f1_then_higher_threshold_v1"
    ]
    metrics_version: Literal["m45_semantic_metrics_v1"]
    vector_max_abs_difference_tolerance: Annotated[
        StrictFloat,
        Field(ge=0.0, le=0.001),
    ]

    @model_validator(mode="after")
    def require_preregistered_split_and_grid(self) -> "SemanticPreregisteredConfig":
        calibration = set(self.calibration_scenario_ids)
        test = set(self.test_scenario_ids)
        required = set(REQUIRED_SEMANTIC_SCENARIOS)
        if calibration & test or calibration | test != required:
            raise ValueError("calibration and test splits must be disjoint and complete")
        if len(calibration) != 5 or len(test) != 10:
            raise ValueError("semantic split must contain 5 calibration and 10 test scenarios")
        if tuple(sorted(set(self.empty_threshold_grid))) != self.empty_threshold_grid:
            raise ValueError("threshold grid must be unique and ascending")
        if any(not math.isfinite(value) or not -1.0 <= value <= 1.0 for value in self.empty_threshold_grid):
            raise ValueError("threshold grid values must be finite cosine scores")
        return self


class SemanticGoldManifest(StrictMemoryModel):
    schema_version: Literal["m45_semantic_gold_manifest_v1"]
    suite_id: Identifier
    scenario_input_sha256: Sha256Hex
    gold_expectation_sha256: Sha256Hex
    preregistered_config_sha256: Sha256Hex
    preregistered_config: SemanticPreregisteredConfig
    scenario_count: Literal[15]
    query_count: Literal[15]
    candidates_per_scenario: Literal[4]
    candidate_count: Literal[60]
    unique_public_text_count: Literal[75]


class SemanticRankingMetrics(StrictMemoryModel):
    scenario_count: Annotated[StrictInt, Field(ge=0)]
    relevant_scenario_count: Annotated[StrictInt, Field(ge=0)]
    recall_at_1: StrictFloat | None = None
    recall_at_3: StrictFloat | None = None
    mrr: StrictFloat | None = None


class SemanticClassificationMetrics(StrictMemoryModel):
    scenario_count: Annotated[StrictInt, Field(ge=0)]
    macro_precision: StrictFloat | None = None
    macro_recall: StrictFloat | None = None
    macro_f1: StrictFloat | None = None
    macro_precision_denominator: Annotated[StrictInt, Field(ge=0)]
    macro_recall_denominator: Annotated[StrictInt, Field(ge=0)]
    macro_f1_denominator: Annotated[StrictInt, Field(ge=0)]
    micro_true_positive: Annotated[StrictInt, Field(ge=0)]
    micro_false_positive: Annotated[StrictInt, Field(ge=0)]
    micro_false_negative: Annotated[StrictInt, Field(ge=0)]
    micro_precision: StrictFloat | None = None
    micro_recall: StrictFloat | None = None
    micro_f1: StrictFloat | None = None
    empty_correct: Annotated[StrictInt, Field(ge=0)]
    empty_total: Annotated[StrictInt, Field(ge=0)]
    empty_accuracy: StrictFloat | None = None
    false_memory_numerator: Annotated[StrictInt, Field(ge=0)]
    false_memory_denominator: Annotated[StrictInt, Field(ge=0)]
    false_memory_rate: StrictFloat | None = None


class SemanticSafetyCounts(StrictMemoryModel):
    cross_player_recall: Annotated[StrictInt, Field(ge=0)] = 0
    current_episode_recall: Annotated[StrictInt, Field(ge=0)] = 0
    inactive_memory_recall: Annotated[StrictInt, Field(ge=0)] = 0
    deletion_resurrection: Annotated[StrictInt, Field(ge=0)] = 0
    hidden_content_leak: Annotated[StrictInt, Field(ge=0)] = 0
    prompt_boundary_violation: Annotated[StrictInt, Field(ge=0)] = 0
    authority_write_by_embedding: Annotated[StrictInt, Field(ge=0)] = 0
    embedding_space_mixing: Annotated[StrictInt, Field(ge=0)] = 0
    incomplete_index_as_empty: Annotated[StrictInt, Field(ge=0)] = 0

    @property
    def total(self) -> int:
        return sum(self.model_dump().values())


class SemanticScenarioResult(StrictMemoryModel):
    scenario_id: Identifier
    split: Literal["calibration", "test"]
    ranking_candidate_ids: tuple[Identifier, ...]
    ranking_similarities: tuple[StrictFloat, ...]
    threshold_candidate_ids: tuple[Identifier, ...]
    relevant_candidate_ids: tuple[Identifier, ...]
    forbidden_candidate_ids: tuple[Identifier, ...]
    relevant_rank: StrictInt | None = None
    fake_ranking_candidate_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    top_k_overlap_count: Annotated[StrictInt, Field(ge=0, le=3)] = 0
    scoped_candidate_count: Annotated[StrictInt, Field(ge=0)]
    other_player_candidate_count: Annotated[StrictInt, Field(ge=0)] = 0
    current_episode_candidate_count: Annotated[StrictInt, Field(ge=0)] = 0
    long_text_characters: Annotated[StrictInt, Field(ge=0)] | None = None
    long_text_tokens_before_truncation: Annotated[StrictInt, Field(ge=0)] | None = None
    long_text_tokens_after_truncation: Annotated[StrictInt, Field(ge=0)] | None = None
    long_text_was_truncated: StrictBool | None = None


class SemanticRunResourceMetrics(StrictMemoryModel):
    model_load_count: Literal[1]
    local_embedding_batch_count: Annotated[StrictInt, Field(ge=1)]
    local_embedding_text_count: Annotated[StrictInt, Field(ge=1)]
    cold_load_ms: Annotated[StrictFloat, Field(ge=0)]
    first_batch_ms: Annotated[StrictFloat, Field(ge=0)]
    warm_batch_ms: Annotated[StrictFloat, Field(ge=0)] | None = None
    total_embedding_ms: Annotated[StrictFloat, Field(ge=0)]
    peak_process_working_set_bytes: Annotated[StrictInt, Field(ge=0)]
    peak_cuda_allocated_bytes: Annotated[StrictInt, Field(ge=0)]
    peak_cuda_reserved_bytes: Annotated[StrictInt, Field(ge=0)]
    network_attempt_count: Literal[0]
    api_request_count: Literal[0]
    cost_cny: Literal[0.0]


class SemanticRawRunResult(StrictMemoryModel):
    result_version: Literal["m45_semantic_result_v1"] = SEMANTIC_RESULT_VERSION
    run_id: Identifier
    freeze_commit: str
    code_commit: str
    input_sha256: Sha256Hex
    expectation_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    config_sha256: Sha256Hex
    selected_empty_threshold: StrictFloat
    calibration_ranking: SemanticRankingMetrics
    calibration_classification: SemanticClassificationMetrics
    test_ranking: SemanticRankingMetrics
    test_classification: SemanticClassificationMetrics
    safety_counts: SemanticSafetyCounts
    scenarios: tuple[SemanticScenarioResult, ...] = Field(min_length=15, max_length=15)
    ordered_result_sha256: Sha256Hex
    vector_payload_sha256: Sha256Hex
    vector_values_by_text_id: dict[Identifier, tuple[StrictFloat, ...]]
    resources: SemanticRunResourceMetrics

