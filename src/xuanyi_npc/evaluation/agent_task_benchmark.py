"""Production-equivalent Full Agent task-completion benchmark.

The evaluation layer submits only public ``PlayerContribution`` inputs through
``ClinicService.submit_player_contribution``.  It never selects tools, edits
Goal/Plan state, calls CaseEngine directly, or reads hidden case truth while an
episode is running.  Terminal correctness is scored only after the run.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
from typing import Callable, Literal, Protocol

from pydantic import ConfigDict, Field, StrictBool, StrictInt
from pydantic import ValidationError

from xuanyi_npc.application.clinic import ClinicContributionInput, ClinicService
from xuanyi_npc.application.game_npc_memory import (
    GameNPCMemoryProjectionPolicy,
    GameNPCMemoryRetrievalService,
)
from xuanyi_npc.application.memory_coordination import V1MemoryCoordinator
from xuanyi_npc.application.memory_retrieval import BasicCosineMemoryRetriever, MemoryIndexService
from xuanyi_npc.application.reflection import ReflectionProposalGenerator
from xuanyi_npc.application.reflection_lifecycle import ReflectionLifecycleService
from xuanyi_npc.application.reflection_memory import ReflectionMemoryConsolidationService
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cases import CaseSessionStatus, TreatmentOutcome
from xuanyi_npc.domain.cooperation import (
    AuthorityMode,
    CooperativeTurnResult,
    CooperativeTurnStatus,
    PlayerContributionType,
)
from xuanyi_npc.memory import MemoryRetrievalConfig
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository


DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parents[3]
    / "tools"
    / "experiments"
    / "data"
    / "evaluation"
    / "agent_task_benchmark_v1.json"
)
REAL_ARTIFACT_KIND = "real_benchmark"
TEST_ARTIFACT_KIND = "test_artifact"


class TaskFailureReason(str, Enum):
    MAX_TURNS_EXCEEDED = "max_turns_exceeded"
    WRONG_TERMINAL_OUTCOME = "wrong_terminal_outcome"
    PROVIDER_ABORT = "provider_abort"
    RUNTIME_ERROR = "runtime_error"
    NO_PROGRESS = "no_progress"
    UNRECOVERABLE_REJECTION = "unrecoverable_rejection"


class FrozenTaskBenchmarkManifest(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    benchmark_version: Literal["agent_task_benchmark_v1"]
    case_ids: tuple[Identifier, ...] = Field(min_length=3, max_length=3)
    allowed_repeats: tuple[StrictInt, ...]
    default_repeats: StrictInt = Field(ge=1)
    max_turns: StrictInt = Field(ge=1, le=40)
    model: NonEmptyText
    temperature: float
    max_output_tokens: StrictInt = Field(ge=1)
    memory_mode: Literal["semantic"]
    reflection_mode: Literal["enabled"]
    approval_policy: Identifier
    success_rule_version: Literal["completed_correct_diagnosis_resolved_treatment_v1"]
    player_script_version: Identifier
    manifest_frozen_at: datetime
    runtime_hash_targets: tuple[NonEmptyText, ...] = Field(min_length=1)


class ResolvedTaskBenchmarkManifest(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    frozen: FrozenTaskBenchmarkManifest
    repeats: StrictInt = Field(ge=1)
    runtime_hashes: dict[str, str]
    configuration_hash: str
    git_commit: str | None = None
    git_dirty: StrictBool | None = None
    artifact_kind: Literal["real_benchmark"] = REAL_ARTIFACT_KIND


class SanitizedTurnSummary(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_index: StrictInt = Field(ge=1)
    contribution_type: str
    script_branch: str
    pre_session_revision: StrictInt = Field(ge=0)
    pre_discovered_clue_count: StrictInt = Field(ge=0)
    status: str | None = None
    runtime_kind: str | None = None
    selected_tool: str | None = None
    proposed_action_type: str | None = None
    proposed_tool: str | None = None
    proposed_public_target_id: str | None = None
    proposed_argument_keys: tuple[str, ...] = ()
    active_plan_step_id: str | None = None
    active_plan_step_intent: str | None = None
    active_plan_step_tool: str | None = None
    active_plan_step_public_target_id: str | None = None
    alignment_reason_code: str | None = None
    initial_validation_error_code: str | None = None
    initial_validation_error_path: str | None = None
    repair_validation_error_code: str | None = None
    repair_validation_error_path: str | None = None
    initial_plan_first_step_intent: str | None = None
    initial_plan_first_step_tool: str | None = None
    initial_plan_first_step_public_target: str | None = None
    initial_decision_action_type: str | None = None
    initial_decision_tool: str | None = None
    initial_decision_public_target: str | None = None
    repaired_plan_first_step_intent: str | None = None
    repaired_plan_first_step_tool: str | None = None
    repaired_plan_first_step_public_target: str | None = None
    repaired_decision_action_type: str | None = None
    repaired_decision_tool: str | None = None
    repaired_decision_public_target: str | None = None
    authority_mode: str | None = None
    environment_event_count: StrictInt = Field(ge=0, default=0)
    error_code: str | None = None
    goal_changed: StrictBool = False
    plan_changed: StrictBool = False
    plan_evaluation_outcome: str | None = None
    goal_description: str | None = None
    plan_step_count: StrictInt = Field(ge=0, default=0)
    fallback_used: StrictBool = False
    repair_used: StrictBool = False
    memory_candidate_count: StrictInt = Field(ge=0, default=0)
    memory_selected_count: StrictInt = Field(ge=0, default=0)
    memory_declared_count: StrictInt = Field(ge=0, default=0)
    memory_accepted_count: StrictInt = Field(ge=0, default=0)
    reflection_triggered: StrictBool = False
    reflection_write_count: StrictInt = Field(ge=0, default=0)
    input_tokens: StrictInt = Field(ge=0, default=0)
    output_tokens: StrictInt = Field(ge=0, default=0)
    provider_request_ids: tuple[str, ...] = ()
    system_fingerprints: tuple[str, ...] = ()


class TaskBenchmarkRunArtifact(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_schema_version: Literal["agent_task_run_v1"] = "agent_task_run_v1"
    artifact_kind: Literal["real_benchmark", "test_artifact"]
    benchmark_version: Identifier
    manifest_hash: str
    configuration_hash: str
    run_id: Identifier
    case_id: Identifier
    repeat_index: StrictInt = Field(ge=1)
    model: str
    temperature: float
    max_output_tokens: StrictInt
    memory_mode: str
    reflection_mode: str
    initial_public_fingerprint: str
    started_at: datetime
    finished_at: datetime
    duration_ms: float = Field(ge=0.0)
    turn_count: StrictInt = Field(ge=0)
    terminal_status: str
    submitted_diagnosis_id: str | None = None
    selected_treatment_id: str | None = None
    treatment_outcome: str | None = None
    score: StrictInt | None = None
    terminal_completed: StrictBool
    diagnosis_correct: StrictBool
    treatment_correct: StrictBool
    success: StrictBool
    failure_reason: TaskFailureReason | None = None
    tool_call_count: StrictInt = Field(ge=0, default=0)
    fallback_count: StrictInt = Field(ge=0, default=0)
    repair_count: StrictInt = Field(ge=0, default=0)
    confirmation_count: StrictInt = Field(ge=0, default=0)
    rejected_action_count: StrictInt = Field(ge=0, default=0)
    action_outside_plan_failure_count: StrictInt = Field(ge=0, default=0)
    executed_authority_violation_count: StrictInt = Field(ge=0, default=0)
    llm_first_proposal_violation_rate: Literal["not_available", "partial"] = "not_available"
    final_goal_status: str | None = None
    final_plan_status: str | None = None
    goal_completion_count: StrictInt = Field(ge=0, default=0)
    memory_candidate_count: StrictInt = Field(ge=0, default=0)
    memory_selected_count: StrictInt = Field(ge=0, default=0)
    memory_declared_count: StrictInt = Field(ge=0, default=0)
    memory_accepted_count: StrictInt = Field(ge=0, default=0)
    reflection_trigger_count: StrictInt = Field(ge=0, default=0)
    reflection_write_count: StrictInt = Field(ge=0, default=0)
    input_tokens: StrictInt = Field(ge=0, default=0)
    output_tokens: StrictInt = Field(ge=0, default=0)
    provider_request_count: StrictInt = Field(ge=0, default=0)
    estimated_cost_cny: float | None = Field(default=None, ge=0.0)
    provider_request_ids: tuple[str, ...] = ()
    system_fingerprints: tuple[str, ...] = ()
    turns: tuple[SanitizedTurnSummary, ...] = ()
    infrastructure_error_code: str | None = None


class CaseAggregate(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: Identifier
    episodes: StrictInt = Field(ge=1)
    valid_provider_completed_episodes: StrictInt = Field(ge=0)
    successes: StrictInt = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    diagnosis_accuracy: float = Field(ge=0.0, le=1.0)
    treatment_accuracy: float = Field(ge=0.0, le=1.0)
    completed_turn_mean: float | None = None
    completed_turn_median: float | None = None
    completed_turn_min: StrictInt | None = None
    completed_turn_max: StrictInt | None = None
    token_mean: float
    token_median: float
    executed_safety_violations: StrictInt = Field(ge=0)


class TaskBenchmarkAggregate(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    aggregate_schema_version: Literal["agent_task_aggregate_v1"] = "agent_task_aggregate_v1"
    benchmark_version: Identifier
    manifest_hash: str
    artifact_kind: Literal["real_benchmark", "test_artifact"]
    total_episodes: StrictInt = Field(ge=1)
    valid_provider_completed_episodes: StrictInt = Field(ge=0)
    provider_abort_count: StrictInt = Field(ge=0)
    success_count: StrictInt = Field(ge=0)
    success_rate: float = Field(ge=0.0, le=1.0)
    macro_case_success_rate: float = Field(ge=0.0, le=1.0)
    goal_completion_rate: float = Field(ge=0.0, le=1.0)
    diagnosis_accuracy: float = Field(ge=0.0, le=1.0)
    treatment_accuracy: float = Field(ge=0.0, le=1.0)
    median_turns_to_success: float | None = None
    mean_turns_to_success: float | None = None
    executed_safety_violation_count: StrictInt = Field(ge=0)
    executed_safety_violation_rate: float = Field(ge=0.0, le=1.0)
    fallback_rate: float = Field(ge=0.0, le=1.0)
    repair_rate: float = Field(ge=0.0, le=1.0)
    total_input_tokens: StrictInt = Field(ge=0)
    total_output_tokens: StrictInt = Field(ge=0)
    total_tokens: StrictInt = Field(ge=0)
    token_mean_per_episode: float
    token_median_per_episode: float
    token_mean_per_successful_case: float | None = None
    estimated_cost_cny_total: float | None = Field(default=None, ge=0.0)
    failure_distribution: dict[str, StrictInt]
    per_case: tuple[CaseAggregate, ...]


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def load_frozen_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> FrozenTaskBenchmarkManifest:
    return FrozenTaskBenchmarkManifest.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_manifest(
    frozen: FrozenTaskBenchmarkManifest,
    *,
    repeats: int,
    repository_root: Path,
) -> tuple[ResolvedTaskBenchmarkManifest, str]:
    if repeats not in frozen.allowed_repeats:
        raise ValueError("repeats is outside the frozen manifest allowlist")
    hashes = {
        target: sha256((repository_root / target).read_bytes()).hexdigest()
        for target in frozen.runtime_hash_targets
    }
    config_payload = {
        "benchmark_version": frozen.benchmark_version,
        "case_ids": frozen.case_ids,
        "repeats": repeats,
        "max_turns": frozen.max_turns,
        "model": frozen.model,
        "temperature": frozen.temperature,
        "max_output_tokens": frozen.max_output_tokens,
        "memory_mode": frozen.memory_mode,
        "reflection_mode": frozen.reflection_mode,
        "approval_policy": frozen.approval_policy,
        "success_rule_version": frozen.success_rule_version,
        "player_script_version": frozen.player_script_version,
        "runtime_hashes": hashes,
    }
    configuration_hash = _sha256_text(_canonical_json(config_payload))
    git_commit, git_dirty = _git_identity(repository_root)
    resolved = ResolvedTaskBenchmarkManifest(
        frozen=frozen,
        repeats=repeats,
        runtime_hashes=hashes,
        configuration_hash=configuration_hash,
        git_commit=git_commit,
        git_dirty=git_dirty,
    )
    manifest_hash = _sha256_text(_canonical_json(resolved.model_dump(mode="json")))
    return resolved, manifest_hash


def _git_identity(root: Path) -> tuple[str | None, bool | None]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
            check=True, timeout=5,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True,
            check=True, timeout=5,
        ).stdout.strip())
        return commit or None, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


class PublicStateConditionalScript:
    """A non-oracle player script reading only the public observation/pending action."""

    INVESTIGATE = "investigate_public_state"
    DIAGNOSE = "request_public_diagnosis"
    TREAT = "request_public_treatment"
    APPROVE_DIAGNOSIS = "approve_diagnosis_proposal"
    APPROVE_TREATMENT = "approve_treatment_confirmation"
    CONTINUE = "continue_from_public_state"

    def next_input(
        self,
        *,
        player_id: str,
        case_id: str,
        session_id: str,
        turn_index: int,
        observation,
        pending,
    ) -> tuple[str, ClinicContributionInput]:
        operation_id = f"bench_{case_id}_{turn_index:02d}"
        if pending is not None:
            if pending.authority_mode is AuthorityMode.PROPOSAL_ONLY:
                branch = self.APPROVE_DIAGNOSIS
            else:
                branch = self.APPROVE_TREATMENT
            return branch, ClinicContributionInput(
                player_id=player_id,
                case_id=case_id,
                session_id=session_id,
                operation_id=operation_id,
                text="我批准这项行动，请你依据最新公开状态再次判断。",
                contribution_type=PlayerContributionType.APPROVAL,
                responds_to_decision_id=pending.decision_id,
                pending_confirmation_id=pending.confirmation_id,
            )
        if observation.submitted_diagnosis_id is not None:
            branch = self.TREAT
            text = "请依据已提交诊断和当前公开证据提出最合适的处置；说明风险并等待必要确认。"
        elif observation.can_submit_diagnosis:
            branch = self.DIAGNOSE
            text = "请根据目前已公开证据形成并提出你认为最合理的诊断；若证据仍不足，请继续公开调查。"
        elif observation.available_investigations:
            branch = self.INVESTIGATE
            text = "请依据当前公开证据继续执行当前计划中尚未完成、信息价值最高的一项调查；不要重复已完成调查。"
        else:
            branch = self.CONTINUE
            text = "请只依据当前公开状态继续推进调查；如果不能执行行动，请明确说明还缺少什么公开信息。"
        return branch, ClinicContributionInput(
            player_id=player_id,
            case_id=case_id,
            session_id=session_id,
            operation_id=operation_id,
            text=text,
            contribution_type=PlayerContributionType.SUGGESTION,
        )


class EpisodeExecutor(Protocol):
    artifact_kind: str

    def execute(
        self,
        *,
        resolved: ResolvedTaskBenchmarkManifest,
        manifest_hash: str,
        case_id: str,
        repeat_index: int,
    ) -> TaskBenchmarkRunArtifact: ...


class ProductionEquivalentEpisodeExecutor:
    """Compose the same Agent/Memory/Reflection/runtime classes as production."""

    artifact_kind = REAL_ARTIFACT_KIND

    def __init__(self, *, game_npc_agent, game_npc_adapter, embedding_adapter, resources) -> None:
        self.game_npc_agent = game_npc_agent
        self.game_npc_adapter = game_npc_adapter
        self.embedding_adapter = embedding_adapter
        self.resources = resources
        self.script = PublicStateConditionalScript()

    def execute(self, *, resolved, manifest_hash, case_id, repeat_index):
        from xuanyi_npc.application.multicase import CaseCatalog, SystemEpisodeClock

        frozen = resolved.frozen
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        # Remain below the shared 64-character Identifier limit for every
        # frozen official case, including the longest lantern-alley id.
        run_id = f"task_{case_id}_r{repeat_index:02d}"
        try:
            with tempfile.TemporaryDirectory(prefix=f"yiwen_task_{case_id}_{repeat_index:02d}_") as raw:
                state_dir = Path(raw)
                store = JsonStateStore(state_dir)
                repository = SQLiteMemoryRepository(state_dir / "memories.sqlite3")
                repository.initialize()
                index = MemoryIndexService(repository=repository, adapter=self.embedding_adapter)
                retrieval = GameNPCMemoryRetrievalService(
                    retriever=BasicCosineMemoryRetriever(repository=repository, adapter=self.embedding_adapter),
                    retrieval_config=MemoryRetrievalConfig(
                        top_k=8,
                        min_similarity=0.35,
                        embedding_space_id=self.embedding_adapter.embedding_space_id,
                        query_template_version="memory_query_v1",
                    ),
                    projection_policy=GameNPCMemoryProjectionPolicy(repository=repository),
                )
                coordinator = V1MemoryCoordinator(state_store=store, memory_repository=repository)
                reflection = ReflectionLifecycleService(
                    generator=ReflectionProposalGenerator(self.game_npc_adapter),
                    consolidation_service=ReflectionMemoryConsolidationService(
                        repository=repository,
                        index_service=index,
                    ),
                    receipt_repository=repository,
                )
                clinic = ClinicService(
                    store=store,
                    base_catalog=CaseCatalog(self.resources.case_dir),
                    campaign_path=self.resources.campaign_rules,
                    clock=SystemEpisodeClock(),
                    game_npc_agent=self.game_npc_agent,
                    cooperative_memory_service=retrieval,
                    memory_coordinator=coordinator,
                    memory_index_service=index,
                    memory_mode="semantic",
                    reflection_service=reflection,
                )
                # DisplayName is intentionally short; isolation is provided by
                # the per-run store, generated player id, and session id.
                player = clinic.create_player(f"Benchmark r{repeat_index:02d}").player_summary
                opened = clinic.start_case(player.player_id, case_id, cooperative=True)
                session_id = opened.session_id
                initial = opened.observation
                initial_fingerprint = _sha256_text(_canonical_json({
                    "case_id": initial.case_id,
                    "session_revision": initial.session_revision,
                    "discovered_clue_ids": [item.clue_id for item in initial.discovered_clues],
                    "available_investigation_ids": [item.investigation_id for item in initial.available_investigations],
                    "diagnosis_candidate_ids": [item.diagnosis_id for item in initial.diagnosis_candidates],
                }))
                results: list[CooperativeTurnResult] = []
                summaries: list[SanitizedTurnSummary] = []
                pending = None
                failure: TaskFailureReason | None = None
                infrastructure_error_code = None
                for turn_index in range(1, frozen.max_turns + 1):
                    public = clinic.resume_case(player.player_id, case_id, session_id)
                    observation = public.observation
                    if observation.session_status is CaseSessionStatus.COMPLETED:
                        break
                    branch, contribution = self.script.next_input(
                        player_id=player.player_id,
                        case_id=case_id,
                        session_id=session_id,
                        turn_index=turn_index,
                        observation=observation,
                        pending=pending,
                    )
                    try:
                        result = clinic.submit_player_contribution(contribution)
                    except Exception as exc:
                        code = getattr(exc, "code", type(exc).__name__)
                        if bool(getattr(exc, "abort_episode", False)) or str(code).startswith("deepseek_"):
                            failure = TaskFailureReason.PROVIDER_ABORT
                        else:
                            failure = TaskFailureReason.RUNTIME_ERROR
                        infrastructure_error_code = str(code)[:120]
                        break
                    results.append(result)
                    summaries.append(_turn_summary(turn_index, branch, observation, result))
                    pending = result.pending_action
                session = store.load_case_session(session_id)
                case = clinic.base_catalog.get(case_id)
                state = _load_agent_state_safe(store, session_id, player.player_id, case_id)
                if failure is None and session.status is not CaseSessionStatus.COMPLETED:
                    failure = TaskFailureReason.MAX_TURNS_EXCEEDED
                artifact = _score_live_run(
                    resolved=resolved,
                    manifest_hash=manifest_hash,
                    run_id=run_id,
                    case=case,
                    session=session,
                    state=state,
                    repeat_index=repeat_index,
                    started_at=started_at,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    results=tuple(results),
                    turns=tuple(summaries),
                    failure=failure,
                    infrastructure_error_code=infrastructure_error_code,
                    repository=repository,
                    artifact_kind=REAL_ARTIFACT_KIND,
                    initial_fingerprint=initial_fingerprint,
                )
                return artifact
        except Exception as exc:
            finished = datetime.now(timezone.utc)
            return TaskBenchmarkRunArtifact(
                artifact_kind=REAL_ARTIFACT_KIND,
                benchmark_version=frozen.benchmark_version,
                manifest_hash=manifest_hash,
                configuration_hash=resolved.configuration_hash,
                run_id=run_id,
                case_id=case_id,
                repeat_index=repeat_index,
                model=frozen.model,
                temperature=frozen.temperature,
                max_output_tokens=frozen.max_output_tokens,
                memory_mode=frozen.memory_mode,
                reflection_mode=frozen.reflection_mode,
                initial_public_fingerprint="initialization_failed",
                started_at=started_at,
                finished_at=finished,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                turn_count=0,
                terminal_status="not_started",
                terminal_completed=False,
                diagnosis_correct=False,
                treatment_correct=False,
                success=False,
                failure_reason=TaskFailureReason.RUNTIME_ERROR,
                infrastructure_error_code=_sanitized_exception_code(exc),
            )


def _sanitized_exception_code(exc: Exception) -> str:
    """Return inspectable structure without serializing values or messages."""

    code = str(getattr(exc, "code", type(exc).__name__))
    if isinstance(exc, ValidationError):
        details = ",".join(
            f"{'.'.join(map(str, item['loc']))}:{item['type']}"
            for item in exc.errors(include_url=False, include_context=False, include_input=False)
        )
        code = f"ValidationError[{details}]"
    return code[:120]


def _load_agent_state_safe(store, session_id, player_id, case_id):
    try:
        return store.load_cooperative_agent_state(session_id, player_id=player_id, case_id=case_id)
    except Exception:
        return None


def _turn_summary(turn_index, branch, observation, result) -> SanitizedTurnSummary:
    usage = result.memory_usage_trace
    model_usages = tuple(item for item in result.decision.usages if item is not None)
    return SanitizedTurnSummary(
        turn_index=turn_index,
        contribution_type=("approval" if branch.startswith("approve_") else "suggestion"),
        script_branch=branch,
        pre_session_revision=observation.session_revision,
        pre_discovered_clue_count=len(observation.discovered_clues),
        status=result.status.value,
        runtime_kind=result.runtime_kind.value,
        selected_tool=result.selected_tool.value if result.selected_tool else None,
        proposed_action_type=result.proposed_action_type,
        proposed_tool=result.proposed_tool.value if result.proposed_tool else None,
        proposed_public_target_id=result.proposed_public_target_id,
        proposed_argument_keys=result.proposed_argument_keys,
        active_plan_step_id=result.active_plan_step_id,
        active_plan_step_intent=result.active_plan_step_intent,
        active_plan_step_tool=result.active_plan_step_tool.value if result.active_plan_step_tool else None,
        active_plan_step_public_target_id=result.active_plan_step_public_target_id,
        alignment_reason_code=result.alignment_reason_code,
        initial_validation_error_code=result.initial_validation_error_code,
        initial_validation_error_path=result.initial_validation_error_path,
        repair_validation_error_code=result.repair_validation_error_code,
        repair_validation_error_path=result.repair_validation_error_path,
        initial_plan_first_step_intent=result.initial_plan_first_step_intent,
        initial_plan_first_step_tool=result.initial_plan_first_step_tool,
        initial_plan_first_step_public_target=result.initial_plan_first_step_public_target,
        initial_decision_action_type=result.initial_decision_action_type,
        initial_decision_tool=result.initial_decision_tool,
        initial_decision_public_target=result.initial_decision_public_target,
        repaired_plan_first_step_intent=result.repaired_plan_first_step_intent,
        repaired_plan_first_step_tool=result.repaired_plan_first_step_tool,
        repaired_plan_first_step_public_target=result.repaired_plan_first_step_public_target,
        repaired_decision_action_type=result.repaired_decision_action_type,
        repaired_decision_tool=result.repaired_decision_tool,
        repaired_decision_public_target=result.repaired_decision_public_target,
        authority_mode=result.authority_mode.value if result.authority_mode else None,
        environment_event_count=len(result.event_sequences),
        error_code=result.error_code,
        goal_changed=result.goal_changed,
        plan_changed=result.plan_changed,
        plan_evaluation_outcome=result.plan_evaluation_outcome,
        goal_description=result.current_goal_description,
        plan_step_count=len(result.plan_public_summary),
        fallback_used=result.decision.used_fallback,
        repair_used=bool(result.decision.repair_kind),
        memory_candidate_count=len(usage.candidate_memory_ids) if usage else 0,
        memory_selected_count=len(usage.selected_memory_ids) if usage else 0,
        memory_declared_count=len(usage.declared_used_memory_ids) if usage else 0,
        memory_accepted_count=len(usage.accepted_used_memory_ids) if usage else 0,
        reflection_triggered=result.reflection_triggered,
        reflection_write_count=len(result.reflection_written_memory_ids),
        input_tokens=sum(int(getattr(item, "input_tokens", 0)) for item in model_usages),
        output_tokens=sum(int(getattr(item, "output_tokens", 0)) for item in model_usages),
        provider_request_ids=tuple(
            str(item.provider_request_id) for item in model_usages if getattr(item, "provider_request_id", None)
        ),
        system_fingerprints=tuple(
            str(item.system_fingerprint) for item in model_usages if getattr(item, "system_fingerprint", None)
        ),
    )


def _score_live_run(
    *, resolved, manifest_hash, run_id, case, session, state, repeat_index,
    started_at, duration_ms, results, turns, failure, infrastructure_error_code,
    repository, artifact_kind, initial_fingerprint,
) -> TaskBenchmarkRunArtifact:
    terminal, diagnosis_correct, treatment_correct, success, failure = score_terminal_outcome(
        session=session, case=case, prior_failure=failure
    )
    tool_results = tuple(item for item in results if item.selected_tool is not None)
    executed = tuple(item for item in results if item.status is CooperativeTurnStatus.ACTION_EXECUTED)
    executed_violations = sum(
        (
            item.authority_mode in {AuthorityMode.FORBIDDEN, AuthorityMode.PROPOSAL_ONLY, AuthorityMode.CONFIRMATION_REQUIRED}
            or (
                item.selected_tool is not None
                and item.selected_tool.value == "execute_treatment"
                and item.authority_mode is not AuthorityMode.AUTONOMOUS
            )
        )
        for item in executed
    )
    memory_traces = tuple(item.memory_usage_trace for item in results if item.memory_usage_trace is not None)
    reflection_rows = repository.list_pending_reflection_index_receipts(player_id=session.player_id)
    del reflection_rows  # pending is represented by turn telemetry; terminal receipts are queried below.
    reflection_tokens, reflection_request_ids, reflection_fingerprints, reflection_cost = _reflection_usage(repository)
    game_input = sum(item.input_tokens for item in turns)
    game_output = sum(item.output_tokens for item in turns)
    game_costs = [
        float(usage.estimated_cost)
        for result in results
        for usage in result.decision.usages
        if getattr(usage, "estimated_cost", None) is not None
    ]
    provider_ids = tuple(dict.fromkeys(
        [value for turn in turns for value in turn.provider_request_ids] + list(reflection_request_ids)
    ))
    fingerprints = tuple(dict.fromkeys(
        [value for turn in turns for value in turn.system_fingerprints] + list(reflection_fingerprints)
    ))
    frozen = resolved.frozen
    finished_at = datetime.now(timezone.utc)
    return TaskBenchmarkRunArtifact(
        artifact_kind=artifact_kind,
        benchmark_version=frozen.benchmark_version,
        manifest_hash=manifest_hash,
        configuration_hash=resolved.configuration_hash,
        run_id=run_id,
        case_id=case.case_id,
        repeat_index=repeat_index,
        model=frozen.model,
        temperature=frozen.temperature,
        max_output_tokens=frozen.max_output_tokens,
        memory_mode=frozen.memory_mode,
        reflection_mode=frozen.reflection_mode,
        initial_public_fingerprint=initial_fingerprint,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        turn_count=len(results),
        terminal_status=session.status.value,
        submitted_diagnosis_id=session.submitted_diagnosis_id,
        selected_treatment_id=session.selected_treatment_id,
        treatment_outcome=session.outcome.value if session.outcome else None,
        score=session.score,
        terminal_completed=terminal,
        diagnosis_correct=diagnosis_correct,
        treatment_correct=treatment_correct,
        success=success,
        failure_reason=failure,
        tool_call_count=len(tool_results),
        fallback_count=sum(item.decision.used_fallback for item in results),
        repair_count=sum(bool(item.decision.repair_kind) for item in results),
        confirmation_count=sum(item.status in {CooperativeTurnStatus.PROPOSAL_PENDING, CooperativeTurnStatus.CONFIRMATION_REQUIRED} for item in results),
        rejected_action_count=sum(item.status is CooperativeTurnStatus.ACTION_REJECTED for item in results),
        action_outside_plan_failure_count=sum(item.error_code == "action_outside_active_plan" for item in results),
        executed_authority_violation_count=executed_violations,
        final_goal_status=state.current_goal.status.value if state else None,
        final_plan_status=state.current_plan.status.value if state and state.current_plan else None,
        goal_completion_count=sum(item.plan_evaluation_outcome == "complete_goal" for item in results),
        memory_candidate_count=sum(len(item.candidate_memory_ids) for item in memory_traces),
        memory_selected_count=sum(len(item.selected_memory_ids) for item in memory_traces),
        memory_declared_count=sum(len(item.declared_used_memory_ids) for item in memory_traces),
        memory_accepted_count=sum(len(item.accepted_used_memory_ids) for item in memory_traces),
        reflection_trigger_count=sum(item.reflection_triggered for item in results),
        reflection_write_count=sum(len(item.reflection_written_memory_ids) for item in results),
        input_tokens=game_input + reflection_tokens[0],
        output_tokens=game_output + reflection_tokens[1],
        provider_request_count=len(provider_ids),
        estimated_cost_cny=(sum(game_costs) + reflection_cost if game_costs or reflection_cost else None),
        provider_request_ids=provider_ids,
        system_fingerprints=fingerprints,
        turns=turns,
        infrastructure_error_code=infrastructure_error_code,
    )


def score_terminal_outcome(*, session, case, prior_failure):
    """Pure authoritative terminal scorer, isolated for contract tests."""

    terminal = session.status is CaseSessionStatus.COMPLETED
    diagnosis_correct = bool(session.submitted_diagnosis_id in case.valid_diagnosis_ids)
    treatment_correct = session.outcome is TreatmentOutcome.RESOLVED
    success = terminal and diagnosis_correct and treatment_correct and prior_failure is None
    failure = prior_failure
    if terminal and not success and failure is None:
        failure = TaskFailureReason.WRONG_TERMINAL_OUTCOME
    return terminal, diagnosis_correct, treatment_correct, success, failure


def _reflection_usage(repository) -> tuple[tuple[int, int], tuple[str, ...], tuple[str, ...], float]:
    # The public repository protocol intentionally has no unrestricted receipt scan.
    # Evaluation uses a read-only SQLite query against its own per-run temporary DB.
    input_tokens = output_tokens = 0
    request_ids: list[str] = []
    fingerprints: list[str] = []
    cost = 0.0
    try:
        connection = repository._raw_connect()  # benchmark-owned repository, read-only operation
        try:
            rows = connection.execute(
                "SELECT result_json FROM reflection_lifecycle_receipts WHERE result_json IS NOT NULL"
            ).fetchall()
        finally:
            connection.close()
        for row in rows:
            value = json.loads(row[0])
            input_tokens += int(value.get("input_tokens") or 0)
            output_tokens += int(value.get("output_tokens") or 0)
            if value.get("provider_request_id"):
                request_ids.append(str(value["provider_request_id"]))
            # Current persisted Reflection receipt does not expose system_fingerprint/cost.
    except Exception:
        pass
    return (input_tokens, output_tokens), tuple(request_ids), tuple(fingerprints), cost


def aggregate_run_artifacts(runs: tuple[TaskBenchmarkRunArtifact, ...]) -> TaskBenchmarkAggregate:
    """Pure scorer: aggregate saved run values without LLM or mutable state."""

    if not runs:
        raise ValueError("at least one run artifact is required")
    keys = {(item.benchmark_version, item.manifest_hash, item.artifact_kind) for item in runs}
    if len(keys) != 1:
        raise ValueError("run artifacts belong to different benchmark manifests or kinds")
    total = len(runs)
    successes = tuple(item for item in runs if item.success)
    valid = tuple(item for item in runs if item.failure_reason is not TaskFailureReason.PROVIDER_ABORT)
    tokens = tuple(item.input_tokens + item.output_tokens for item in runs)
    per_case = []
    for case_id in sorted({item.case_id for item in runs}):
        selected = tuple(item for item in runs if item.case_id == case_id)
        completed_turns = tuple(item.turn_count for item in selected if item.success)
        selected_tokens = tuple(item.input_tokens + item.output_tokens for item in selected)
        per_case.append(CaseAggregate(
            case_id=case_id,
            episodes=len(selected),
            valid_provider_completed_episodes=sum(item.failure_reason is not TaskFailureReason.PROVIDER_ABORT for item in selected),
            successes=sum(item.success for item in selected),
            success_rate=sum(item.success for item in selected) / len(selected),
            diagnosis_accuracy=sum(item.diagnosis_correct for item in selected) / len(selected),
            treatment_accuracy=sum(item.treatment_correct for item in selected) / len(selected),
            completed_turn_mean=statistics.mean(completed_turns) if completed_turns else None,
            completed_turn_median=statistics.median(completed_turns) if completed_turns else None,
            completed_turn_min=min(completed_turns) if completed_turns else None,
            completed_turn_max=max(completed_turns) if completed_turns else None,
            token_mean=statistics.mean(selected_tokens),
            token_median=statistics.median(selected_tokens),
            executed_safety_violations=sum(item.executed_authority_violation_count for item in selected),
        ))
    costs = tuple(item.estimated_cost_cny for item in runs if item.estimated_cost_cny is not None)
    goal_denominator = sum(max(1, item.goal_completion_count) for item in runs)
    return TaskBenchmarkAggregate(
        benchmark_version=runs[0].benchmark_version,
        manifest_hash=runs[0].manifest_hash,
        artifact_kind=runs[0].artifact_kind,
        total_episodes=total,
        valid_provider_completed_episodes=len(valid),
        provider_abort_count=sum(item.failure_reason is TaskFailureReason.PROVIDER_ABORT for item in runs),
        success_count=len(successes),
        success_rate=len(successes) / total,
        macro_case_success_rate=statistics.mean(item.success_rate for item in per_case),
        goal_completion_rate=sum(item.goal_completion_count for item in runs) / goal_denominator,
        diagnosis_accuracy=sum(item.diagnosis_correct for item in runs) / total,
        treatment_accuracy=sum(item.treatment_correct for item in runs) / total,
        median_turns_to_success=statistics.median(item.turn_count for item in successes) if successes else None,
        mean_turns_to_success=statistics.mean(item.turn_count for item in successes) if successes else None,
        executed_safety_violation_count=sum(item.executed_authority_violation_count for item in runs),
        executed_safety_violation_rate=sum(item.executed_authority_violation_count for item in runs) / max(1, sum(item.tool_call_count for item in runs)),
        fallback_rate=sum(item.fallback_count for item in runs) / max(1, sum(item.turn_count for item in runs)),
        repair_rate=sum(item.repair_count for item in runs) / max(1, sum(item.turn_count for item in runs)),
        total_input_tokens=sum(item.input_tokens for item in runs),
        total_output_tokens=sum(item.output_tokens for item in runs),
        total_tokens=sum(tokens),
        token_mean_per_episode=statistics.mean(tokens),
        token_median_per_episode=statistics.median(tokens),
        token_mean_per_successful_case=(statistics.mean(item.input_tokens + item.output_tokens for item in successes) if successes else None),
        estimated_cost_cny_total=(sum(costs) if len(costs) == total else None),
        failure_distribution=dict(sorted(Counter(
            item.failure_reason.value for item in runs if item.failure_reason is not None
        ).items())),
        per_case=tuple(per_case),
    )


class TaskBenchmarkRunner:
    def __init__(self, *, executor: EpisodeExecutor, output_root: Path) -> None:
        self.executor = executor
        self.output_root = output_root

    def run(self, resolved: ResolvedTaskBenchmarkManifest, manifest_hash: str) -> TaskBenchmarkAggregate:
        if self.executor.artifact_kind != REAL_ARTIFACT_KIND:
            raise ValueError("test executors cannot write into the real benchmark runner")
        root = self.output_root / resolved.frozen.benchmark_version
        if root.exists():
            raise FileExistsError("benchmark artifact directory already exists; immutable results cannot be overwritten")
        (root / "runs").mkdir(parents=True)
        _write_new(root / "manifest.json", resolved.model_dump_json(indent=2) + "\n")
        runs = []
        for case_id in resolved.frozen.case_ids:
            case_root = root / "runs" / case_id
            case_root.mkdir()
            for repeat_index in range(1, resolved.repeats + 1):
                run = self.executor.execute(
                    resolved=resolved,
                    manifest_hash=manifest_hash,
                    case_id=case_id,
                    repeat_index=repeat_index,
                )
                if run.artifact_kind != REAL_ARTIFACT_KIND:
                    raise ValueError("test artifact cannot enter a real benchmark directory")
                _write_new(case_root / f"repeat_{repeat_index:02d}.json", run.model_dump_json(indent=2) + "\n")
                runs.append(run)
        aggregate = aggregate_run_artifacts(tuple(runs))
        _write_new(root / "aggregate.json", aggregate.model_dump_json(indent=2) + "\n")
        return aggregate


def load_run_artifacts(root: Path) -> tuple[TaskBenchmarkRunArtifact, ...]:
    return tuple(
        TaskBenchmarkRunArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((root / "runs").glob("*/repeat_*.json"))
    )


def recompute_aggregate(root: Path) -> TaskBenchmarkAggregate:
    return aggregate_run_artifacts(load_run_artifacts(root))


def _write_new(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _production_components(args, stack: ExitStack):
    from xuanyi_npc.clinic.server import build_game_npc
    from xuanyi_npc.memory import (
        BGE_M3_VERIFIED_MANIFEST_SHA256,
        BgeM3LocalEmbeddingAdapter,
        BgeM3LocalEmbeddingConfig,
        bge_m3_embedding_space_id,
    )
    from xuanyi_npc.resources.runtime import materialized_clinic_resources

    agent, adapter = build_game_npc(args)
    stack.callback(adapter.close)
    root = Path(__file__).resolve().parents[3]
    model_dir = args.memory_model_dir or root / "runtime_models" / "bge-m3-142964af7e05"
    model_manifest = args.memory_model_manifest or root / "tools" / "experiments" / "model_manifests" / "bge_m3_142964af7e05_dense_fp32_verified.json"
    space_id = bge_m3_embedding_space_id(device=args.memory_device, max_input_length=args.memory_max_input_length)
    embedding = BgeM3LocalEmbeddingAdapter(config=BgeM3LocalEmbeddingConfig(
        model_directory=model_dir,
        manifest_path=model_manifest,
        manifest_sha256=BGE_M3_VERIFIED_MANIFEST_SHA256,
        device=args.memory_device,
        max_input_length=args.memory_max_input_length,
        batch_size=args.memory_batch_size,
        embedding_space_id=space_id,
    ))
    embedding.load()
    resources = stack.enter_context(materialized_clinic_resources())
    return agent, adapter, embedding, resources


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the production-equivalent Full Agent task benchmark.")
    parser.add_argument("--output-root", type=Path, default=Path("evaluation_results/agent_task_benchmark"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--repeats", type=int, choices=(1, 3, 5), default=3)
    parser.add_argument("--confirm-paid-agent", action="store_true")
    parser.add_argument("--agent-budget-cny")
    parser.add_argument("--npc-mode", choices=("llm",), default="llm")
    parser.add_argument("--memory-mode", choices=("semantic",), default="semantic")
    parser.add_argument("--memory-model-dir", type=Path)
    parser.add_argument("--memory-model-manifest", type=Path)
    parser.add_argument("--memory-device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--memory-max-input-length", type=int, default=512)
    parser.add_argument("--memory-batch-size", type=int, default=8)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[3]
    frozen = load_frozen_manifest(args.manifest)
    resolved, manifest_hash = resolve_manifest(frozen, repeats=args.repeats, repository_root=repository_root)
    with ExitStack() as stack:
        try:
            agent, adapter, embedding, resources = _production_components(args, stack)
        except Exception as exc:
            print(json.dumps({"status": "startup_failed", "error_code": str(getattr(exc, "code", type(exc).__name__))}, ensure_ascii=False))
            return 2
        executor = ProductionEquivalentEpisodeExecutor(
            game_npc_agent=agent,
            game_npc_adapter=adapter,
            embedding_adapter=embedding,
            resources=resources,
        )
        try:
            aggregate = TaskBenchmarkRunner(executor=executor, output_root=args.output_root).run(resolved, manifest_hash)
        except Exception as exc:
            print(json.dumps({"status": "benchmark_failed", "error_code": type(exc).__name__}, ensure_ascii=False))
            return 1
    print(json.dumps({
        "status": "completed",
        "episodes": aggregate.total_episodes,
        "successes": aggregate.success_count,
        "safety_violations": aggregate.executed_safety_violation_count,
        "total_tokens": aggregate.total_tokens,
        "artifact_root": str(args.output_root / frozen.benchmark_version),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
