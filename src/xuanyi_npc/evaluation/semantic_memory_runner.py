"""Frozen M4.5 semantic Gold loader, evaluator, and offline BGE runner."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from xuanyi_npc.agents import ScriptedFakeLLM, V1DoctorAgent
from xuanyi_npc.agents.llm import ChatMessage, ChatRole
from xuanyi_npc.agents.v1_doctor import V1DoctorAgentInput, V1_SYSTEM_PROMPT
from xuanyi_npc.application.memory_context import MemoryQueryBuilder
from xuanyi_npc.application.memory_retrieval import BasicCosineMemoryRetriever, MemoryIndexService
from xuanyi_npc.application.views import AgentContextFilter, CaseObservation, MemoryContextStatus, MemoryView, ObservedClueView
from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import AgentAction, AgentActionType, CaseSessionState
from xuanyi_npc.domain.cases import CaseSessionStatus
from xuanyi_npc.memory.canonical import canonical_json, sha256_hex, stable_lifecycle_operation_id
from xuanyi_npc.memory.contracts import (
    LifecycleAction,
    MemoryCorrectionOperation,
    MemoryHardDeleteOperation,
    MemoryInvalidationOperation,
    MemoryLifecycleReason,
    MemorySourceEventType,
    MemoryStatus,
    PublicClueFact,
    TrustedMemoryBoundary,
)
from xuanyi_npc.memory.embeddings import (
    DeterministicFakeEmbedding,
    EmbeddingAdapter,
    EmbeddingBatchResult,
    EmbeddingRequest,
    EmbeddingRequestItem,
    MemoryRetrievalConfig,
    normalize_embedding_text,
)
from xuanyi_npc.memory.errors import MemoryIndexIncompleteError, MemoryTombstonedError
from xuanyi_npc.memory.local_bge import (
    BGE_M3_DIMENSION,
    BGE_M3_VERIFIED_MANIFEST_SHA256,
    BgeM3LocalEmbeddingAdapter,
    BgeM3LocalEmbeddingConfig,
)
from xuanyi_npc.memory.projection import CommittedActionPublicView, DeterministicMemoryProjector
from xuanyi_npc.storage.sqlite_memory import SQLiteMemoryRepository

from .semantic_memory_contracts import (
    SafetyExclusionReason,
    SemanticCandidateInput,
    SemanticCandidateRuntimeFact,
    SemanticCandidateRuntimeStatus,
    SemanticCandidateSetup,
    SemanticClassificationMetrics,
    SemanticGoldManifest,
    SemanticGoldManifestV2,
    SemanticGoldSuiteExpectation,
    SemanticGoldSuiteExpectationV2,
    SemanticGoldSuiteInput,
    SemanticPreregisteredConfig,
    SemanticRankingMetrics,
    SemanticRawRunResultV2,
    SemanticRunResourceMetrics,
    SemanticSafetyCounts,
    SemanticScenarioExpectation,
    SemanticScenarioExpectationV2,
    SemanticScenarioInput,
    SemanticScenarioResultV2,
)


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT = ROOT / "data" / "evaluation" / "m45_semantic_gold_inputs.json"
DEFAULT_EXPECTATIONS = ROOT / "data" / "evaluation" / "m45_semantic_gold_expectations.json"
DEFAULT_MANIFEST = ROOT / "data" / "evaluation" / "m45_semantic_gold_manifest.json"
DEFAULT_EXPECTATIONS_V2 = (
    ROOT / "data" / "evaluation" / "m45_semantic_gold_expectations_v2.json"
)
DEFAULT_MANIFEST_V2 = (
    ROOT / "data" / "evaluation" / "m45_semantic_gold_manifest_v2.json"
)
DEFAULT_MODEL = ROOT / "runtime_models" / "bge-m3-142964af7e05"
DEFAULT_MODEL_MANIFEST = ROOT / "config" / "model_manifests" / "bge_m3_142964af7e05_dense_fp32_verified.json"
HIDDEN_FRAGMENTS = (
    "root_cause",
    "valid_diagnosis_ids",
    "diagnosis_correct",
    "correct_treatment",
    "hidden_prerequisite",
    "score_breakdown",
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_semantic_gold(
    input_path: Path = DEFAULT_INPUT,
    expectation_path: Path = DEFAULT_EXPECTATIONS,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> tuple[SemanticGoldSuiteInput, SemanticGoldSuiteExpectation, SemanticGoldManifest]:
    suite = SemanticGoldSuiteInput.model_validate_json(input_path.read_text(encoding="utf-8"))
    expectations = SemanticGoldSuiteExpectation.model_validate_json(expectation_path.read_text(encoding="utf-8"))
    manifest = SemanticGoldManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    if suite.suite_id != expectations.suite_id or suite.suite_id != manifest.suite_id:
        raise ValueError("semantic Gold suite identities do not match")
    if _sha256_file(input_path) != manifest.scenario_input_sha256:
        raise ValueError("semantic Gold input hash does not match")
    if _sha256_file(expectation_path) != manifest.gold_expectation_sha256:
        raise ValueError("semantic Gold expectation hash does not match")
    if sha256_hex(manifest.preregistered_config) != manifest.preregistered_config_sha256:
        raise ValueError("semantic preregistered config hash does not match")
    expected_ids = {item.scenario_id: {candidate.candidate_id for candidate in item.candidates} for item in suite.scenarios}
    for expectation in expectations.scenarios:
        if not (set(expectation.relevant_candidate_ids) | set(expectation.forbidden_candidate_ids)).issubset(expected_ids[expectation.scenario_id]):
            raise ValueError("semantic expectation references an unknown candidate")
    return suite, expectations, manifest


def _expected_safety_reason(
    scenario: SemanticScenarioInput,
    candidate: SemanticCandidateInput,
) -> SafetyExclusionReason | None:
    if candidate.source.player_id != scenario.player_id:
        return SafetyExclusionReason.CROSS_PLAYER
    if candidate.source.source_session_id == scenario.current_session_id:
        return SafetyExclusionReason.CURRENT_EPISODE
    if candidate.setup is SemanticCandidateSetup.INVALIDATE:
        return SafetyExclusionReason.INVALIDATED
    if candidate.setup is SemanticCandidateSetup.HARD_DELETE:
        return SafetyExclusionReason.HARD_DELETED
    # A CORRECT slot denotes its active replacement. The superseded source record
    # remains independently audited from SQLite lifecycle state.
    return None


def validate_v2_partition_against_input(
    suite: SemanticGoldSuiteInput,
    expectations: SemanticGoldSuiteExpectationV2,
) -> None:
    scenarios = {item.scenario_id: item for item in suite.scenarios}
    for expectation in expectations.scenarios:
        scenario = scenarios[expectation.scenario_id]
        candidates = {item.candidate_id: item for item in scenario.candidates}
        relevant = set(expectation.relevant_candidate_ids)
        negative = set(expectation.semantic_negative_candidate_ids)
        excluded = {
            item.candidate_id: item.reason
            for item in expectation.safety_excluded_candidates
        }
        partition = relevant | negative | set(excluded)
        if partition != set(candidates):
            raise ValueError("semantic v2 partition must cover all four candidates")
        for candidate_id in relevant | negative:
            if _expected_safety_reason(scenario, candidates[candidate_id]) is not None:
                raise ValueError(
                    "legal semantic candidate violates trusted runtime scope"
                )
        for candidate_id, reason in excluded.items():
            expected = _expected_safety_reason(scenario, candidates[candidate_id])
            if reason is not expected:
                raise ValueError(
                    "safety exclusion reason does not match frozen input state"
                )


def load_semantic_gold_v2(
    input_path: Path = DEFAULT_INPUT,
    expectation_path: Path = DEFAULT_EXPECTATIONS_V2,
    manifest_path: Path = DEFAULT_MANIFEST_V2,
) -> tuple[
    SemanticGoldSuiteInput,
    SemanticGoldSuiteExpectationV2,
    SemanticGoldManifestV2,
]:
    suite = SemanticGoldSuiteInput.model_validate_json(
        input_path.read_text(encoding="utf-8")
    )
    expectations = SemanticGoldSuiteExpectationV2.model_validate_json(
        expectation_path.read_text(encoding="utf-8")
    )
    manifest = SemanticGoldManifestV2.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    if suite.suite_id != expectations.suite_id or suite.suite_id != manifest.suite_id:
        raise ValueError("semantic v2 Gold suite identities do not match")
    if _sha256_file(input_path) != manifest.scenario_input_sha256:
        raise ValueError("semantic v2 input hash does not match frozen v1 input")
    if _sha256_file(expectation_path) != manifest.gold_expectation_v2_sha256:
        raise ValueError("semantic v2 expectation hash does not match")
    if sha256_hex(manifest.preregistered_config) != manifest.preregistered_config_sha256:
        raise ValueError("semantic v2 preregistered config hash does not match")
    if _sha256_file(DEFAULT_EXPECTATIONS) != manifest.source_v1_expectation_sha256:
        raise ValueError("semantic v1 expectation history changed")
    if _sha256_file(DEFAULT_MANIFEST) != manifest.source_v1_manifest_sha256:
        raise ValueError("semantic v1 manifest history changed")
    validate_v2_partition_against_input(suite, expectations)
    return suite, expectations, manifest


def _public_view(candidate: SemanticCandidateInput) -> CommittedActionPublicView:
    source = candidate.source
    return CommittedActionPublicView(
        player_id=source.player_id,
        source_session_id=source.source_session_id,
        source_event_type=MemorySourceEventType(source.source_event_type),
        source_sequence=source.source_sequence,
        source_revision=source.source_revision,
        occurred_at=source.occurred_at,
        case_id=source.case_id,
        case_title=source.case_title,
        action_type=source.action_type,
        action_id=source.action_id,
        public_action_description=source.public_action_description,
        public_clues=tuple(PublicClueFact(clue_id=item.clue_id, description=item.description) for item in source.public_clues),
        public_result=source.public_result,
    )


def _observation(scenario: SemanticScenarioInput) -> CaseObservation:
    return CaseObservation(
        case_id="case_semantic_current",
        title=scenario.query.case_title,
        synopsis=scenario.query.case_synopsis,
        patient_id="patient_semantic",
        patient_name="合成患者",
        patient_public_profile="仅用于本地语义记忆评测的公开架空档案。",
        session_status=CaseSessionStatus.ACTIVE,
        session_revision=0,
        discovered_clues=tuple(
            ObservedClueView(clue_id=f"semantic_query_clue_{index:03d}", description=value)
            for index, value in enumerate(scenario.query.discovered_clue_descriptions, start=1)
        ),
        can_submit_diagnosis=False,
    )


def _query_text(scenario: SemanticScenarioInput) -> str:
    return MemoryQueryBuilder().build(
        current_user_message=scenario.query.current_user_message,
        case_observation=_observation(scenario),
        fixed_lesson=scenario.query.fixed_lesson,
    ).text


def candidate_public_text(candidate: SemanticCandidateInput) -> str:
    if candidate.setup is SemanticCandidateSetup.CORRECT:
        assert candidate.replacement_public_content is not None
        return candidate.replacement_public_content
    _, memory = DeterministicMemoryProjector().project_public_view(_public_view(candidate))
    return memory.content


def materialize_frozen_texts(suite: SemanticGoldSuiteInput) -> dict[str, str]:
    texts: dict[str, str] = {}
    for scenario in suite.scenarios:
        query_id = f"query_{scenario.scenario_id.removeprefix('semantic_').removesuffix('_001')}"
        texts[query_id] = _query_text(scenario)
        for candidate in scenario.candidates:
            texts[candidate.candidate_id] = candidate_public_text(candidate)
    normalized = {key: normalize_embedding_text(value) for key, value in texts.items()}
    if len(normalized) != 75 or len(set(normalized.values())) != 75:
        raise ValueError("semantic Gold must materialize exactly 75 unique public texts")
    if any(fragment in canonical_json(normalized) for fragment in HIDDEN_FRAGMENTS):
        raise ValueError("hidden sentinel entered semantic model input")
    return normalized


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None:
        return None
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def ranking_metrics(
    scenario_ids: tuple[str, ...],
    rankings: dict[str, tuple[str, ...]],
    expectations: dict[
        str,
        SemanticScenarioExpectation | SemanticScenarioExpectationV2,
    ],
) -> SemanticRankingMetrics:
    recalls_1: list[float] = []
    recalls_3: list[float] = []
    reciprocal: list[float] = []
    for scenario_id in scenario_ids:
        relevant = set(expectations[scenario_id].relevant_candidate_ids)
        if not relevant:
            continue
        expectation = expectations[scenario_id]
        ranking = rankings[scenario_id]
        if isinstance(expectation, SemanticScenarioExpectationV2):
            ranking = tuple(
                item
                for item in ranking
                if item in expectation.legal_ranking_candidate_ids
            )
        recalls_1.append(len(set(ranking[:1]) & relevant) / len(relevant))
        recalls_3.append(len(set(ranking[:3]) & relevant) / len(relevant))
        rank = next((index for index, value in enumerate(ranking, start=1) if value in relevant), None)
        reciprocal.append(0.0 if rank is None else 1.0 / rank)
    return SemanticRankingMetrics(
        scenario_count=len(scenario_ids),
        relevant_scenario_count=len(recalls_1),
        recall_at_1=_ratio(sum(recalls_1), len(recalls_1)),
        recall_at_3=_ratio(sum(recalls_3), len(recalls_3)),
        mrr=_ratio(sum(reciprocal), len(reciprocal)),
    )


def classification_metrics(
    scenario_ids: tuple[str, ...],
    selected: dict[str, tuple[str, ...]],
    expectations: dict[
        str,
        SemanticScenarioExpectation | SemanticScenarioExpectationV2,
    ],
) -> SemanticClassificationMetrics:
    precisions: list[float] = []
    recalls: list[float] = []
    f1s: list[float] = []
    total_tp = total_fp = total_fn = 0
    empty_correct = empty_total = 0
    for scenario_id in scenario_ids:
        expectation = expectations[scenario_id]
        relevant = set(expectation.relevant_candidate_ids)
        returned = set(selected[scenario_id])
        if isinstance(expectation, SemanticScenarioExpectationV2):
            returned &= set(expectation.legal_ranking_candidate_ids)
        tp = len(relevant & returned)
        fp = len(returned - relevant)
        fn = len(relevant - returned)
        total_tp += tp
        total_fp += fp
        total_fn += fn
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        score = _f1(precision, recall)
        if precision is not None:
            precisions.append(precision)
        if recall is not None:
            recalls.append(recall)
        if score is not None:
            f1s.append(score)
        if not relevant:
            empty_total += 1
            empty_correct += not returned
    micro_precision = _ratio(total_tp, total_tp + total_fp)
    micro_recall = _ratio(total_tp, total_tp + total_fn)
    return SemanticClassificationMetrics(
        scenario_count=len(scenario_ids),
        macro_precision=_ratio(sum(precisions), len(precisions)),
        macro_recall=_ratio(sum(recalls), len(recalls)),
        macro_f1=_ratio(sum(f1s), len(f1s)),
        macro_precision_denominator=len(precisions),
        macro_recall_denominator=len(recalls),
        macro_f1_denominator=len(f1s),
        micro_true_positive=total_tp,
        micro_false_positive=total_fp,
        micro_false_negative=total_fn,
        micro_precision=micro_precision,
        micro_recall=micro_recall,
        micro_f1=_f1(micro_precision, micro_recall),
        empty_correct=empty_correct,
        empty_total=empty_total,
        empty_accuracy=_ratio(empty_correct, empty_total),
        false_memory_numerator=total_fp,
        false_memory_denominator=total_tp + total_fp,
        false_memory_rate=_ratio(total_fp, total_tp + total_fp),
    )


def select_empty_threshold(
    config: SemanticPreregisteredConfig,
    scores: dict[str, tuple[tuple[str, float], ...]],
    expectations: dict[
        str,
        SemanticScenarioExpectation | SemanticScenarioExpectationV2,
    ],
) -> tuple[float, SemanticClassificationMetrics]:
    best: tuple[tuple[float, float, float], float, SemanticClassificationMetrics] | None = None
    for threshold in config.empty_threshold_grid:
        selected = {scenario_id: tuple(candidate_id for candidate_id, score in scores[scenario_id] if score >= threshold) for scenario_id in config.calibration_scenario_ids}
        metrics = classification_metrics(config.calibration_scenario_ids, selected, expectations)
        key = (metrics.empty_accuracy if metrics.empty_accuracy is not None else -1.0, metrics.macro_f1 if metrics.macro_f1 is not None else -1.0, threshold)
        if best is None or key > best[0]:
            best = (key, threshold, metrics)
    assert best is not None
    return best[1], best[2]


def runtime_safety_counts(
    *,
    scenario: SemanticScenarioInput,
    runtime_facts: tuple[SemanticCandidateRuntimeFact, ...],
    entered_candidate_ids: frozenset[str],
    hidden_content_leak: int = 0,
    prompt_boundary_violation: int = 0,
    authority_write_by_embedding: int = 0,
    embedding_space_mixing: int = 0,
    incomplete_index_as_empty: int = 0,
) -> SemanticSafetyCounts:
    """Classify safety only from product runtime facts, never Gold relevance."""

    facts = {item.candidate_id: item for item in runtime_facts}
    if not entered_candidate_ids.issubset(facts):
        raise ValueError("entered semantic candidate has no runtime fact")
    cross_player = 0
    current_episode = 0
    inactive = 0
    deleted = 0
    for candidate_id in entered_candidate_ids:
        fact = facts[candidate_id]
        if fact.player_id != scenario.player_id:
            cross_player += 1
        if fact.source_session_id == scenario.current_session_id:
            current_episode += 1
        if fact.status in {
            SemanticCandidateRuntimeStatus.SUPERSEDED,
            SemanticCandidateRuntimeStatus.INVALIDATED,
        }:
            inactive += 1
        if fact.status is SemanticCandidateRuntimeStatus.HARD_DELETED:
            deleted += 1
    return SemanticSafetyCounts(
        cross_player_recall=cross_player,
        current_episode_recall=current_episode,
        inactive_memory_recall=inactive,
        deletion_resurrection=deleted,
        hidden_content_leak=hidden_content_leak,
        prompt_boundary_violation=prompt_boundary_violation,
        authority_write_by_embedding=authority_write_by_embedding,
        embedding_space_mixing=embedding_space_mixing,
        incomplete_index_as_empty=incomplete_index_as_empty,
    )


def _sum_safety_counts(
    left: SemanticSafetyCounts,
    right: SemanticSafetyCounts,
) -> SemanticSafetyCounts:
    return SemanticSafetyCounts(
        **{
            field: getattr(left, field) + getattr(right, field)
            for field in SemanticSafetyCounts.model_fields
        }
    )


class _RecordingAdapter:
    def __init__(self, delegate: EmbeddingAdapter, text_ids: dict[str, str]) -> None:
        self.delegate = delegate
        self.text_ids = text_ids
        self.vectors: dict[str, tuple[float, ...]] = {}
        self.call_latencies_ms: list[float] = []
        self.physical_batch_count = 0
        self.text_count = 0

    @property
    def algorithm_version(self) -> str:
        return self.delegate.algorithm_version

    @property
    def embedding_space_id(self) -> str:
        return self.delegate.embedding_space_id

    @property
    def dimension(self) -> int:
        return self.delegate.dimension

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        started = time.perf_counter()
        result = self.delegate.embed(request)
        self.call_latencies_ms.append((time.perf_counter() - started) * 1000.0)
        batch_size = getattr(getattr(self.delegate, "config", None), "batch_size", len(request.items))
        self.physical_batch_count += math.ceil(len(request.items) / batch_size)
        self.text_count += len(request.items)
        for requested, returned in zip(request.items, result.items, strict=True):
            text_id = self.text_ids[normalize_embedding_text(requested.text)]
            prior = self.vectors.get(text_id)
            if prior is not None:
                difference = max(abs(left - right) for left, right in zip(prior, returned.vector, strict=True))
                if difference > 1e-6:
                    raise RuntimeError("same-run embedding repeatability exceeded tolerance")
            self.vectors[text_id] = returned.vector
        return result


def _prepare_repository(
    scenario: SemanticScenarioInput,
    adapter: EmbeddingAdapter,
    database_path: Path,
) -> tuple[SQLiteMemoryRepository, dict[str, str], BasicCosineMemoryRetriever, Any, str]:
    repository = SQLiteMemoryRepository(database_path)
    repository.initialize()
    projector = DeterministicMemoryProjector()
    memory_to_candidate: dict[str, str] = {}
    projected: dict[str, Any] = {}
    for candidate in scenario.candidates:
        source, memory = projector.project_public_view(_public_view(candidate))
        repository.write_projection(source, memory)
        projected[candidate.candidate_id] = (source, memory)
        memory_to_candidate[memory.memory_id] = candidate.candidate_id
        if candidate.setup is SemanticCandidateSetup.CORRECT:
            operation_id = stable_lifecycle_operation_id(LifecycleAction.CORRECT.value, memory.player_id, memory.memory_id, f"req_{candidate.candidate_id}")
            result = repository.correct_memory(MemoryCorrectionOperation(
                operation_id=operation_id,
                request_id=f"req_{candidate.candidate_id}",
                player_id=memory.player_id,
                target_memory_id=memory.memory_id,
                reason=MemoryLifecycleReason.VERIFIED_CORRECTION,
                trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
                occurred_at=datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc),
                replacement_public_content=candidate.replacement_public_content,
            ))
            assert result.replacement_memory_id is not None
            memory_to_candidate[result.replacement_memory_id] = candidate.candidate_id
        elif candidate.setup is SemanticCandidateSetup.INVALIDATE:
            operation_id = stable_lifecycle_operation_id(LifecycleAction.INVALIDATE.value, memory.player_id, memory.memory_id, f"req_{candidate.candidate_id}")
            repository.invalidate_memory(MemoryInvalidationOperation(
                operation_id=operation_id,
                request_id=f"req_{candidate.candidate_id}",
                player_id=memory.player_id,
                target_memory_id=memory.memory_id,
                reason=MemoryLifecycleReason.SOURCE_REVOKED,
                trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
                occurred_at=datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc),
            ))
        elif candidate.setup is SemanticCandidateSetup.HARD_DELETE:
            operation_id = stable_lifecycle_operation_id(LifecycleAction.HARD_DELETE.value, memory.player_id, memory.memory_id, f"req_{candidate.candidate_id}")
            repository.hard_delete_memory(MemoryHardDeleteOperation(
                operation_id=operation_id,
                request_id=f"req_{candidate.candidate_id}",
                player_id=memory.player_id,
                target_memory_id=memory.memory_id,
                reason=MemoryLifecycleReason.PRIVACY_REQUEST,
                trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
                occurred_at=datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc),
            ))
            try:
                repository.write_projection(source, memory)
            except MemoryTombstonedError:
                pass
            else:
                raise RuntimeError("hard-deleted semantic memory was resurrected")
    index = MemoryIndexService(repository=repository, adapter=adapter)
    for player_id in sorted({candidate.source.player_id for candidate in scenario.candidates}):
        index.index_player(player_id=player_id)
    retriever = BasicCosineMemoryRetriever(repository=repository, adapter=adapter)
    player = build_demo_player().model_copy(update={"player_id": scenario.player_id, "display_name": "合成语义评测学徒"})
    session = CaseSessionState(session_id=scenario.current_session_id, case_id="case_semantic_current", player_id=scenario.player_id)
    scope = AgentContextFilter().memory_scope(player, session)
    return repository, memory_to_candidate, retriever, scope, _query_text(scenario)


def _candidate_runtime_facts(
    *,
    scenario: SemanticScenarioInput,
    repository: SQLiteMemoryRepository,
    aliases: dict[str, str],
) -> tuple[SemanticCandidateRuntimeFact, ...]:
    records_by_candidate: dict[str, list[Any]] = {
        candidate.candidate_id: [] for candidate in scenario.candidates
    }
    for player_id in sorted(
        {candidate.source.player_id for candidate in scenario.candidates}
    ):
        for memory in repository.list_memories(
            player_id=player_id,
            include_inactive=True,
        ):
            candidate_id = aliases.get(memory.memory_id)
            if candidate_id is not None:
                records_by_candidate[candidate_id].append(memory)
    facts: list[SemanticCandidateRuntimeFact] = []
    for candidate in scenario.candidates:
        records = records_by_candidate[candidate.candidate_id]
        active = next(
            (record for record in records if record.status is MemoryStatus.ACTIVE),
            None,
        )
        if active is not None:
            facts.append(
                SemanticCandidateRuntimeFact(
                    candidate_id=candidate.candidate_id,
                    player_id=active.player_id,
                    source_session_id=active.source_session_id,
                    status=SemanticCandidateRuntimeStatus.ACTIVE,
                )
            )
            continue
        inactive = next(
            (
                record
                for record in records
                if record.status
                in {MemoryStatus.SUPERSEDED, MemoryStatus.INVALIDATED}
            ),
            None,
        )
        if inactive is not None:
            facts.append(
                SemanticCandidateRuntimeFact(
                    candidate_id=candidate.candidate_id,
                    player_id=inactive.player_id,
                    source_session_id=inactive.source_session_id,
                    status=(
                        SemanticCandidateRuntimeStatus.SUPERSEDED
                        if inactive.status is MemoryStatus.SUPERSEDED
                        else SemanticCandidateRuntimeStatus.INVALIDATED
                    ),
                )
            )
            continue
        if candidate.setup is not SemanticCandidateSetup.HARD_DELETE:
            raise RuntimeError("semantic candidate authority is unexpectedly missing")
        facts.append(
            SemanticCandidateRuntimeFact(
                candidate_id=candidate.candidate_id,
                player_id=candidate.source.player_id,
                source_session_id=candidate.source.source_session_id,
                status=SemanticCandidateRuntimeStatus.HARD_DELETED,
            )
        )
    return tuple(facts)


def _eligible_candidate_ids(
    runtime_facts: tuple[SemanticCandidateRuntimeFact, ...],
    scenario: SemanticScenarioInput,
) -> frozenset[str]:
    return frozenset(
        fact.candidate_id
        for fact in runtime_facts
        if fact.player_id == scenario.player_id
        and fact.source_session_id != scenario.current_session_id
        and fact.status is SemanticCandidateRuntimeStatus.ACTIVE
    )


def _authority_hash(repository: SQLiteMemoryRepository, players: set[str]) -> str:
    return sha256_hex({player_id: repository.list_memories(player_id=player_id, include_inactive=True) for player_id in sorted(players)})


def _prompt_boundary(memory: MemoryView, scenario: SemanticScenarioInput) -> bool:
    fake = ScriptedFakeLLM([AgentAction(action_id="agent_step_001", action_type=AgentActionType.RESPOND, dialogue="继续核对公开信息。", confidence=0.5).model_dump_json()])
    player = build_demo_player().model_copy(update={"player_id": scenario.player_id, "display_name": "合成语义评测学徒"})
    V1DoctorAgent(fake).decide(V1DoctorAgentInput(
        step_index=1,
        player_view=AgentContextFilter().player_view(player),
        case_observation=_observation(scenario),
        recent_messages=(ChatMessage(role=ChatRole.USER, content=scenario.query.current_user_message),),
        fixed_lesson=scenario.query.fixed_lesson,
        retrieved_memories=(memory,),
        memory_context_status=MemoryContextStatus.READY,
    ))
    request = fake.requests[0]
    return request.messages[0].content == V1_SYSTEM_PROMPT and memory.content in request.messages[-1].content and "record_memory" not in canonical_json(request.response_schema)


def _fake_rankings(suite: SemanticGoldSuiteInput, texts: dict[str, str]) -> dict[str, tuple[str, ...]]:
    adapter = DeterministicFakeEmbedding()
    request = EmbeddingRequest(embedding_space_id=adapter.embedding_space_id, dimension=adapter.dimension, items=tuple(EmbeddingRequestItem(item_id=key, text=value) for key, value in texts.items()))
    result = adapter.embed(request)
    vectors = {item.item_id: item.vector for item in result.items}
    rankings: dict[str, tuple[str, ...]] = {}
    for scenario in suite.scenarios:
        query_id = f"query_{scenario.scenario_id.removeprefix('semantic_').removesuffix('_001')}"
        candidates = [candidate for candidate in scenario.candidates if candidate.source.player_id == scenario.player_id and candidate.source.source_session_id != scenario.current_session_id and candidate.setup not in {SemanticCandidateSetup.INVALIDATE, SemanticCandidateSetup.HARD_DELETE}]
        scored = [(candidate.candidate_id, math.fsum(left * right for left, right in zip(vectors[query_id], vectors[candidate.candidate_id], strict=True))) for candidate in candidates]
        scored.sort(key=lambda item: (-item[1], item[0]))
        rankings[scenario.scenario_id] = tuple(item[0] for item in scored[:3])
    return rankings


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def _peak_working_set_bytes() -> int:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    process = get_current_process()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        raise RuntimeError("unable to read process peak memory")
    return int(counters.PeakWorkingSetSize)


@contextmanager
def _blocked_network() -> Iterator[list[str]]:
    attempts: list[str] = []
    original_create = socket.create_connection
    original_connect = socket.socket.connect
    def blocked(*args: object, **kwargs: object) -> None:
        del args, kwargs
        attempts.append("socket")
        raise RuntimeError("network is forbidden during the local semantic Pilot")
    socket.create_connection = blocked
    socket.socket.connect = blocked
    previous_hf = os.environ.get("HF_HUB_OFFLINE")
    previous_tf = os.environ.get("TRANSFORMERS_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        yield attempts
    finally:
        socket.create_connection = original_create
        socket.socket.connect = original_connect
        if previous_hf is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous_hf
        if previous_tf is None:
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
        else:
            os.environ["TRANSFORMERS_OFFLINE"] = previous_tf


def _git_value(*args: str) -> str:
    return subprocess.run(("git", *args), cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def run_local_bge(
    *,
    run_id: str,
    freeze_commit: str,
    output_path: Path,
) -> SemanticRawRunResultV2:
    if _git_value("rev-parse", "HEAD") != freeze_commit or _git_value("status", "--porcelain"):
        raise RuntimeError("semantic Pilot requires the exact clean freeze checkpoint")
    suite, gold, manifest = load_semantic_gold_v2()
    texts = materialize_frozen_texts(suite)
    config = manifest.preregistered_config
    output_path = output_path.resolve()
    results_root = (ROOT / "results").resolve()
    if results_root not in output_path.parents:
        raise RuntimeError("raw semantic results must remain in the ignored results directory")
    if _sha256_file(ROOT / "requirements" / "local-embedding-cu126-win-py312.txt") != config.dependency_lock_sha256:
        raise RuntimeError("local embedding dependency lock changed")
    text_ids = {value: key for key, value in texts.items()}
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("frozen CUDA device is unavailable")
    torch.cuda.reset_peak_memory_stats()
    adapter_config = BgeM3LocalEmbeddingConfig(
        model_directory=DEFAULT_MODEL.resolve(strict=True),
        manifest_path=DEFAULT_MODEL_MANIFEST.resolve(strict=True),
        manifest_sha256=BGE_M3_VERIFIED_MANIFEST_SHA256,
        device="cuda",
        max_input_length=config.max_length_tokens,
        batch_size=config.batch_size,
        embedding_space_id=config.embedding_space_id,
    )
    base = BgeM3LocalEmbeddingAdapter(config=adapter_config)
    safety = SemanticSafetyCounts()
    with _blocked_network() as network_attempts:
        load_started = time.perf_counter()
        base.load()
        torch.cuda.synchronize()
        cold_load_ms = (time.perf_counter() - load_started) * 1000.0
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            str(DEFAULT_MODEL.resolve()),
            local_files_only=True,
            trust_remote_code=False,
        )
        long_text = texts["query_long_text"]
        long_before = len(tokenizer(long_text, add_special_tokens=True, truncation=False)["input_ids"])
        long_after = len(tokenizer(long_text, add_special_tokens=True, truncation=True, max_length=config.max_length_tokens)["input_ids"])
        if long_before <= config.max_length_tokens or long_after != config.max_length_tokens:
            raise RuntimeError("frozen long-text tokenizer truncation expectation failed")
        long_details = (len(long_text), long_before, long_after, True)
        recording = _RecordingAdapter(base, text_ids)
        corpus_request = EmbeddingRequest(
            embedding_space_id=base.embedding_space_id,
            dimension=base.dimension,
            items=tuple(EmbeddingRequestItem(item_id=key, text=value) for key, value in texts.items()),
        )
        recording.embed(corpus_request)
        torch.cuda.synchronize()
        fake_rankings = _fake_rankings(suite, texts)
        scores: dict[str, tuple[tuple[str, float], ...]] = {}
        scoped_counts: dict[str, int] = {}
        prompt_ok = True
        expectation_by_id = {item.scenario_id: item for item in gold.scenarios}
        with tempfile.TemporaryDirectory(prefix=f"xuanyi-{run_id}-") as temporary:
            root = Path(temporary)
            for scenario in suite.scenarios:
                database = root / scenario.scenario_id / "memory.sqlite3"
                repository, aliases, retriever, scope, query_text = _prepare_repository(scenario, recording, database)
                runtime_facts = _candidate_runtime_facts(
                    scenario=scenario,
                    repository=repository,
                    aliases=aliases,
                )
                eligible_candidates = _eligible_candidate_ids(runtime_facts, scenario)
                expectation = expectation_by_id[scenario.scenario_id]
                if eligible_candidates != expectation.legal_ranking_candidate_ids:
                    raise RuntimeError(
                        "semantic Gold partition does not match actual product state"
                    )
                players = {candidate.source.player_id for candidate in scenario.candidates}
                before_authority = _authority_hash(repository, players)
                search = retriever.retrieve_scoped(
                    scope=scope,
                    query_text=query_text,
                    config=MemoryRetrievalConfig(top_k=3, min_similarity=-1.0, embedding_space_id=config.embedding_space_id, query_template_version=config.query_template_version),
                )
                after_authority = _authority_hash(repository, players)
                ranked = tuple((aliases[hit.memory_id], hit.similarity) for hit in search.hits)
                scores[scenario.scenario_id] = ranked
                scoped_counts[scenario.scenario_id] = search.index_state.active_memory_count
                if search.index_state.active_memory_count != len(eligible_candidates):
                    raise RuntimeError(
                        "runtime candidate pre-filter diverged from authority state"
                    )
                returned_aliases = frozenset(item[0] for item in ranked)
                safety = _sum_safety_counts(
                    safety,
                    runtime_safety_counts(
                        scenario=scenario,
                        runtime_facts=runtime_facts,
                        entered_candidate_ids=(
                            eligible_candidates | returned_aliases
                        ),
                        authority_write_by_embedding=int(
                            before_authority != after_authority
                        ),
                    ),
                )
                if scenario.scenario_id == "semantic_prompt_injection_data_001":
                    candidate = scenario.candidates[0]
                    memory = next(memory for memory in repository.list_memories(player_id=scenario.player_id, include_inactive=False) if aliases.get(memory.memory_id) == candidate.candidate_id)
                    prompt_ok = _prompt_boundary(MemoryView(memory_id=memory.memory_id, memory_type=memory.memory_type, content=memory.content, occurred_at=memory.occurred_at), scenario)
                if scenario.scenario_id == "semantic_empty_001":
                    repository.delete_embeddings(player_id=scenario.player_id, embedding_space_id=config.embedding_space_id)
                    try:
                        retriever.retrieve_scoped(scope=scope, query_text=query_text, config=MemoryRetrievalConfig(top_k=3, min_similarity=-1.0, embedding_space_id=config.embedding_space_id, query_template_version=config.query_template_version))
                    except MemoryIndexIncompleteError:
                        pass
                    else:
                        safety = safety.model_copy(
                            update={
                                "incomplete_index_as_empty": (
                                    safety.incomplete_index_as_empty + 1
                                )
                            }
                        )
        if network_attempts:
            raise RuntimeError("local semantic Pilot attempted network access")
    if not prompt_ok:
        safety = safety.model_copy(update={"prompt_boundary_violation": 1})
    public_scan = canonical_json({"texts": texts, "scores": scores})
    leak_count = sum(fragment in public_scan for fragment in HIDDEN_FRAGMENTS)
    if leak_count:
        safety = safety.model_copy(update={"hidden_content_leak": leak_count})
    if safety.total:
        raise RuntimeError("semantic Pilot safety stop condition triggered")
    expectation_by_id = {item.scenario_id: item for item in gold.scenarios}
    selected_threshold, calibration_classification = select_empty_threshold(config, scores, expectation_by_id)
    ranking_ids = {scenario_id: tuple(candidate_id for candidate_id, _ in ranking) for scenario_id, ranking in scores.items()}
    selected = {scenario_id: tuple(candidate_id for candidate_id, score in ranking if score >= selected_threshold) for scenario_id, ranking in scores.items()}
    calibration_ranking = ranking_metrics(config.calibration_scenario_ids, ranking_ids, expectation_by_id)
    test_ranking = ranking_metrics(config.test_scenario_ids, ranking_ids, expectation_by_id)
    test_classification = classification_metrics(config.test_scenario_ids, selected, expectation_by_id)
    scenarios: list[SemanticScenarioResultV2] = []
    for scenario in suite.scenarios:
        expectation = expectation_by_id[scenario.scenario_id]
        ranking = scores[scenario.scenario_id]
        relevant_rank = next((index for index, (candidate_id, _) in enumerate(ranking, start=1) if candidate_id in expectation.relevant_candidate_ids), None)
        fake = fake_rankings[scenario.scenario_id]
        scenarios.append(SemanticScenarioResultV2(
            scenario_id=scenario.scenario_id,
            split="calibration" if scenario.scenario_id in config.calibration_scenario_ids else "test",
            ranking_candidate_ids=tuple(item[0] for item in ranking),
            ranking_similarities=tuple(item[1] for item in ranking),
            threshold_candidate_ids=selected[scenario.scenario_id],
            relevant_candidate_ids=expectation.relevant_candidate_ids,
            semantic_negative_candidate_ids=(
                expectation.semantic_negative_candidate_ids
            ),
            safety_excluded_candidates=expectation.safety_excluded_candidates,
            relevant_rank=relevant_rank,
            fake_ranking_candidate_ids=fake,
            top_k_overlap_count=len(set(fake) & {item[0] for item in ranking}),
            scoped_candidate_count=scoped_counts[scenario.scenario_id],
            other_player_candidate_count=0,
            current_episode_candidate_count=0,
            **(
                {
                    "long_text_characters": long_details[0],
                    "long_text_tokens_before_truncation": long_details[1],
                    "long_text_tokens_after_truncation": long_details[2],
                    "long_text_was_truncated": long_details[3],
                }
                if scenario.require_long_text_truncation
                else {}
            ),
        ))
    ordered_payload = tuple((item.scenario_id, item.ranking_candidate_ids, item.threshold_candidate_ids) for item in scenarios)
    vector_payload = {key: recording.vectors[key] for key in sorted(recording.vectors)}
    resources = SemanticRunResourceMetrics(
        model_load_count=1,
        local_embedding_batch_count=recording.physical_batch_count,
        local_embedding_text_count=recording.text_count,
        cold_load_ms=cold_load_ms,
        first_batch_ms=recording.call_latencies_ms[0],
        warm_batch_ms=recording.call_latencies_ms[1] if len(recording.call_latencies_ms) > 1 else None,
        total_embedding_ms=sum(recording.call_latencies_ms),
        peak_process_working_set_bytes=_peak_working_set_bytes(),
        peak_cuda_allocated_bytes=int(torch.cuda.max_memory_allocated()),
        peak_cuda_reserved_bytes=int(torch.cuda.max_memory_reserved()),
        network_attempt_count=0,
        api_request_count=0,
        cost_cny=0.0,
    )
    result = SemanticRawRunResultV2(
        run_id=run_id,
        freeze_commit=freeze_commit,
        code_commit=_git_value("rev-parse", "HEAD"),
        input_sha256=manifest.scenario_input_sha256,
        expectation_sha256=manifest.gold_expectation_v2_sha256,
        manifest_sha256=_sha256_file(DEFAULT_MANIFEST_V2),
        config_sha256=manifest.preregistered_config_sha256,
        selected_empty_threshold=selected_threshold,
        calibration_ranking=calibration_ranking,
        calibration_classification=calibration_classification,
        test_ranking=test_ranking,
        test_classification=test_classification,
        safety_counts=safety,
        scenarios=tuple(scenarios),
        ordered_result_sha256=sha256_hex(ordered_payload),
        vector_payload_sha256=sha256_hex(vector_payload),
        vector_values_by_text_id=vector_payload,
        resources=resources,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_local_bge(run_id=args.run_id, freeze_commit=args.freeze_commit, output_path=args.output)
    print(json.dumps({"run_id": result.run_id, "selected_empty_threshold": result.selected_empty_threshold, "test_ranking": result.test_ranking.model_dump(mode="json"), "test_classification": result.test_classification.model_dump(mode="json"), "safety": result.safety_counts.model_dump(mode="json"), "ordered_result_sha256": result.ordered_result_sha256}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
