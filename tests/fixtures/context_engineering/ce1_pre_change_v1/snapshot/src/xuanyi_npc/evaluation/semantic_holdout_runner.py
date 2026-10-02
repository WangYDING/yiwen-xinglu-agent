"""Independent, calibration-gated runner for the frozen M4.5 36-case holdout.

This module deliberately does not import the historical 15-case semantic runner.
Gold is opened through a split gate: calibration labels are available first, while
final-test labels stay inaccessible until a conservative policy is locked.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from pydantic import Field, StrictBool, StrictFloat, StrictInt

from xuanyi_npc.application.memory_retrieval import (
    BasicCosineMemoryRetriever,
    MemoryIndexService,
)
from xuanyi_npc.application.retrieval_query import RetrievalQueryV2Builder
from xuanyi_npc.application.views import (
    AgentContextFilter,
    CaseObservation,
    MemoryScope,
    ObservedClueView,
)
from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import CaseSessionState
from xuanyi_npc.domain.cases import CaseSessionStatus
from xuanyi_npc.memory.canonical import (
    canonical_json,
    sha256_hex,
    stable_lifecycle_operation_id,
)
from xuanyi_npc.memory.contracts import (
    AuthoritativeMemoryRecord,
    LifecycleAction,
    MemoryCorrectionOperation,
    MemoryHardDeleteOperation,
    MemoryInvalidationOperation,
    MemoryLifecycleReason,
    MemorySourceEventType,
    MemoryStatus,
    PublicClueFact,
    Sha256Hex,
    StrictMemoryModel,
    TrustedMemoryBoundary,
)
from xuanyi_npc.memory.embeddings import (
    ConservativeRetrievalConfigV2,
    EmbeddingAdapter,
    EmbeddingBatchResult,
    EmbeddingRequest,
    EmbeddedItem,
    RepresentationIndexStatus,
    normalize_embedding_text,
)
from xuanyi_npc.memory.errors import MemoryIndexIncompleteError, MemoryTombstonedError
from xuanyi_npc.memory.local_bge import (
    BGE_M3_DIMENSION,
    BGE_M3_VERIFIED_MANIFEST_SHA256,
    BgeM3LocalEmbeddingAdapter,
    BgeM3LocalEmbeddingConfig,
    BgeM3VerifiedManifest,
)
from xuanyi_npc.memory.projection import (
    CommittedActionPublicView,
    DeterministicMemoryProjector,
)
from xuanyi_npc.memory.representations import EmbeddingDocumentV2Builder
from xuanyi_npc.storage.sqlite_memory import SQLiteMemoryRepository

from .semantic_holdout_contracts import (
    CalibrationPolicyOutcome,
    CalibrationSelectionError,
    ConservativeParameter,
    HoldoutCandidateInput,
    HoldoutCandidateSetup,
    HoldoutEvaluationMetrics,
    HoldoutManifest,
    HoldoutPolicyMetrics,
    HoldoutPreregisteredConfig,
    HoldoutSafetyReason,
    HoldoutScenarioExpectation,
    HoldoutScenarioInput,
    HoldoutScenarioPrediction,
    HoldoutSplit,
    HoldoutSuiteExpectation,
    HoldoutSuiteInput,
    LockedConservativePolicy,
    evaluate_holdout_predictions,
    select_conservative_policy,
)


ROOT = Path(__file__).resolve().parents[3]
GOLD_FREEZE_COMMIT = "98d08eef52bfb164f454bd50c08c0d3feab1bb26"
EXPERIMENT_DATA_ROOT = ROOT / "tools" / "experiments" / "data" / "evaluation"
DEFAULT_INPUT = EXPERIMENT_DATA_ROOT / "m45_semantic_holdout_inputs_v1.json"
DEFAULT_GOLD = EXPERIMENT_DATA_ROOT / "m45_semantic_holdout_expectations_v1.json"
DEFAULT_CONFIG = EXPERIMENT_DATA_ROOT / "m45_semantic_holdout_config_v1.json"
DEFAULT_MANIFEST = EXPERIMENT_DATA_ROOT / "m45_semantic_holdout_manifest_v1.json"
DEFAULT_MODEL = ROOT / "runtime_models" / "bge-m3-142964af7e05"
DEFAULT_MODEL_MANIFEST = ROOT / "config" / "model_manifests" / "bge_m3_142964af7e05_dense_fp32_verified.json"
DEFAULT_DEPENDENCY_LOCK = ROOT / "requirements" / "local-embedding-cu126-win-py312.txt"
MAIN_WEIGHT_SHA256 = "993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e"
FROZEN_BATCH_SIZE = 16
HIDDEN_SENTINELS = (
    "root_cause",
    "valid_diagnosis_ids",
    "diagnosis_correct",
    "correct_treatment",
    "hidden_prerequisite",
    "score_breakdown",
    "api_key",
)


class HoldoutRunnerError(RuntimeError):
    """Safe runner stop with a stable public error code."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class RuntimeCandidateFact(StrictMemoryModel):
    candidate_id: str
    player_id: str
    source_session_id: str
    status: Literal["active", "superseded", "invalidated", "hard_deleted"]


class HoldoutSafetyCounts(StrictMemoryModel):
    cross_player_recall: StrictInt = Field(default=0, ge=0)
    current_episode_recall: StrictInt = Field(default=0, ge=0)
    superseded_recall: StrictInt = Field(default=0, ge=0)
    invalidated_recall: StrictInt = Field(default=0, ge=0)
    deletion_resurrection: StrictInt = Field(default=0, ge=0)
    hidden_content_leak: StrictInt = Field(default=0, ge=0)
    prompt_boundary_change: StrictInt = Field(default=0, ge=0)
    authority_write_by_embedding: StrictInt = Field(default=0, ge=0)
    embedding_space_mixing: StrictInt = Field(default=0, ge=0)
    incomplete_or_stale_index_as_empty: StrictInt = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return sum(int(value) for value in self.model_dump().values())


class HoldoutScenarioRun(StrictMemoryModel):
    scenario_id: str
    split: HoldoutSplit
    ranked_candidate_ids: tuple[str, ...]
    ranked_similarities: tuple[StrictFloat, ...]
    returned_candidate_ids: tuple[str, ...]
    relevant_candidate_ids: tuple[str, ...]
    semantic_negative_candidate_ids: tuple[str, ...]
    safety_excluded: tuple[tuple[str, HoldoutSafetyReason], ...]
    eligible_candidate_count: StrictInt = Field(ge=0)
    returned_count: StrictInt = Field(ge=0)


class HoldoutRunResources(StrictMemoryModel):
    model_load_count: StrictInt = Field(ge=0)
    local_embedding_batch_count: StrictInt = Field(ge=0)
    local_embedding_text_count: StrictInt = Field(ge=0)
    cold_load_ms: StrictFloat | None = None
    first_batch_ms: StrictFloat | None = None
    warm_embedding_ms: StrictFloat | None = None
    total_embedding_ms: StrictFloat
    peak_process_working_set_bytes: StrictInt = Field(ge=0)
    peak_cuda_allocated_bytes: StrictInt = Field(ge=0)
    peak_cuda_reserved_bytes: StrictInt = Field(ge=0)
    network_attempt_count: StrictInt = Field(ge=0)
    api_request_count: Literal[0] = 0
    cost_cny: Literal[0.0] = 0.0


class HoldoutAdmission(StrictMemoryModel):
    single_run_quality_passed: StrictBool
    failed_gates: tuple[str, ...] = ()


class HoldoutRawRunResult(StrictMemoryModel):
    schema_version: Literal["m45_semantic_holdout_raw_result_v1"] = (
        "m45_semantic_holdout_raw_result_v1"
    )
    run_id: str
    status: Literal["completed", "fail_calibration"]
    gold_freeze_commit: Literal["98d08eef52bfb164f454bd50c08c0d3feab1bb26"]
    execution_commit: str
    input_sha256: Sha256Hex
    expectation_sha256: Sha256Hex
    config_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    model_manifest_sha256: Sha256Hex
    dependency_lock_sha256: Sha256Hex
    embedding_space_id: str
    selected_policy: LockedConservativePolicy | None = None
    calibration_policy_outcomes: tuple[CalibrationPolicyOutcome, ...]
    calibration_metrics: HoldoutEvaluationMetrics | None = None
    final_test_metrics: HoldoutEvaluationMetrics | None = None
    scenarios: tuple[HoldoutScenarioRun, ...]
    safety_counts: HoldoutSafetyCounts
    admission: HoldoutAdmission | None = None
    ordered_result_sha256: Sha256Hex
    vector_payload_sha256: Sha256Hex
    vector_values_by_text_id: dict[str, tuple[StrictFloat, ...]]
    resources: HoldoutRunResources
    final_test_evaluation_count: Literal[0, 1]


class HoldoutRunComparison(StrictMemoryModel):
    policy_identical: StrictBool
    ordered_results_identical: StrictBool
    metrics_identical: StrictBool
    vector_keys_identical: StrictBool
    max_vector_abs_difference: StrictFloat | None
    passed_repeatability_gate: StrictBool


class HoldoutFailureCheckpoint(StrictMemoryModel):
    schema_version: Literal["m45_semantic_holdout_failure_v1"] = (
        "m45_semantic_holdout_failure_v1"
    )
    run_id: str
    execution_commit: str | None = None
    error_code: str
    safe_message: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_model_manifest_sha256(path: Path) -> str:
    manifest = BgeM3VerifiedManifest.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    return sha256_hex(manifest)


def _git_value(*args: str) -> str:
    return subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def load_frozen_holdout() -> tuple[
    HoldoutSuiteInput,
    HoldoutPreregisteredConfig,
    HoldoutManifest,
]:
    suite = HoldoutSuiteInput.model_validate_json(DEFAULT_INPUT.read_text(encoding="utf-8"))
    config = HoldoutPreregisteredConfig.model_validate_json(
        DEFAULT_CONFIG.read_text(encoding="utf-8")
    )
    manifest = HoldoutManifest.model_validate_json(
        DEFAULT_MANIFEST.read_text(encoding="utf-8")
    )
    identities = (
        (_sha256_file(DEFAULT_INPUT), manifest.input_sha256),
        (_sha256_file(DEFAULT_GOLD), manifest.expectation_sha256),
        (_sha256_file(DEFAULT_CONFIG), manifest.config_sha256),
    )
    if any(actual != expected for actual, expected in identities):
        raise HoldoutRunnerError("holdout_identity_mismatch", "frozen holdout identity changed")
    if tuple(item.scenario_id for item in suite.scenarios if item.split is HoldoutSplit.CALIBRATION) != config.calibration_scenario_ids:
        raise HoldoutRunnerError("holdout_split_mismatch", "calibration split changed")
    if tuple(item.scenario_id for item in suite.scenarios if item.split is HoldoutSplit.FINAL_TEST) != config.final_test_scenario_ids:
        raise HoldoutRunnerError("holdout_split_mismatch", "final-test split changed")
    return suite, config, manifest


class HoldoutGoldGate:
    """Expose final-test labels only after the calibration policy is locked."""

    def __init__(self, *, path: Path, expected_sha256: str, suite_id: str) -> None:
        if _sha256_file(path) != expected_sha256:
            raise HoldoutRunnerError("holdout_identity_mismatch", "holdout Gold identity changed")
        self._path = path
        self._suite_id = suite_id
        self._locked_policy: LockedConservativePolicy | None = None
        self.final_access_count = 0

    def calibration(self, scenario_ids: tuple[str, ...]) -> HoldoutSuiteExpectation:
        return self._selected(scenario_ids)

    def lock(self, policy: LockedConservativePolicy) -> None:
        if self._locked_policy is not None:
            raise HoldoutRunnerError("policy_already_locked", "calibration policy is already locked")
        self._locked_policy = policy

    def final_test(self, scenario_ids: tuple[str, ...]) -> HoldoutSuiteExpectation:
        if self._locked_policy is None:
            raise HoldoutRunnerError(
                "final_gold_locked",
                "final-test Gold is unavailable before calibration policy lock",
            )
        self.final_access_count += 1
        if self.final_access_count != 1:
            raise HoldoutRunnerError(
                "final_gold_reused", "final-test Gold may be evaluated only once"
            )
        return self._selected(scenario_ids)

    def _selected(self, scenario_ids: tuple[str, ...]) -> HoldoutSuiteExpectation:
        raw = json.loads(self._path.read_text(encoding="utf-8"))
        by_id = {item["scenario_id"]: item for item in raw["scenarios"]}
        if not set(scenario_ids).issubset(by_id):
            raise HoldoutRunnerError("gold_scenario_missing", "holdout Gold scenario is missing")
        scenarios = tuple(HoldoutScenarioExpectation.model_validate(by_id[item]) for item in scenario_ids)
        return HoldoutSuiteExpectation.model_construct(
            schema_version=raw["schema_version"],
            suite_id=raw["suite_id"],
            scenarios=scenarios,
        )


def _subset_suite(
    suite: HoldoutSuiteInput, scenario_ids: tuple[str, ...]
) -> HoldoutSuiteInput:
    by_id = {item.scenario_id: item for item in suite.scenarios}
    return suite.model_copy(update={"scenarios": tuple(by_id[item] for item in scenario_ids)})


def _public_view(candidate: HoldoutCandidateInput) -> CommittedActionPublicView:
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
        public_clues=tuple(
            PublicClueFact(clue_id=item.clue_id, description=item.description)
            for item in source.public_clues
        ),
        public_result=source.public_result,
    )


def _observation(scenario: HoldoutScenarioInput) -> CaseObservation:
    return CaseObservation(
        case_id=f"case_current_{scenario.scenario_id}",
        title="公开记忆检索探针",
        synopsis="仅用于离线合成评测的公开病例简介。",
        patient_id=f"patient_{scenario.scenario_id}",
        patient_name="合成患者",
        patient_public_profile="公开架空档案。",
        session_status=CaseSessionStatus.ACTIVE,
        session_revision=0,
        discovered_clues=tuple(
            ObservedClueView(
                clue_id=f"clue_{scenario.scenario_id}_{index:02d}",
                description=description,
            )
            for index, description in enumerate(
                scenario.query.discovered_clue_descriptions, start=1
            )
        ),
        can_submit_diagnosis=False,
    )


def _query_text(scenario: HoldoutScenarioInput) -> str:
    return RetrievalQueryV2Builder().build(
        current_user_message=scenario.query.retrieval_intent,
        case_observation=_observation(scenario),
        fixed_lesson="固定课程不进入检索向量。",
    ).text


class RecordingCachingAdapter:
    """Record one real vector per canonical text and reuse it deterministically."""

    def __init__(self, delegate: EmbeddingAdapter) -> None:
        self.delegate = delegate
        self._alias_by_item_id: dict[str, str] = {}
        self._cache: dict[str, tuple[float, ...]] = {}
        self.vectors: dict[str, tuple[float, ...]] = {}
        self.text_hashes: dict[str, str] = {}
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

    def register_aliases(self, aliases: dict[str, str]) -> None:
        self._alias_by_item_id.update(aliases)

    def set_query_alias(self, alias: str) -> None:
        self._alias_by_item_id["memory_query"] = alias

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        normalized = tuple(normalize_embedding_text(item.text) for item in request.items)
        missing_indices = tuple(index for index, text in enumerate(normalized) if text not in self._cache)
        if missing_indices:
            missing_request = request.model_copy(
                update={"items": tuple(request.items[index] for index in missing_indices)}
            )
            started = time.perf_counter()
            result = self.delegate.embed(missing_request)
            self.call_latencies_ms.append((time.perf_counter() - started) * 1000.0)
            batch_size = int(getattr(getattr(self.delegate, "config", None), "batch_size", len(missing_indices)))
            self.physical_batch_count += math.ceil(len(missing_indices) / batch_size)
            self.text_count += len(missing_indices)
            for index, embedded in zip(missing_indices, result.items, strict=True):
                self._cache[normalized[index]] = embedded.vector
        items: list[EmbeddedItem] = []
        for requested, text in zip(request.items, normalized, strict=True):
            vector = self._cache[text]
            alias = self._alias_by_item_id.get(requested.item_id)
            if alias is None:
                raise HoldoutRunnerError("unregistered_embedding_item", "embedding item has no frozen alias")
            prior = self.vectors.get(alias)
            if prior is not None:
                difference = max(abs(left - right) for left, right in zip(prior, vector, strict=True))
                if difference > 1e-6:
                    raise HoldoutRunnerError("vector_repeatability_failed", "same-run vector drift exceeded tolerance")
            self.vectors[alias] = vector
            self.text_hashes[alias] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            items.append(EmbeddedItem(item_id=requested.item_id, vector=vector))
        return EmbeddingBatchResult(
            embedding_space_id=self.embedding_space_id,
            dimension=self.dimension,
            items=tuple(items),
        )


def _lifecycle_operation(
    *, candidate: HoldoutCandidateInput, memory_id: str, action: LifecycleAction
) -> MemoryCorrectionOperation | MemoryInvalidationOperation | MemoryHardDeleteOperation:
    request_id = f"holdout_{action.value}_{candidate.candidate_id}"
    common = dict(
        operation_id=stable_lifecycle_operation_id(
            action.value, candidate.source.player_id, memory_id, request_id
        ),
        request_id=request_id,
        player_id=candidate.source.player_id,
        target_memory_id=memory_id,
        trusted_boundary=TrustedMemoryBoundary.V1_APPLICATION,
        occurred_at=datetime(2026, 8, 10, 8, 0, tzinfo=timezone.utc),
    )
    if action is LifecycleAction.CORRECT:
        return MemoryCorrectionOperation(
            **common,
            reason=MemoryLifecycleReason.VERIFIED_CORRECTION,
            replacement_public_content=candidate.replacement_public_content,
        )
    if action is LifecycleAction.INVALIDATE:
        return MemoryInvalidationOperation(
            **common, reason=MemoryLifecycleReason.SOURCE_REVOKED
        )
    return MemoryHardDeleteOperation(
        **common, reason=MemoryLifecycleReason.PRIVACY_REQUEST
    )


class PreparedScenario:
    def __init__(
        self,
        *,
        scenario: HoldoutScenarioInput,
        repository: SQLiteMemoryRepository,
        aliases: dict[str, str],
        facts: tuple[RuntimeCandidateFact, ...],
        retriever: BasicCosineMemoryRetriever,
        scope: MemoryScope,
        query_text: str,
        authority_hash: str,
    ) -> None:
        self.scenario = scenario
        self.repository = repository
        self.aliases = aliases
        self.facts = facts
        self.retriever = retriever
        self.scope = scope
        self.query_text = query_text
        self.authority_hash = authority_hash


def _authority_hash(repository: SQLiteMemoryRepository, players: set[str]) -> str:
    return sha256_hex(
        {
            player_id: repository.list_memories(
                player_id=player_id, include_inactive=True
            )
            for player_id in sorted(players)
        }
    )


def _prepare_scenario(
    *,
    scenario: HoldoutScenarioInput,
    adapter: RecordingCachingAdapter,
    database_path: Path,
) -> PreparedScenario:
    (database_path.parent / "state").mkdir(parents=True, exist_ok=True)
    repository = SQLiteMemoryRepository(database_path)
    repository.initialize()
    projector = DeterministicMemoryProjector()
    aliases: dict[str, str] = {}
    original_ids: dict[str, str] = {}
    for candidate in scenario.candidates:
        source, memory = projector.project_public_view(_public_view(candidate))
        repository.write_projection(source, memory)
        aliases[memory.memory_id] = candidate.candidate_id
        original_ids[candidate.candidate_id] = memory.memory_id
        if candidate.setup in {
            HoldoutCandidateSetup.CORRECTED_ACTIVE,
            HoldoutCandidateSetup.SUPERSEDED,
        }:
            result = repository.correct_memory(
                _lifecycle_operation(
                    candidate=candidate,
                    memory_id=memory.memory_id,
                    action=LifecycleAction.CORRECT,
                )
            )
            assert result.replacement_memory_id is not None
            aliases[result.replacement_memory_id] = candidate.candidate_id
            if candidate.setup is HoldoutCandidateSetup.SUPERSEDED:
                repository.invalidate_memory(
                    _lifecycle_operation(
                        candidate=candidate,
                        memory_id=result.replacement_memory_id,
                        action=LifecycleAction.INVALIDATE,
                    )
                )
        elif candidate.setup is HoldoutCandidateSetup.INVALIDATED:
            repository.invalidate_memory(
                _lifecycle_operation(
                    candidate=candidate,
                    memory_id=memory.memory_id,
                    action=LifecycleAction.INVALIDATE,
                )
            )
        elif candidate.setup is HoldoutCandidateSetup.HARD_DELETED:
            repository.hard_delete_memory(
                _lifecycle_operation(
                    candidate=candidate,
                    memory_id=memory.memory_id,
                    action=LifecycleAction.HARD_DELETE,
                )
            )
            if not repository.tombstone_exists(memory.memory_id):
                raise HoldoutRunnerError("missing_tombstone", "hard-delete tombstone is missing")
            try:
                repository.write_projection(source, memory)
            except MemoryTombstonedError:
                pass
            else:
                raise HoldoutRunnerError("deletion_resurrection", "hard-deleted memory was restored")

    records_by_alias: dict[str, list[AuthoritativeMemoryRecord]] = {
        item.candidate_id: [] for item in scenario.candidates
    }
    players = {candidate.source.player_id for candidate in scenario.candidates}
    for player_id in sorted(players):
        for memory in repository.list_memories(player_id=player_id, include_inactive=True):
            alias = aliases.get(memory.memory_id)
            if alias is not None:
                records_by_alias[alias].append(memory)
    facts: list[RuntimeCandidateFact] = []
    for candidate in scenario.candidates:
        records = records_by_alias[candidate.candidate_id]
        if candidate.setup is HoldoutCandidateSetup.HARD_DELETED:
            if records or not repository.tombstone_exists(original_ids[candidate.candidate_id]):
                raise HoldoutRunnerError("deletion_resurrection", "hard-deleted authority still exists")
            status = "hard_deleted"
        elif candidate.setup is HoldoutCandidateSetup.SUPERSEDED:
            original = repository.get_memory(
                player_id=candidate.source.player_id,
                memory_id=original_ids[candidate.candidate_id],
            )
            if original.status is not MemoryStatus.SUPERSEDED:
                raise HoldoutRunnerError("lifecycle_state_mismatch", "superseded authority state differs")
            status = "superseded"
        elif candidate.setup is HoldoutCandidateSetup.INVALIDATED:
            original = repository.get_memory(
                player_id=candidate.source.player_id,
                memory_id=original_ids[candidate.candidate_id],
            )
            if original.status is not MemoryStatus.INVALIDATED:
                raise HoldoutRunnerError("lifecycle_state_mismatch", "invalidated authority state differs")
            status = "invalidated"
        else:
            if not any(item.status is MemoryStatus.ACTIVE for item in records):
                raise HoldoutRunnerError("authority_missing", "active candidate authority is missing")
            status = "active"
        facts.append(
            RuntimeCandidateFact(
                candidate_id=candidate.candidate_id,
                player_id=candidate.source.player_id,
                source_session_id=candidate.source.source_session_id,
                status=status,
            )
        )

    eligible_aliases = {
        item.candidate_id
        for item in facts
        if item.player_id == scenario.player_id
        and item.source_session_id != scenario.current_session_id
        and item.status == "active"
    }
    eligible_memories = tuple(
        memory
        for memory in repository.list_memories(player_id=scenario.player_id, include_inactive=False)
        if memory.source_session_id != scenario.current_session_id
        and aliases.get(memory.memory_id) in eligible_aliases
    )
    adapter.register_aliases({memory.memory_id: aliases[memory.memory_id] for memory in eligible_memories})
    index = MemoryIndexService(
        repository=repository,
        adapter=adapter,
        document_builder=EmbeddingDocumentV2Builder(),
    )
    # Product index generation is reused on the already permission-filtered set.
    records = index._embed_memories(player_id=scenario.player_id, memories=eligible_memories)
    repository.write_embeddings(player_id=scenario.player_id, records=records)
    state = index.inspect_representation_candidates(
        player_id=scenario.player_id, memories=eligible_memories
    )
    if state.status is not RepresentationIndexStatus.READY and eligible_memories:
        raise HoldoutRunnerError("memory_index_incomplete", "V2 index is not ready")
    if state.status is not RepresentationIndexStatus.EMPTY and not eligible_memories:
        raise HoldoutRunnerError("memory_index_state_invalid", "empty V2 index state is invalid")
    player = build_demo_player().model_copy(
        update={"player_id": scenario.player_id, "display_name": "合成评测学徒"}
    )
    session = CaseSessionState(
        session_id=scenario.current_session_id,
        case_id=f"case_current_{scenario.scenario_id}",
        player_id=scenario.player_id,
    )
    scope = AgentContextFilter().memory_scope(player, session)
    return PreparedScenario(
        scenario=scenario,
        repository=repository,
        aliases=aliases,
        facts=tuple(facts),
        retriever=BasicCosineMemoryRetriever(
            repository=repository,
            adapter=adapter,
            document_builder=EmbeddingDocumentV2Builder(),
        ),
        scope=scope,
        query_text=_query_text(scenario),
        authority_hash=_authority_hash(repository, players),
    )


def _policy_config(
    parameter: ConservativeParameter, embedding_space_id: str
) -> ConservativeRetrievalConfigV2:
    return ConservativeRetrievalConfigV2(
        min_similarity=parameter.min_similarity,
        max_results=parameter.max_results,
        minimum_margin=parameter.minimum_margin,
        embedding_space_id=embedding_space_id,
    )


def _search(
    prepared: PreparedScenario,
    adapter: RecordingCachingAdapter,
    parameter: ConservativeParameter,
) -> tuple[tuple[str, float], ...]:
    adapter.set_query_alias(f"query:{prepared.scenario.scenario_id}")
    result = prepared.retriever.retrieve_conservative_scoped(
        scope=prepared.scope,
        query_text=prepared.query_text,
        config=_policy_config(parameter, adapter.embedding_space_id),
    )
    AgentContextFilter().memory_views(prepared.scope, result)
    if _authority_hash(
        prepared.repository,
        {item.player_id for item in prepared.facts},
    ) != prepared.authority_hash:
        raise HoldoutRunnerError("authority_write_by_embedding", "embedding changed authority")
    return tuple((prepared.aliases[item.memory_id], item.similarity) for item in result.hits)


def _prediction(
    scenario_id: str,
    ranking: tuple[tuple[str, float], ...],
    returned: tuple[tuple[str, float], ...],
) -> HoldoutScenarioPrediction:
    return HoldoutScenarioPrediction(
        scenario_id=scenario_id,
        ranked_candidate_ids=tuple(item[0] for item in ranking),
        returned_candidate_ids=tuple(item[0] for item in returned),
    )


def _verify_expectation_against_runtime(
    prepared: PreparedScenario,
    expectation: HoldoutScenarioExpectation,
) -> None:
    facts = {item.candidate_id: item for item in prepared.facts}
    legal = {
        *expectation.relevant_candidate_ids,
        *expectation.semantic_negative_candidate_ids,
    }
    actual_legal = {
        item.candidate_id
        for item in prepared.facts
        if item.player_id == prepared.scenario.player_id
        and item.source_session_id != prepared.scenario.current_session_id
        and item.status == "active"
    }
    if legal != actual_legal:
        raise HoldoutRunnerError(
            "gold_runtime_partition_mismatch",
            "Gold legal candidates differ from committed product state",
        )
    for excluded in expectation.safety_excluded_candidates:
        fact = facts[excluded.candidate_id]
        actual: HoldoutSafetyReason | None = None
        if fact.player_id != prepared.scenario.player_id:
            actual = HoldoutSafetyReason.CROSS_PLAYER
        elif fact.source_session_id == prepared.scenario.current_session_id:
            actual = HoldoutSafetyReason.CURRENT_EPISODE
        elif fact.status == "superseded":
            actual = HoldoutSafetyReason.SUPERSEDED
        elif fact.status == "invalidated":
            actual = HoldoutSafetyReason.INVALIDATED
        elif fact.status == "hard_deleted":
            actual = HoldoutSafetyReason.HARD_DELETED
        if actual is not excluded.reason:
            raise HoldoutRunnerError(
                "gold_runtime_reason_mismatch",
                "Gold exclusion reason differs from committed product state",
            )


def _metrics_for_subset(
    *,
    suite: HoldoutSuiteInput,
    gold: HoldoutSuiteExpectation,
    scenario_ids: tuple[str, ...],
    predictions: tuple[HoldoutScenarioPrediction, ...],
) -> HoldoutEvaluationMetrics:
    return evaluate_holdout_predictions(
        suite=_subset_suite(suite, scenario_ids),
        gold=gold,
        predictions=predictions,
    )


def _policy_metrics(metrics: HoldoutEvaluationMetrics) -> HoldoutPolicyMetrics:
    return HoldoutPolicyMetrics(
        macro_f1=metrics.macro_f1,
        recall_at_3=metrics.recall_at_3,
        mrr=metrics.mrr,
        irrelevant_retrieval_rate=metrics.irrelevant_retrieval_rate,
        empty_accuracy=metrics.empty_accuracy,
        safety_total=0,
    )


def _admission(
    metrics: HoldoutEvaluationMetrics,
    config: HoldoutPreregisteredConfig,
    safety: HoldoutSafetyCounts,
) -> HoldoutAdmission:
    threshold = config.admission
    checks = {
        "recall_at_1": metrics.recall_at_1 is not None and metrics.recall_at_1 >= threshold.recall_at_1_minimum,
        "recall_at_3": metrics.recall_at_3 is not None and metrics.recall_at_3 >= threshold.recall_at_3_minimum,
        "mrr": metrics.mrr is not None and metrics.mrr >= threshold.mrr_minimum,
        "macro_f1": metrics.macro_f1 is not None and metrics.macro_f1 >= threshold.macro_f1_minimum,
        "micro_f1": metrics.micro_f1 is not None and metrics.micro_f1 >= threshold.micro_f1_minimum,
        "irrelevant_retrieval_rate": metrics.irrelevant_retrieval_rate is not None and metrics.irrelevant_retrieval_rate <= threshold.irrelevant_retrieval_rate_maximum,
        "empty_accuracy": metrics.empty_accuracy == threshold.empty_accuracy_required,
        "correction_false_negative": metrics.correction_false_negative == threshold.correction_false_negative_required,
        "negation_false_negative": metrics.negation_false_negative == threshold.negation_false_negative_required,
        "safety_total": safety.total == threshold.safety_total_required,
    }
    failed = tuple(name for name, passed in checks.items() if not passed)
    return HoldoutAdmission(single_run_quality_passed=not failed, failed_gates=failed)


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _peak_working_set_bytes() -> int:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    )
    get_process_memory_info.restype = ctypes.c_int
    process = get_current_process()
    if not get_process_memory_info(process, ctypes.byref(counters), counters.cb):
        raise HoldoutRunnerError("resource_telemetry_failed", "process memory telemetry failed")
    return int(counters.PeakWorkingSetSize)


@contextmanager
def _blocked_network() -> Iterator[list[str]]:
    attempts: list[str] = []
    original_create = socket.create_connection
    original_connect = socket.socket.connect

    def blocked(*args: object, **kwargs: object) -> None:
        del args, kwargs
        attempts.append("socket")
        raise HoldoutRunnerError("network_attempt", "network is forbidden during the local holdout")

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


@contextmanager
def _temporary_run_root(run_id: str) -> Iterator[Path]:
    root = Path(tempfile.mkdtemp(prefix=f"xuanyi-holdout-{run_id}-"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _validate_execution_identity(freeze_commit: str, output_path: Path) -> tuple[
    HoldoutSuiteInput,
    HoldoutPreregisteredConfig,
    HoldoutManifest,
]:
    if _git_value("rev-parse", "HEAD") != freeze_commit:
        raise HoldoutRunnerError("execution_commit_mismatch", "HEAD is not the authorized execution commit")
    if _git_value("status", "--porcelain"):
        raise HoldoutRunnerError("dirty_worktree", "holdout execution requires a clean worktree")
    output = output_path.resolve()
    results = (ROOT / "results").resolve()
    if results not in output.parents:
        raise HoldoutRunnerError("unsafe_output_path", "raw results must stay under results")
    suite, config, manifest = load_frozen_holdout()
    if _sha256_file(DEFAULT_MANIFEST) != "44424fc212d382c98799b67ce0d70a222acd4cf0e0809ebc0b4c070fb7f653c8":
        raise HoldoutRunnerError("holdout_identity_mismatch", "holdout manifest changed")
    if _canonical_model_manifest_sha256(DEFAULT_MODEL_MANIFEST) != config.model_manifest_sha256:
        raise HoldoutRunnerError("model_identity_mismatch", "model manifest changed")
    if _sha256_file(DEFAULT_DEPENDENCY_LOCK) != config.dependency_lock_sha256:
        raise HoldoutRunnerError("dependency_identity_mismatch", "embedding dependency lock changed")
    if _sha256_file(DEFAULT_MODEL / "model.safetensors") != MAIN_WEIGHT_SHA256:
        raise HoldoutRunnerError("model_identity_mismatch", "BGE main weight changed")
    return suite, config, manifest


def execute_holdout(
    *,
    run_id: str,
    execution_commit: str,
    suite: HoldoutSuiteInput,
    config: HoldoutPreregisteredConfig,
    manifest: HoldoutManifest,
    gold_gate: HoldoutGoldGate,
    adapter: RecordingCachingAdapter,
    temporary_root: Path,
    cold_load_ms: float | None = None,
    peak_process_bytes: int = 0,
    peak_cuda_allocated_bytes: int = 0,
    peak_cuda_reserved_bytes: int = 0,
    network_attempt_count: int = 0,
) -> HoldoutRawRunResult:
    prepared: dict[str, PreparedScenario] = {}
    for scenario in suite.scenarios:
        prepared[scenario.scenario_id] = _prepare_scenario(
            scenario=scenario,
            adapter=adapter,
            database_path=temporary_root / scenario.scenario_id / "memory.sqlite3",
        )

    calibration_gold = gold_gate.calibration(config.calibration_scenario_ids)
    calibration_gold_by_id = {item.scenario_id: item for item in calibration_gold.scenarios}
    for scenario_id, expectation in calibration_gold_by_id.items():
        _verify_expectation_against_runtime(prepared[scenario_id], expectation)
    baseline_parameter = ConservativeParameter(min_similarity=-1.0, max_results=3, minimum_margin=0.0)
    rankings: dict[str, tuple[tuple[str, float], ...]] = {}
    outcomes: list[CalibrationPolicyOutcome] = []
    policy_predictions: dict[ConservativeParameter, tuple[HoldoutScenarioPrediction, ...]] = {}
    for parameter in config.parameter_grid:
        predictions: list[HoldoutScenarioPrediction] = []
        for scenario_id in config.calibration_scenario_ids:
            item = prepared[scenario_id]
            if scenario_id not in rankings:
                rankings[scenario_id] = _search(item, adapter, baseline_parameter)
            returned = _search(item, adapter, parameter)
            expectation = calibration_gold_by_id[scenario_id]
            legal = {*expectation.relevant_candidate_ids, *expectation.semantic_negative_candidate_ids}
            if not {value[0] for value in rankings[scenario_id]}.issubset(legal) or not {value[0] for value in returned}.issubset(legal):
                raise HoldoutRunnerError("safety_candidate_entered", "safety-excluded candidate reached calibration")
            predictions.append(_prediction(scenario_id, rankings[scenario_id], returned))
        prediction_tuple = tuple(predictions)
        policy_predictions[parameter] = prediction_tuple
        metrics = _metrics_for_subset(
            suite=suite,
            gold=calibration_gold,
            scenario_ids=config.calibration_scenario_ids,
            predictions=prediction_tuple,
        )
        outcomes.append(CalibrationPolicyOutcome(parameter=parameter, evaluated_scenario_ids=config.calibration_scenario_ids, metrics=_policy_metrics(metrics)))
    try:
        selected = select_conservative_policy(outcomes=tuple(outcomes), config=config)
    except CalibrationSelectionError:
        safety = HoldoutSafetyCounts()
        resources = _resources(adapter, cold_load_ms, peak_process_bytes, peak_cuda_allocated_bytes, peak_cuda_reserved_bytes, network_attempt_count)
        ordered = tuple((key, tuple(item[0] for item in value)) for key, value in sorted(rankings.items()))
        vectors = {key: adapter.vectors[key] for key in sorted(adapter.vectors)}
        return HoldoutRawRunResult(
            run_id=run_id,
            status="fail_calibration",
            gold_freeze_commit=GOLD_FREEZE_COMMIT,
            execution_commit=execution_commit,
            input_sha256=manifest.input_sha256,
            expectation_sha256=manifest.expectation_sha256,
            config_sha256=manifest.config_sha256,
            manifest_sha256=_sha256_file(DEFAULT_MANIFEST),
            model_manifest_sha256=config.model_manifest_sha256,
            dependency_lock_sha256=config.dependency_lock_sha256,
            embedding_space_id=adapter.embedding_space_id,
            calibration_policy_outcomes=tuple(outcomes),
            scenarios=(),
            safety_counts=safety,
            ordered_result_sha256=sha256_hex(ordered),
            vector_payload_sha256=sha256_hex(vectors),
            vector_values_by_text_id=vectors,
            resources=resources,
            final_test_evaluation_count=0,
        )

    selected_calibration_predictions = policy_predictions[selected.parameter]
    calibration_metrics = _metrics_for_subset(
        suite=suite,
        gold=calibration_gold,
        scenario_ids=config.calibration_scenario_ids,
        predictions=selected_calibration_predictions,
    )
    gold_gate.lock(selected)
    final_gold = gold_gate.final_test(config.final_test_scenario_ids)
    final_gold_by_id = {item.scenario_id: item for item in final_gold.scenarios}
    for scenario_id, expectation in final_gold_by_id.items():
        _verify_expectation_against_runtime(prepared[scenario_id], expectation)
    final_predictions: list[HoldoutScenarioPrediction] = []
    returned_by_id: dict[str, tuple[tuple[str, float], ...]] = {
        item.scenario_id: tuple(
            (candidate_id, next(score for alias, score in rankings[item.scenario_id] if alias == candidate_id))
            for candidate_id in item.returned_candidate_ids
        )
        for item in selected_calibration_predictions
    }
    for scenario_id in config.final_test_scenario_ids:
        item = prepared[scenario_id]
        rankings[scenario_id] = _search(item, adapter, baseline_parameter)
        returned = _search(item, adapter, selected.parameter)
        returned_by_id[scenario_id] = returned
        expectation = final_gold_by_id[scenario_id]
        legal = {*expectation.relevant_candidate_ids, *expectation.semantic_negative_candidate_ids}
        if not {value[0] for value in rankings[scenario_id]}.issubset(legal) or not {value[0] for value in returned}.issubset(legal):
            raise HoldoutRunnerError("safety_candidate_entered", "safety-excluded candidate reached final test")
        final_predictions.append(_prediction(scenario_id, rankings[scenario_id], returned))
    final_metrics = _metrics_for_subset(
        suite=suite,
        gold=final_gold,
        scenario_ids=config.final_test_scenario_ids,
        predictions=tuple(final_predictions),
    )
    all_gold = {**calibration_gold_by_id, **final_gold_by_id}
    scenarios: list[HoldoutScenarioRun] = []
    for scenario in suite.scenarios:
        expectation = all_gold[scenario.scenario_id]
        ranking = rankings[scenario.scenario_id]
        returned = returned_by_id[scenario.scenario_id]
        facts = prepared[scenario.scenario_id].facts
        eligible = tuple(
            fact for fact in facts if fact.player_id == scenario.player_id and fact.source_session_id != scenario.current_session_id and fact.status == "active"
        )
        scenarios.append(HoldoutScenarioRun(
            scenario_id=scenario.scenario_id,
            split=scenario.split,
            ranked_candidate_ids=tuple(item[0] for item in ranking),
            ranked_similarities=tuple(item[1] for item in ranking),
            returned_candidate_ids=tuple(item[0] for item in returned),
            relevant_candidate_ids=expectation.relevant_candidate_ids,
            semantic_negative_candidate_ids=expectation.semantic_negative_candidate_ids,
            safety_excluded=tuple((item.candidate_id, item.reason) for item in expectation.safety_excluded_candidates),
            eligible_candidate_count=len(eligible),
            returned_count=len(returned),
        ))
    public_scan = canonical_json({
        "queries": {item.scenario_id: prepared[item.scenario_id].query_text for item in suite.scenarios},
        "documents": adapter.text_hashes,
        "scenarios": scenarios,
    }).casefold()
    safety = HoldoutSafetyCounts(hidden_content_leak=sum(item in public_scan for item in HIDDEN_SENTINELS))
    if safety.total or network_attempt_count:
        raise HoldoutRunnerError("safety_stop", "holdout safety hard gate failed")
    ordered = tuple((item.scenario_id, item.ranked_candidate_ids, item.returned_candidate_ids) for item in scenarios)
    vectors = {key: adapter.vectors[key] for key in sorted(adapter.vectors)}
    resources = _resources(adapter, cold_load_ms, peak_process_bytes, peak_cuda_allocated_bytes, peak_cuda_reserved_bytes, network_attempt_count)
    return HoldoutRawRunResult(
        run_id=run_id,
        status="completed",
        gold_freeze_commit=GOLD_FREEZE_COMMIT,
        execution_commit=execution_commit,
        input_sha256=manifest.input_sha256,
        expectation_sha256=manifest.expectation_sha256,
        config_sha256=manifest.config_sha256,
        manifest_sha256=_sha256_file(DEFAULT_MANIFEST),
        model_manifest_sha256=config.model_manifest_sha256,
        dependency_lock_sha256=config.dependency_lock_sha256,
        embedding_space_id=adapter.embedding_space_id,
        selected_policy=selected,
        calibration_policy_outcomes=tuple(outcomes),
        calibration_metrics=calibration_metrics,
        final_test_metrics=final_metrics,
        scenarios=tuple(scenarios),
        safety_counts=safety,
        admission=_admission(final_metrics, config, safety),
        ordered_result_sha256=sha256_hex(ordered),
        vector_payload_sha256=sha256_hex(vectors),
        vector_values_by_text_id=vectors,
        resources=resources,
        final_test_evaluation_count=gold_gate.final_access_count,
    )


def _resources(
    adapter: RecordingCachingAdapter,
    cold_load_ms: float | None,
    peak_process_bytes: int,
    peak_cuda_allocated_bytes: int,
    peak_cuda_reserved_bytes: int,
    network_attempt_count: int,
) -> HoldoutRunResources:
    latencies = adapter.call_latencies_ms
    return HoldoutRunResources(
        model_load_count=int(cold_load_ms is not None),
        local_embedding_batch_count=adapter.physical_batch_count,
        local_embedding_text_count=adapter.text_count,
        cold_load_ms=cold_load_ms,
        first_batch_ms=latencies[0] if latencies else None,
        warm_embedding_ms=sum(latencies[1:]) if len(latencies) > 1 else None,
        total_embedding_ms=sum(latencies),
        peak_process_working_set_bytes=peak_process_bytes,
        peak_cuda_allocated_bytes=peak_cuda_allocated_bytes,
        peak_cuda_reserved_bytes=peak_cuda_reserved_bytes,
        network_attempt_count=network_attempt_count,
    )


def compare_holdout_runs(
    first: HoldoutRawRunResult, second: HoldoutRawRunResult, *, tolerance: float = 1e-6
) -> HoldoutRunComparison:
    first_keys = tuple(sorted(first.vector_values_by_text_id))
    second_keys = tuple(sorted(second.vector_values_by_text_id))
    keys_equal = first_keys == second_keys
    maximum: float | None = None
    if keys_equal and first_keys:
        maximum = max(
            abs(left - right)
            for key in first_keys
            for left, right in zip(
                first.vector_values_by_text_id[key],
                second.vector_values_by_text_id[key],
                strict=True,
            )
        )
    policy_equal = first.selected_policy == second.selected_policy
    order_equal = first.ordered_result_sha256 == second.ordered_result_sha256
    metrics_equal = first.calibration_metrics == second.calibration_metrics and first.final_test_metrics == second.final_test_metrics
    passed = policy_equal and order_equal and metrics_equal and keys_equal and maximum is not None and maximum <= tolerance
    return HoldoutRunComparison(
        policy_identical=policy_equal,
        ordered_results_identical=order_equal,
        metrics_identical=metrics_equal,
        vector_keys_identical=keys_equal,
        max_vector_abs_difference=maximum,
        passed_repeatability_gate=passed,
    )


def run_local_bge(
    *, run_id: str, freeze_commit: str, output_path: Path
) -> HoldoutRawRunResult:
    suite, config, manifest = _validate_execution_identity(freeze_commit, output_path)
    # Importing Torch is intentionally below confirmation and all cheap identity gates.
    import torch

    if not torch.cuda.is_available():
        raise HoldoutRunnerError("cuda_unavailable", "frozen CUDA device is unavailable")
    torch.cuda.reset_peak_memory_stats()
    local_config = BgeM3LocalEmbeddingConfig(
        model_directory=DEFAULT_MODEL.resolve(strict=True),
        manifest_path=DEFAULT_MODEL_MANIFEST.resolve(strict=True),
        manifest_sha256=BGE_M3_VERIFIED_MANIFEST_SHA256,
        device="cuda",
        max_input_length=config.max_length_tokens,
        batch_size=FROZEN_BATCH_SIZE,
        representation_version="retrieval_v2",
        embedding_space_id=config.embedding_space_id,
    )
    base = BgeM3LocalEmbeddingAdapter(config=local_config)
    with _blocked_network() as network_attempts:
        started = time.perf_counter()
        base.load()
        torch.cuda.synchronize()
        cold_load_ms = (time.perf_counter() - started) * 1000.0
        if base.dimension != BGE_M3_DIMENSION or base.embedding_space_id != config.embedding_space_id:
            raise HoldoutRunnerError("embedding_identity_mismatch", "loaded BGE identity differs from freeze")
        adapter = RecordingCachingAdapter(base)
        with _temporary_run_root(run_id) as temporary:
            result = execute_holdout(
                run_id=run_id,
                execution_commit=freeze_commit,
                suite=suite,
                config=config,
                manifest=manifest,
                gold_gate=HoldoutGoldGate(path=DEFAULT_GOLD, expected_sha256=manifest.expectation_sha256, suite_id=suite.suite_id),
                adapter=adapter,
                temporary_root=temporary,
                cold_load_ms=cold_load_ms,
                network_attempt_count=len(network_attempts),
            )
            result = result.model_copy(
                update={
                    "resources": _resources(
                        adapter,
                        cold_load_ms,
                        _peak_working_set_bytes(),
                        int(torch.cuda.max_memory_allocated()),
                        int(torch.cuda.max_memory_reserved()),
                        len(network_attempts),
                    )
                }
            )
        if network_attempts:
            raise HoldoutRunnerError("network_attempt", "offline holdout attempted network access")
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return result


def _write_failure(path: Path, *, run_id: str, error: HoldoutRunnerError) -> None:
    try:
        resolved = path.resolve()
        if (ROOT / "results").resolve() not in resolved.parents:
            return
        resolved.parent.mkdir(parents=True, exist_ok=True)
        checkpoint = HoldoutFailureCheckpoint(
            run_id=run_id,
            execution_commit=_git_value("rev-parse", "HEAD") if (ROOT / ".git").exists() else None,
            error_code=error.error_code,
            safe_message=str(error),
        )
        resolved.write_text(checkpoint.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except Exception:
        return


def main(argv: tuple[str, ...] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the frozen 36-case local semantic holdout.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--confirm-real-vector-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_real_vector_run:
        parser.error("--confirm-real-vector-run is required before loading Torch or BGE")
    try:
        result = run_local_bge(run_id=args.run_id, freeze_commit=args.freeze_commit, output_path=args.output)
    except HoldoutRunnerError as exc:
        _write_failure(args.output, run_id=args.run_id, error=exc)
        print(json.dumps({"status": "stopped", "error_code": exc.error_code}, ensure_ascii=False), file=os.sys.stderr)
        return 2
    except Exception:
        error = HoldoutRunnerError(
            "unexpected_runner_error",
            "holdout runner stopped on an unexpected error",
        )
        _write_failure(args.output, run_id=args.run_id, error=error)
        print(
            json.dumps(
                {"status": "stopped", "error_code": error.error_code},
                ensure_ascii=False,
            ),
            file=os.sys.stderr,
        )
        return 2
    print(json.dumps({
        "run_id": result.run_id,
        "status": result.status,
        "selected_policy": None if result.selected_policy is None else result.selected_policy.parameter.model_dump(mode="json"),
        "quality_passed": None if result.admission is None else result.admission.single_run_quality_passed,
        "safety_total": result.safety_counts.total,
        "ordered_result_sha256": result.ordered_result_sha256,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
