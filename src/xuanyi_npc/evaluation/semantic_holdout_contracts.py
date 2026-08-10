"""Strict frozen contracts for the unseen M4.5 semantic holdout."""

from __future__ import annotations

import math
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt, model_validator

from xuanyi_npc.domain.base import Identifier, NonEmptyText
from xuanyi_npc.memory.contracts import Sha256Hex, StrictMemoryModel

from .memory_contracts import SyntheticMemorySource


HOLDOUT_SCHEMA_VERSION = "m45_semantic_holdout_v1"
HOLDOUT_GOLD_VERSION = "m45_semantic_holdout_gold_v1"
HOLDOUT_CONFIG_VERSION = "m45_semantic_holdout_config_v1"
HOLDOUT_MANIFEST_VERSION = "m45_semantic_holdout_manifest_v1"
OBSERVED_DEVELOPMENT_SUITE_ID = "m45_semantic_gold_001"


class HoldoutSplit(str, Enum):
    CALIBRATION = "calibration"
    FINAL_TEST = "final_test"


class HoldoutSlice(str, Enum):
    CORRECTION = "correction"
    SHORT_TEXT = "short_text"
    NEGATION = "negation_antonym"
    LEXICAL_DISTRACTOR = "lexical_distractor"
    ZH_SYNONYM = "zh_synonym"
    MIXED_LANGUAGE = "mixed_language"
    LONG_TEXT = "long_text_truncation"
    MULTI_RELEVANT = "multi_relevant"
    EMPTY = "empty"
    PROMPT_INJECTION = "prompt_injection_data"
    NO_LEXICAL_OVERLAP = "no_lexical_overlap"
    ACTION_PARAPHRASE = "action_paraphrase"
    DIAGNOSIS_PROVENANCE = "diagnosis_provenance"
    CROSS_PLAYER = "cross_player"
    CURRENT_EPISODE = "current_episode"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    HARD_DELETED = "hard_deleted"


class HoldoutCandidateSetup(str, Enum):
    ACTIVE = "active"
    CORRECTED_ACTIVE = "corrected_active"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    HARD_DELETED = "hard_deleted"


class HoldoutSafetyReason(str, Enum):
    CROSS_PLAYER = "cross_player"
    CURRENT_EPISODE = "current_episode"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    HARD_DELETED = "hard_deleted"


class HoldoutCandidateInput(StrictMemoryModel):
    candidate_id: Identifier
    source: SyntheticMemorySource
    setup: HoldoutCandidateSetup = HoldoutCandidateSetup.ACTIVE
    replacement_public_content: NonEmptyText | None = None

    @model_validator(mode="after")
    def require_lifecycle_shape(self) -> "HoldoutCandidateInput":
        needs_replacement = self.setup in {
            HoldoutCandidateSetup.CORRECTED_ACTIVE,
            HoldoutCandidateSetup.SUPERSEDED,
        }
        if needs_replacement != (self.replacement_public_content is not None):
            raise ValueError("holdout correction setup has an invalid replacement")
        return self


class HoldoutQueryInput(StrictMemoryModel):
    retrieval_intent: NonEmptyText
    discovered_clue_descriptions: tuple[NonEmptyText, ...] = Field(
        default_factory=tuple
    )


class HoldoutScenarioInput(StrictMemoryModel):
    scenario_id: Identifier
    split: HoldoutSplit
    description: NonEmptyText
    slice_tags: tuple[HoldoutSlice, ...] = Field(min_length=1)
    player_id: Identifier
    current_session_id: Identifier
    query: HoldoutQueryInput
    candidates: tuple[HoldoutCandidateInput, ...] = Field(min_length=4, max_length=4)
    require_character_truncation: StrictBool = False
    require_tokenizer_truncation_observation: StrictBool = False

    @model_validator(mode="after")
    def require_unique_shape(self) -> "HoldoutScenarioInput":
        candidate_ids = tuple(item.candidate_id for item in self.candidates)
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("holdout candidate IDs must be unique per scenario")
        if self.slice_tags != tuple(dict.fromkeys(self.slice_tags)):
            raise ValueError("holdout slice tags must be unique and stable")
        return self


class HoldoutSuiteInput(StrictMemoryModel):
    schema_version: Literal["m45_semantic_holdout_v1"] = HOLDOUT_SCHEMA_VERSION
    suite_id: Literal["m45_semantic_holdout_001"]
    observed_development_suite_id: Literal["m45_semantic_gold_001"]
    scenarios: tuple[HoldoutScenarioInput, ...] = Field(min_length=36, max_length=36)

    @model_validator(mode="after")
    def require_frozen_counts(self) -> "HoldoutSuiteInput":
        scenario_ids = tuple(item.scenario_id for item in self.scenarios)
        if scenario_ids != tuple(sorted(scenario_ids)):
            raise ValueError("holdout scenarios must use stable scenario_id order")
        if len(set(scenario_ids)) != 36:
            raise ValueError("holdout scenario IDs must be unique")
        calibration = tuple(
            item for item in self.scenarios if item.split is HoldoutSplit.CALIBRATION
        )
        final_test = tuple(
            item for item in self.scenarios if item.split is HoldoutSplit.FINAL_TEST
        )
        if len(calibration) != 12 or len(final_test) != 24:
            raise ValueError("holdout split must be calibration=12 and final_test=24")
        candidate_ids = tuple(
            candidate.candidate_id
            for scenario in self.scenarios
            for candidate in scenario.candidates
        )
        if len(candidate_ids) != 144 or len(set(candidate_ids)) != 144:
            raise ValueError("holdout must contain 144 unique raw candidates")
        return self


class HoldoutSafetyExcluded(StrictMemoryModel):
    candidate_id: Identifier
    reason: HoldoutSafetyReason


class HoldoutScenarioExpectation(StrictMemoryModel):
    scenario_id: Identifier
    relevant_candidate_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    semantic_negative_candidate_ids: tuple[Identifier, ...] = Field(
        default_factory=tuple
    )
    safety_excluded_candidates: tuple[HoldoutSafetyExcluded, ...] = Field(
        default_factory=tuple
    )
    expected_empty: StrictBool

    @model_validator(mode="after")
    def require_partition(self) -> "HoldoutScenarioExpectation":
        groups = (
            self.relevant_candidate_ids,
            self.semantic_negative_candidate_ids,
            tuple(item.candidate_id for item in self.safety_excluded_candidates),
        )
        for values in groups:
            if len(values) != len(set(values)):
                raise ValueError("holdout partition IDs must be unique")
        if any(
            set(left) & set(right)
            for index, left in enumerate(groups)
            for right in groups[index + 1 :]
        ):
            raise ValueError("holdout candidate partitions must be disjoint")
        if sum(len(group) for group in groups) != 4:
            raise ValueError("holdout partitions must cover exactly four candidates")
        if self.expected_empty != (not self.relevant_candidate_ids):
            raise ValueError("holdout empty expectation must match relevant candidates")
        return self


class HoldoutSuiteExpectation(StrictMemoryModel):
    schema_version: Literal["m45_semantic_holdout_gold_v1"] = HOLDOUT_GOLD_VERSION
    suite_id: Literal["m45_semantic_holdout_001"]
    scenarios: tuple[HoldoutScenarioExpectation, ...] = Field(
        min_length=36,
        max_length=36,
    )


class ConservativeParameter(StrictMemoryModel):
    min_similarity: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]
    max_results: Annotated[StrictInt, Field(ge=1, le=3)]
    minimum_margin: Annotated[StrictFloat, Field(ge=0.0, le=2.0)]


class HoldoutAdmissionThresholds(StrictMemoryModel):
    recall_at_1_minimum: Literal[0.8]
    recall_at_3_minimum: Literal[0.9]
    mrr_minimum: Literal[0.85]
    macro_f1_minimum: Literal[0.8]
    micro_f1_minimum: Literal[0.8]
    irrelevant_retrieval_rate_maximum: Literal[0.1]
    empty_accuracy_required: Literal[1.0]
    correction_false_negative_required: Literal[0]
    negation_false_negative_required: Literal[0]
    safety_total_required: Literal[0]
    repeated_order_and_metrics_identical: Literal[True]
    vector_max_abs_difference: Literal[0.000001]


class HoldoutPreregisteredConfig(StrictMemoryModel):
    config_version: Literal["m45_semantic_holdout_config_v1"]
    model_repository: Literal["BAAI/bge-m3"]
    model_revision: Literal["142964af7e05de16511657561de8e8750fc153a0"]
    model_manifest_sha256: Sha256Hex
    dependency_lock_sha256: Sha256Hex
    embedding_space_id: Literal[
        "bge_m3_142964af_dense_fp32_d1024_cuda_l512_rq2_doc2_v1"
    ]
    precision: Literal["fp32"]
    device: Literal["cuda"]
    dimension: Literal[1024]
    max_length_tokens: Literal[512]
    query_template_version: Literal["retrieval_query_v2"]
    document_template_version: Literal["embedding_document_v2"]
    normalization_version: Literal["nfkc_casefold_ws_v2"]
    truncation_version: Literal["unicode_codepoint_prefix_v2"]
    ranking_order: Literal["similarity_desc_memory_id_asc"]
    parameter_grid: tuple[ConservativeParameter, ...] = Field(min_length=2)
    selection_objective_version: Literal[
        "safety_empty_macrof1_recall3_mrr_irr_conservative_v1"
    ]
    no_valid_parameter_behavior: Literal["fail_calibration"]
    calibration_scenario_ids: tuple[Identifier, ...] = Field(min_length=12, max_length=12)
    final_test_scenario_ids: tuple[Identifier, ...] = Field(min_length=24, max_length=24)
    metrics_version: Literal["semantic_holdout_metrics_v1"]
    admission: HoldoutAdmissionThresholds
    formal_run_limit: Literal[2]
    real_vector_run_authorized: Literal[False]

    @model_validator(mode="after")
    def require_grid_and_split(self) -> "HoldoutPreregisteredConfig":
        if set(self.calibration_scenario_ids) & set(self.final_test_scenario_ids):
            raise ValueError("holdout calibration and final test must be disjoint")
        if len(set(self.parameter_grid)) != len(self.parameter_grid):
            raise ValueError("holdout parameter grid must be unique")
        expected = tuple(
            sorted(
                self.parameter_grid,
                key=lambda item: (
                    item.min_similarity,
                    item.max_results,
                    item.minimum_margin,
                ),
            )
        )
        if self.parameter_grid != expected:
            raise ValueError("holdout parameter grid order must be stable")
        return self


class HoldoutManifest(StrictMemoryModel):
    schema_version: Literal["m45_semantic_holdout_manifest_v1"]
    suite_id: Literal["m45_semantic_holdout_001"]
    input_path: NonEmptyText
    expectation_path: NonEmptyText
    config_path: NonEmptyText
    input_sha256: Sha256Hex
    expectation_sha256: Sha256Hex
    config_sha256: Sha256Hex
    observed_development_input_sha256: Sha256Hex
    scenario_count: Literal[36]
    calibration_count: Literal[12]
    calibration_relevant_count: Literal[8]
    calibration_empty_count: Literal[4]
    final_test_count: Literal[24]
    final_test_relevant_count: Literal[20]
    final_test_empty_count: Literal[4]
    candidates_per_scenario: Literal[4]
    candidate_count: Literal[144]
    input_texts_are_synthetic_public_only: Literal[True]
    bge_loaded_or_run: Literal[False]


class HoldoutPolicyMetrics(StrictMemoryModel):
    macro_f1: StrictFloat | None
    recall_at_3: StrictFloat | None
    mrr: StrictFloat | None
    irrelevant_retrieval_rate: StrictFloat | None
    empty_accuracy: StrictFloat | None
    safety_total: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def require_finite_metrics(self) -> "HoldoutPolicyMetrics":
        for value in self.model_dump().values():
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("holdout policy metrics must be finite when defined")
        return self


class CalibrationPolicyOutcome(StrictMemoryModel):
    parameter: ConservativeParameter
    evaluated_scenario_ids: tuple[Identifier, ...]
    metrics: HoldoutPolicyMetrics


class LockedConservativePolicy(StrictMemoryModel):
    selection_version: Literal[
        "safety_empty_macrof1_recall3_mrr_irr_conservative_v1"
    ]
    parameter: ConservativeParameter


class HoldoutScenarioPrediction(StrictMemoryModel):
    scenario_id: Identifier
    ranked_candidate_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    returned_candidate_ids: tuple[Identifier, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def require_unique_predictions(self) -> "HoldoutScenarioPrediction":
        if len(set(self.ranked_candidate_ids)) != len(self.ranked_candidate_ids):
            raise ValueError("ranked candidate IDs must be unique")
        if len(set(self.returned_candidate_ids)) != len(self.returned_candidate_ids):
            raise ValueError("returned candidate IDs must be unique")
        return self


class HoldoutEvaluationMetrics(StrictMemoryModel):
    relevant_scenario_count: Annotated[StrictInt, Field(ge=0)]
    recall_at_1: StrictFloat | None
    recall_at_3: StrictFloat | None
    mrr: StrictFloat | None
    macro_precision: StrictFloat | None
    macro_recall: StrictFloat | None
    macro_f1: StrictFloat | None
    macro_precision_denominator: Annotated[StrictInt, Field(ge=0)]
    macro_recall_denominator: Annotated[StrictInt, Field(ge=0)]
    macro_f1_denominator: Annotated[StrictInt, Field(ge=0)]
    micro_true_positive: Annotated[StrictInt, Field(ge=0)]
    micro_false_positive: Annotated[StrictInt, Field(ge=0)]
    micro_false_negative: Annotated[StrictInt, Field(ge=0)]
    micro_precision: StrictFloat | None
    micro_recall: StrictFloat | None
    micro_f1: StrictFloat | None
    irrelevant_retrieval_numerator: Annotated[StrictInt, Field(ge=0)]
    irrelevant_retrieval_denominator: Annotated[StrictInt, Field(ge=0)]
    irrelevant_retrieval_rate: StrictFloat | None
    empty_correct: Annotated[StrictInt, Field(ge=0)]
    empty_total: Annotated[StrictInt, Field(ge=0)]
    empty_accuracy: StrictFloat | None
    correction_false_negative: Annotated[StrictInt, Field(ge=0)]
    negation_false_negative: Annotated[StrictInt, Field(ge=0)]
    return_counts: tuple[Annotated[StrictInt, Field(ge=0)], ...]


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def evaluate_holdout_predictions(
    *,
    suite: HoldoutSuiteInput,
    gold: HoldoutSuiteExpectation,
    predictions: tuple[HoldoutScenarioPrediction, ...],
) -> HoldoutEvaluationMetrics:
    """Compute frozen ranking/return metrics; safety exclusions are not semantic FP/FN."""

    scenario_by_id = {item.scenario_id: item for item in suite.scenarios}
    gold_by_id = {item.scenario_id: item for item in gold.scenarios}
    prediction_by_id = {item.scenario_id: item for item in predictions}
    if (
        len(prediction_by_id) != len(predictions)
        or set(prediction_by_id) != set(scenario_by_id)
        or set(gold_by_id) != set(scenario_by_id)
    ):
        raise HoldoutContractError("holdout predictions must cover exact scenarios")
    ranking_recall_1: list[float] = []
    ranking_recall_3: list[float] = []
    reciprocal_ranks: list[float] = []
    macro_precision: list[float] = []
    macro_recall: list[float] = []
    macro_f1: list[float] = []
    total_tp = total_fp = total_fn = 0
    empty_correct = empty_total = 0
    correction_fn = negation_fn = 0
    return_counts: list[int] = []
    for scenario in suite.scenarios:
        expectation = gold_by_id[scenario.scenario_id]
        prediction = prediction_by_id[scenario.scenario_id]
        relevant = set(expectation.relevant_candidate_ids)
        legal = relevant | set(expectation.semantic_negative_candidate_ids)
        if not set(prediction.ranked_candidate_ids).issubset(legal) or not set(
            prediction.returned_candidate_ids
        ).issubset(legal):
            raise HoldoutContractError(
                "safety-excluded or unknown candidate entered semantic metrics"
            )
        returned = set(prediction.returned_candidate_ids)
        tp = len(returned & relevant)
        fp = len(returned - relevant)
        fn = len(relevant - returned)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        return_counts.append(len(prediction.returned_candidate_ids))
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        if precision is not None:
            macro_precision.append(precision)
        if recall is not None:
            macro_recall.append(recall)
        if precision is not None and recall is not None:
            macro_f1.append(
                0.0
                if precision + recall == 0.0
                else 2.0 * precision * recall / (precision + recall)
            )
        if relevant:
            ranking_recall_1.append(
                len(set(prediction.ranked_candidate_ids[:1]) & relevant) / len(relevant)
            )
            ranking_recall_3.append(
                len(set(prediction.ranked_candidate_ids[:3]) & relevant) / len(relevant)
            )
            first_rank = next(
                (
                    index
                    for index, candidate_id in enumerate(
                        prediction.ranked_candidate_ids,
                        start=1,
                    )
                    if candidate_id in relevant
                ),
                None,
            )
            reciprocal_ranks.append(0.0 if first_rank is None else 1.0 / first_rank)
        else:
            empty_total += 1
            empty_correct += not prediction.returned_candidate_ids
        if HoldoutSlice.CORRECTION in scenario.slice_tags:
            correction_fn += fn
        if HoldoutSlice.NEGATION in scenario.slice_tags:
            negation_fn += fn
    micro_precision = _ratio(total_tp, total_tp + total_fp)
    micro_recall = _ratio(total_tp, total_tp + total_fn)
    micro_f1 = (
        None
        if micro_precision is None or micro_recall is None
        else (
            0.0
            if micro_precision + micro_recall == 0.0
            else 2.0
            * micro_precision
            * micro_recall
            / (micro_precision + micro_recall)
        )
    )
    return HoldoutEvaluationMetrics(
        relevant_scenario_count=len(ranking_recall_1),
        recall_at_1=_ratio(sum(ranking_recall_1), len(ranking_recall_1)),
        recall_at_3=_ratio(sum(ranking_recall_3), len(ranking_recall_3)),
        mrr=_ratio(sum(reciprocal_ranks), len(reciprocal_ranks)),
        macro_precision=_ratio(sum(macro_precision), len(macro_precision)),
        macro_recall=_ratio(sum(macro_recall), len(macro_recall)),
        macro_f1=_ratio(sum(macro_f1), len(macro_f1)),
        macro_precision_denominator=len(macro_precision),
        macro_recall_denominator=len(macro_recall),
        macro_f1_denominator=len(macro_f1),
        micro_true_positive=total_tp,
        micro_false_positive=total_fp,
        micro_false_negative=total_fn,
        micro_precision=micro_precision,
        micro_recall=micro_recall,
        micro_f1=micro_f1,
        irrelevant_retrieval_numerator=total_fp,
        irrelevant_retrieval_denominator=total_tp + total_fp,
        irrelevant_retrieval_rate=_ratio(total_fp, total_tp + total_fp),
        empty_correct=empty_correct,
        empty_total=empty_total,
        empty_accuracy=_ratio(empty_correct, empty_total),
        correction_false_negative=correction_fn,
        negation_false_negative=negation_fn,
        return_counts=tuple(return_counts),
    )


class CalibrationSelectionError(ValueError):
    pass


class HoldoutContractError(ValueError):
    pass


def validate_holdout_partition(
    suite: HoldoutSuiteInput,
    gold: HoldoutSuiteExpectation,
    config: HoldoutPreregisteredConfig,
) -> None:
    """Cross-check Gold labels against actual player/session/lifecycle facts."""

    scenario_by_id = {item.scenario_id: item for item in suite.scenarios}
    expectation_by_id = {item.scenario_id: item for item in gold.scenarios}
    if set(scenario_by_id) != set(expectation_by_id):
        raise HoldoutContractError("holdout input and Gold scenario IDs differ")
    for scenario_id, scenario in scenario_by_id.items():
        expectation = expectation_by_id[scenario_id]
        candidate_by_id = {item.candidate_id: item for item in scenario.candidates}
        partition_ids = {
            *expectation.relevant_candidate_ids,
            *expectation.semantic_negative_candidate_ids,
            *(item.candidate_id for item in expectation.safety_excluded_candidates),
        }
        if partition_ids != set(candidate_by_id):
            raise HoldoutContractError("holdout Gold does not cover exact raw candidates")
        legal_ids = {
            *expectation.relevant_candidate_ids,
            *expectation.semantic_negative_candidate_ids,
        }
        for candidate_id in legal_ids:
            candidate = candidate_by_id[candidate_id]
            if (
                candidate.source.player_id != scenario.player_id
                or candidate.source.source_session_id == scenario.current_session_id
                or candidate.setup
                not in {
                    HoldoutCandidateSetup.ACTIVE,
                    HoldoutCandidateSetup.CORRECTED_ACTIVE,
                }
            ):
                raise HoldoutContractError("legal holdout candidate is not active history")
        for excluded in expectation.safety_excluded_candidates:
            candidate = candidate_by_id[excluded.candidate_id]
            actual_reason: HoldoutSafetyReason | None = None
            if candidate.source.player_id != scenario.player_id:
                actual_reason = HoldoutSafetyReason.CROSS_PLAYER
            elif candidate.source.source_session_id == scenario.current_session_id:
                actual_reason = HoldoutSafetyReason.CURRENT_EPISODE
            else:
                lifecycle_reason = {
                    HoldoutCandidateSetup.SUPERSEDED: HoldoutSafetyReason.SUPERSEDED,
                    HoldoutCandidateSetup.INVALIDATED: HoldoutSafetyReason.INVALIDATED,
                    HoldoutCandidateSetup.HARD_DELETED: HoldoutSafetyReason.HARD_DELETED,
                }
                actual_reason = lifecycle_reason.get(candidate.setup)
            if excluded.reason is not actual_reason:
                raise HoldoutContractError(
                    "holdout safety reason does not match product state"
                )
    calibration_ids = tuple(
        item.scenario_id
        for item in suite.scenarios
        if item.split is HoldoutSplit.CALIBRATION
    )
    final_ids = tuple(
        item.scenario_id
        for item in suite.scenarios
        if item.split is HoldoutSplit.FINAL_TEST
    )
    if (
        calibration_ids != config.calibration_scenario_ids
        or final_ids != config.final_test_scenario_ids
    ):
        raise HoldoutContractError("holdout split does not match frozen config")
    counts = {
        HoldoutSplit.CALIBRATION: (8, 4),
        HoldoutSplit.FINAL_TEST: (20, 4),
    }
    for split, (relevant_expected, empty_expected) in counts.items():
        items = tuple(
            expectation_by_id[item.scenario_id]
            for item in suite.scenarios
            if item.split is split
        )
        if (
            sum(not item.expected_empty for item in items) != relevant_expected
            or sum(item.expected_empty for item in items) != empty_expected
        ):
            raise HoldoutContractError("holdout relevant/empty split counts are invalid")


def select_conservative_policy(
    *,
    outcomes: tuple[CalibrationPolicyOutcome, ...],
    config: HoldoutPreregisteredConfig,
) -> LockedConservativePolicy:
    """Select only from exact calibration results with a frozen conservative tie-break."""

    expected_ids = config.calibration_scenario_ids
    if not outcomes:
        raise CalibrationSelectionError("calibration produced no parameter outcomes")
    by_parameter = {item.parameter: item for item in outcomes}
    if set(by_parameter) != set(config.parameter_grid) or len(by_parameter) != len(outcomes):
        raise CalibrationSelectionError("calibration outcomes do not match the frozen grid")
    for item in outcomes:
        if item.evaluated_scenario_ids != expected_ids:
            raise CalibrationSelectionError(
                "policy selection may read only the ordered calibration split"
            )
    eligible = tuple(
        item
        for item in outcomes
        if item.metrics.safety_total == 0 and item.metrics.empty_accuracy == 1.0
    )
    if not eligible:
        raise CalibrationSelectionError("no calibration parameter satisfies hard gates")

    def score(item: CalibrationPolicyOutcome) -> tuple[float, ...]:
        metrics = item.metrics
        if None in (
            metrics.macro_f1,
            metrics.recall_at_3,
            metrics.mrr,
            metrics.irrelevant_retrieval_rate,
        ):
            raise CalibrationSelectionError(
                "calibration selection metrics cannot be undefined"
            )
        return (
            metrics.macro_f1,
            metrics.recall_at_3,
            metrics.mrr,
            -metrics.irrelevant_retrieval_rate,
            item.parameter.min_similarity,
            -float(item.parameter.max_results),
            item.parameter.minimum_margin,
        )

    selected = max(eligible, key=score)
    return LockedConservativePolicy(
        selection_version=config.selection_objective_version,
        parameter=selected.parameter,
    )
