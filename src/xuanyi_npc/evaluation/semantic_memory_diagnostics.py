"""Read-only post-hoc diagnostics for saved M4.5 semantic Pilot results."""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, StrictFloat, StrictInt

from xuanyi_npc.memory.canonical import sha256_hex

from .semantic_memory_contracts import (
    SafetyExclusionReason,
    SemanticGoldManifestV2,
    SemanticGoldSuiteExpectationV2,
    SemanticGoldSuiteInput,
    SemanticRawRunResultV2,
    StrictMemoryModel,
)


POST_HOC_ANALYSIS_LABEL = "post_hoc_exploratory_only"


class DiagnosticCandidateCategory(StrEnum):
    RELEVANT = "relevant"
    SEMANTIC_NEGATIVE = "semantic_negative"
    SAFETY_EXCLUDED = "safety_excluded"


class DiagnosticCandidateScore(StrictMemoryModel):
    candidate_id: str
    similarity: StrictFloat
    full_rank: StrictInt = Field(ge=1, le=4)
    legal_rank: StrictInt | None = Field(default=None, ge=1, le=4)
    category: DiagnosticCandidateCategory
    safety_exclusion_reason: SafetyExclusionReason | None = None


class DiagnosticScenarioScore(StrictMemoryModel):
    scenario_id: str
    split: Literal["calibration", "test"]
    candidates: tuple[DiagnosticCandidateScore, ...] = Field(
        min_length=4,
        max_length=4,
    )


class ExploratoryPolicy(StrictMemoryModel):
    analysis_label: Literal["post_hoc_exploratory_only"] = POST_HOC_ANALYSIS_LABEL
    policy_id: str
    absolute_threshold: StrictFloat
    max_results: StrictInt = Field(ge=1, le=3)
    min_top1_to_top2_margin: StrictFloat = Field(ge=0)


class ExploratoryPolicyResult(StrictMemoryModel):
    analysis_label: Literal["post_hoc_exploratory_only"] = POST_HOC_ANALYSIS_LABEL
    policy: ExploratoryPolicy
    true_positive: StrictInt = Field(ge=0)
    false_positive: StrictInt = Field(ge=0)
    false_negative: StrictInt = Field(ge=0)
    precision: StrictFloat | None
    recall: StrictFloat | None
    f1: StrictFloat | None
    irrelevant_retrieval_numerator: StrictInt = Field(ge=0)
    irrelevant_retrieval_denominator: StrictInt = Field(ge=0)
    irrelevant_retrieval_rate: StrictFloat | None
    empty_correct: StrictInt = Field(ge=0)
    empty_total: StrictInt = Field(ge=0)
    returned_candidate_ids: dict[str, tuple[str, ...]]


class SemanticDiagnosticResult(StrictMemoryModel):
    schema_version: Literal["m45_semantic_post_hoc_diagnostic_v1"] = (
        "m45_semantic_post_hoc_diagnostic_v1"
    )
    analysis_label: Literal["post_hoc_exploratory_only"] = POST_HOC_ANALYSIS_LABEL
    run1_sha256: str
    run2_sha256: str
    input_sha256: str
    expectation_sha256: str
    manifest_sha256: str
    config_sha256: str
    ordered_results_match: bool
    metrics_match: bool
    vector_payloads_match: bool
    max_vector_absolute_difference: StrictFloat
    scenarios: tuple[DiagnosticScenarioScore, ...] = Field(
        min_length=15,
        max_length=15,
    )
    counterfactuals: tuple[ExploratoryPolicyResult, ...]


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _query_id(scenario_id: str) -> str:
    return f"query_{scenario_id.removeprefix('semantic_').removesuffix('_001')}"


def _cosine_from_normalized(
    left: tuple[float, ...],
    right: tuple[float, ...],
) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("saved diagnostic vectors have inconsistent dimensions")
    if any(not math.isfinite(value) for value in (*left, *right)):
        raise ValueError("saved diagnostic vector contains a non-finite value")
    return math.fsum(a * b for a, b in zip(left, right, strict=True))


def _candidate_category(
    candidate_id: str,
    *,
    relevant: frozenset[str],
    negatives: frozenset[str],
    exclusions: dict[str, SafetyExclusionReason],
) -> tuple[DiagnosticCandidateCategory, SafetyExclusionReason | None]:
    if candidate_id in relevant:
        return DiagnosticCandidateCategory.RELEVANT, None
    if candidate_id in negatives:
        return DiagnosticCandidateCategory.SEMANTIC_NEGATIVE, None
    if candidate_id in exclusions:
        return DiagnosticCandidateCategory.SAFETY_EXCLUDED, exclusions[candidate_id]
    raise ValueError("candidate is absent from the frozen v2 partition")


def score_saved_vectors(
    *,
    run: SemanticRawRunResultV2,
    suite: SemanticGoldSuiteInput,
    expectations: SemanticGoldSuiteExpectationV2,
    manifest: SemanticGoldManifestV2,
) -> tuple[DiagnosticScenarioScore, ...]:
    expectation_by_id = {item.scenario_id: item for item in expectations.scenarios}
    calibration = frozenset(manifest.preregistered_config.calibration_scenario_ids)
    output: list[DiagnosticScenarioScore] = []
    for scenario in suite.scenarios:
        expectation = expectation_by_id[scenario.scenario_id]
        relevant = frozenset(expectation.relevant_candidate_ids)
        negatives = frozenset(expectation.semantic_negative_candidate_ids)
        exclusions = {
            item.candidate_id: item.reason
            for item in expectation.safety_excluded_candidates
        }
        query = run.vector_values_by_text_id[_query_id(scenario.scenario_id)]
        scored: list[
            tuple[
                str,
                float,
                DiagnosticCandidateCategory,
                SafetyExclusionReason | None,
            ]
        ] = []
        for candidate in scenario.candidates:
            category, reason = _candidate_category(
                candidate.candidate_id,
                relevant=relevant,
                negatives=negatives,
                exclusions=exclusions,
            )
            vector = run.vector_values_by_text_id[candidate.candidate_id]
            scored.append(
                (
                    candidate.candidate_id,
                    _cosine_from_normalized(query, vector),
                    category,
                    reason,
                )
            )
        scored.sort(key=lambda item: (-item[1], item[0]))
        legal_ids = [
            item[0]
            for item in scored
            if item[2] is not DiagnosticCandidateCategory.SAFETY_EXCLUDED
        ]
        candidates = tuple(
            DiagnosticCandidateScore(
                candidate_id=candidate_id,
                similarity=similarity,
                full_rank=rank,
                legal_rank=(
                    legal_ids.index(candidate_id) + 1
                    if candidate_id in legal_ids
                    else None
                ),
                category=category,
                safety_exclusion_reason=reason,
            )
            for rank, (candidate_id, similarity, category, reason) in enumerate(
                scored,
                start=1,
            )
        )
        output.append(
            DiagnosticScenarioScore(
                scenario_id=scenario.scenario_id,
                split=(
                    "calibration"
                    if scenario.scenario_id in calibration
                    else "test"
                ),
                candidates=candidates,
            )
        )
    return tuple(output)


def evaluate_exploratory_policy(
    *,
    policy: ExploratoryPolicy,
    scenarios: tuple[DiagnosticScenarioScore, ...],
) -> ExploratoryPolicyResult:
    true_positive = false_positive = false_negative = 0
    empty_correct = empty_total = 0
    returned_by_scenario: dict[str, tuple[str, ...]] = {}
    for scenario in scenarios:
        if scenario.split != "test":
            continue
        legal = sorted(
            (
                item
                for item in scenario.candidates
                if item.category is not DiagnosticCandidateCategory.SAFETY_EXCLUDED
            ),
            key=lambda item: (-item.similarity, item.candidate_id),
        )
        margin = (
            legal[0].similarity - legal[1].similarity
            if len(legal) >= 2
            else math.inf
        )
        returned = (
            tuple(
                item.candidate_id
                for item in legal
                if item.similarity >= policy.absolute_threshold
            )[: policy.max_results]
            if margin >= policy.min_top1_to_top2_margin
            else ()
        )
        returned_by_scenario[scenario.scenario_id] = returned
        relevant = {
            item.candidate_id
            for item in scenario.candidates
            if item.category is DiagnosticCandidateCategory.RELEVANT
        }
        actual = set(returned)
        true_positive += len(actual & relevant)
        false_positive += len(actual - relevant)
        false_negative += len(relevant - actual)
        if not relevant:
            empty_total += 1
            empty_correct += not actual
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return ExploratoryPolicyResult(
        policy=policy,
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        irrelevant_retrieval_numerator=false_positive,
        irrelevant_retrieval_denominator=true_positive + false_positive,
        irrelevant_retrieval_rate=_ratio(
            false_positive,
            true_positive + false_positive,
        ),
        empty_correct=empty_correct,
        empty_total=empty_total,
        returned_candidate_ids=returned_by_scenario,
    )


def default_exploratory_policies(
    manifest: SemanticGoldManifestV2,
) -> tuple[ExploratoryPolicy, ...]:
    policies = [
        ExploratoryPolicy(
            policy_id=f"top_{count}_no_threshold",
            absolute_threshold=-1.0,
            max_results=count,
            min_top1_to_top2_margin=0.0,
        )
        for count in (1, 2, 3)
    ]
    policies.extend(
        ExploratoryPolicy(
            policy_id=f"absolute_{threshold:.2f}_max3",
            absolute_threshold=threshold,
            max_results=3,
            min_top1_to_top2_margin=0.0,
        )
        for threshold in manifest.preregistered_config.empty_threshold_grid
    )
    policies.append(
        ExploratoryPolicy(
            policy_id="absolute_0.65_max1",
            absolute_threshold=0.65,
            max_results=1,
            min_top1_to_top2_margin=0.0,
        )
    )
    policies.extend(
        ExploratoryPolicy(
            policy_id=f"absolute_0.65_margin_{margin:.3f}_max{count}",
            absolute_threshold=0.65,
            max_results=count,
            min_top1_to_top2_margin=margin,
        )
        for count in (1, 3)
        for margin in (0.01, 0.02, 0.03, 0.05)
    )
    return tuple(policies)


def analyze_saved_results(
    *,
    run1_path: Path,
    run2_path: Path,
    input_path: Path,
    expectation_path: Path,
    manifest_path: Path,
) -> SemanticDiagnosticResult:
    run1_bytes = run1_path.read_bytes()
    run2_bytes = run2_path.read_bytes()
    run1 = SemanticRawRunResultV2.model_validate_json(run1_bytes)
    run2 = SemanticRawRunResultV2.model_validate_json(run2_bytes)
    suite = SemanticGoldSuiteInput.model_validate_json(
        input_path.read_text(encoding="utf-8")
    )
    expectations = SemanticGoldSuiteExpectationV2.model_validate_json(
        expectation_path.read_text(encoding="utf-8")
    )
    manifest = SemanticGoldManifestV2.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    input_sha = _file_sha256(input_path)
    expectation_sha = _file_sha256(expectation_path)
    manifest_sha = _file_sha256(manifest_path)
    if input_sha != manifest.scenario_input_sha256:
        raise ValueError("saved diagnostic input hash does not match manifest")
    if expectation_sha != manifest.gold_expectation_v2_sha256:
        raise ValueError("saved diagnostic expectation hash does not match manifest")
    if sha256_hex(manifest.preregistered_config) != manifest.preregistered_config_sha256:
        raise ValueError("saved diagnostic config hash does not match manifest")
    for run in (run1, run2):
        if (
            run.input_sha256 != input_sha
            or run.expectation_sha256 != expectation_sha
            or run.manifest_sha256 != manifest_sha
            or run.config_sha256 != manifest.preregistered_config_sha256
        ):
            raise ValueError("saved result identity does not match frozen Gold")
    if run1.vector_values_by_text_id.keys() != run2.vector_values_by_text_id.keys():
        raise ValueError("saved result vector identities differ")
    max_difference = max(
        abs(left - right)
        for item_id in run1.vector_values_by_text_id
        for left, right in zip(
            run1.vector_values_by_text_id[item_id],
            run2.vector_values_by_text_id[item_id],
            strict=True,
        )
    )
    scenarios = score_saved_vectors(
        run=run1,
        suite=suite,
        expectations=expectations,
        manifest=manifest,
    )
    counterfactuals = tuple(
        evaluate_exploratory_policy(policy=policy, scenarios=scenarios)
        for policy in default_exploratory_policies(manifest)
    )
    metrics_match = (
        run1.calibration_ranking == run2.calibration_ranking
        and run1.calibration_classification == run2.calibration_classification
        and run1.test_ranking == run2.test_ranking
        and run1.test_classification == run2.test_classification
        and run1.safety_counts == run2.safety_counts
    )
    return SemanticDiagnosticResult(
        run1_sha256=hashlib.sha256(run1_bytes).hexdigest(),
        run2_sha256=hashlib.sha256(run2_bytes).hexdigest(),
        input_sha256=input_sha,
        expectation_sha256=expectation_sha,
        manifest_sha256=manifest_sha,
        config_sha256=manifest.preregistered_config_sha256,
        ordered_results_match=(
            run1.ordered_result_sha256 == run2.ordered_result_sha256
        ),
        metrics_match=metrics_match,
        vector_payloads_match=(
            run1.vector_payload_sha256 == run2.vector_payload_sha256
        ),
        max_vector_absolute_difference=max_difference,
        scenarios=scenarios,
        counterfactuals=counterfactuals,
    )


def write_diagnostic_result(result: SemanticDiagnosticResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
