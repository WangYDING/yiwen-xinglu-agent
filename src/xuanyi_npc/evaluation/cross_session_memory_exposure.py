"""Evaluation-only cross-session semantic-memory exposure harness.

This module composes production storage, projection, indexing, retrieval, runtime,
and Authority paths.  It owns no retrieval or Agent behavior.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from xuanyi_npc.agents.game_npc import DeterministicCooperativeNPC
from xuanyi_npc.application import (
    BasicCosineMemoryRetriever,
    GameNPCMemoryProjectionPolicy,
    GameNPCMemoryRetrievalConfig,
    GameNPCMemoryRetrievalService,
    MemoryIndexService,
    V1MemoryCoordinator,
)
from xuanyi_npc.application.clinic import ClinicActionInput, ClinicContributionInput, ClinicService
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.memory import MemoryRetrievalConfig
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository


SUITE_ID = "cross_session_memory_exposure_v1"


class ExposureScenario(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scenario_id: Identifier
    condition: Literal["positive_transfer", "irrelevant_memory_negative", "empty_history_control"]
    session_a_case_id: Identifier | None = None
    session_a_investigation_id: Identifier | None = None
    session_b_case_id: Identifier
    expected_relation: NonEmptyText


class ExposureManifest(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    suite_id: Literal["cross_session_memory_exposure_v1"]
    evaluation_only: Literal[True]
    schema_version: Literal["cross_session_memory_exposure_manifest_v1"]
    scenarios: tuple[ExposureScenario, ...] = Field(min_length=3, max_length=3)


class ExposureArtifact(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    suite_id: Literal["cross_session_memory_exposure_v1"] = SUITE_ID
    scenario_id: Identifier
    condition: str
    player_id_sanitized: str
    session_a_episode_id: str | None
    session_b_episode_id: str
    expected_memory_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    selected_ids: tuple[str, ...]
    declared_ids: tuple[str, ...]
    accepted_ids: tuple[str, ...]
    memory_candidate_count: int
    memory_selected_count: int
    memory_declared_used_count: int
    memory_accepted_used_count: int
    retrieved_relevant_count: int
    relevant_selected: bool
    irrelevant_retrieved: int
    false_positive_exposure: bool
    expected_empty_correct: bool
    agent_input_contains_memory_context: bool
    same_repository_path: bool
    current_session_leakage: bool
    player_isolation_violation: bool
    authority_violation: bool
    infrastructure_status: str
    provider_error: bool = False
    decision_action_type: str | None = None
    selected_tool: str | None = None
    selected_public_target: str | None = None
    turns: int = 1
    repair_count: int = 0
    fallback_count: int = 0
    provider_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_cny: float = 0.0


@dataclass
class _SequenceIds:
    prefix: str
    value: int = 0

    def _next(self) -> str:
        self.value += 1
        return f"{self.prefix}_{self.value}"

    def new_player_id(self) -> str:
        return self._next()

    def new_session_id(self) -> str:
        return self._next()


class _EvaluationClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 27, 0, 0, tzinfo=timezone.utc)


class _CapturingOfflineAgent:
    """Evaluation observer delegating decisions to the existing offline Agent."""

    def __init__(self) -> None:
        self.delegate = DeterministicCooperativeNPC()
        self.inputs = []

    def decide(self, value):
        self.inputs.append(value)
        return self.delegate.decide(value)

    def repair_action_contract(self, *args, **kwargs):
        return self.delegate.repair_action_contract(*args, **kwargs)

    def action_contract_fallback(self, *args, **kwargs):
        return self.delegate.action_contract_fallback(*args, **kwargs)


def canonical_hash(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_manifest(path: Path) -> ExposureManifest:
    return ExposureManifest.model_validate_json(path.read_text(encoding="utf-8"))


def run_scenario(
    *, scenario: ExposureScenario, state_dir: Path, resources, embedding_adapter,
    agent=None, session_a_driver=None, session_a_hook=None,
) -> ExposureArtifact:
    """Run one offline scenario; callers supply a deterministic/test embedding."""
    store = JsonStateStore(state_dir)
    repository_path = state_dir / "memories.sqlite3"
    repository = SQLiteMemoryRepository(repository_path)
    repository.initialize()
    index = MemoryIndexService(repository=repository, adapter=embedding_adapter)
    retrieval = GameNPCMemoryRetrievalService(
        retriever=BasicCosineMemoryRetriever(repository=repository, adapter=embedding_adapter),
        retrieval_config=MemoryRetrievalConfig(
            top_k=8, min_similarity=0.35,
            embedding_space_id=embedding_adapter.embedding_space_id,
            query_template_version="memory_query_v1",
        ),
        projection_policy=GameNPCMemoryProjectionPolicy(repository=repository),
        projection_config=GameNPCMemoryRetrievalConfig(),
    )
    agent = agent or _CapturingOfflineAgent()
    ids = _SequenceIds(f"eval_{scenario.scenario_id}")
    clinic = ClinicService(
        store=store, base_catalog=CaseCatalog(resources.case_dir),
        campaign_path=resources.campaign_rules, clock=_EvaluationClock(), game_npc_agent=agent,
        player_id_factory=ids, session_id_factory=ids,
        cooperative_memory_service=retrieval,
        memory_coordinator=V1MemoryCoordinator(state_store=store, memory_repository=repository),
        memory_index_service=index, memory_mode="semantic",
    )
    player_id = clinic.create_player("EVALUATION ONLY").player_summary.player_id
    session_a = None
    expected_ids: tuple[str, ...] = ()
    if scenario.session_a_case_id is not None:
        opened_a = clinic.start_case(player_id, scenario.session_a_case_id, cooperative=True)
        session_a = opened_a.session_id
        if session_a_driver is None:
            clinic.submit_case_action(ClinicActionInput(
                player_id=player_id, case_id=opened_a.case_id, session_id=opened_a.session_id,
                operation_id=f"op_{scenario.scenario_id}_a", action_type="investigation",
                selection_id=scenario.session_a_investigation_id,
            ))
        else:
            session_a_driver(clinic=clinic, player_id=player_id, opened=opened_a)
        expected_ids = tuple(
            item.memory_id for item in repository.list_memories(
                player_id=player_id, include_inactive=False
            ) if item.source_session_id == opened_a.session_id
        )
        indexed_ids = {
            item.memory_id for item in repository.list_embeddings(
                player_id=player_id, embedding_space_id=embedding_adapter.embedding_space_id
            )
        }
        if not expected_ids or not set(expected_ids).issubset(indexed_ids):
            raise RuntimeError("session A memory write/index failed")
        if session_a_hook is not None:
            session_a_hook(
                clinic=clinic, player_id=player_id, opened=opened_a,
                repository=repository, index_service=index,
                embedding_adapter=embedding_adapter, ordinary_memory_ids=expected_ids,
            )
    opened_b = clinic.start_case(player_id, scenario.session_b_case_id, cooperative=True)
    result = clinic.submit_player_contribution(ClinicContributionInput(
        player_id=player_id, case_id=opened_b.case_id, session_id=opened_b.session_id,
        operation_id=f"op_{scenario.scenario_id}_b",
        text="请依据当前公开线索选择一项安全、可逆的调查。",
    ))
    trace = result.memory_usage_trace
    candidate_ids = trace.candidate_memory_ids if trace else ()
    selected_ids = trace.selected_memory_ids if trace else ()
    declared_ids = trace.declared_used_memory_ids if trace else ()
    accepted_ids = trace.accepted_used_memory_ids if trace else ()
    relevant = set(expected_ids) if scenario.condition == "positive_transfer" else set()
    retrieved_relevant = len(relevant.intersection(candidate_ids))
    irrelevant = len(set(candidate_ids).difference(relevant))
    expected_empty = scenario.condition == "empty_history_control"
    context = agent.inputs[-1].memory_context if agent.inputs else None
    own_session_memories = repository.list_memories(player_id=player_id, include_inactive=False)
    leakage = any(item.source_episode_id == opened_b.session_id for item in (context.memories if context else ()))
    other_player = repository.list_memories(player_id=f"{player_id}_other", include_inactive=False)
    execution_getter = getattr(agent, "last_planning_execution", None)
    execution = execution_getter() if callable(execution_getter) else None
    usages = tuple(getattr(execution, "usages", ())) if execution is not None else ()
    costs = [float(item.estimated_cost) for item in usages if item.estimated_cost is not None]
    return ExposureArtifact(
        scenario_id=scenario.scenario_id, condition=scenario.condition,
        player_id_sanitized=hashlib.sha256(player_id.encode()).hexdigest()[:12],
        session_a_episode_id=session_a, session_b_episode_id=opened_b.session_id,
        expected_memory_ids=expected_ids, candidate_ids=candidate_ids, selected_ids=selected_ids,
        declared_ids=declared_ids, accepted_ids=accepted_ids,
        memory_candidate_count=len(candidate_ids), memory_selected_count=len(selected_ids),
        memory_declared_used_count=len(declared_ids), memory_accepted_used_count=len(accepted_ids),
        retrieved_relevant_count=retrieved_relevant,
        relevant_selected=bool(relevant.intersection(selected_ids)),
        irrelevant_retrieved=irrelevant, false_positive_exposure=bool(irrelevant),
        expected_empty_correct=(not expected_empty or (not candidate_ids and not selected_ids)),
        agent_input_contains_memory_context=context is not None and bool(context.memories),
        same_repository_path=repository.database_path == repository_path,
        current_session_leakage=leakage,
        player_isolation_violation=bool(other_player), authority_violation=False,
        infrastructure_status="ok" if own_session_memories or expected_empty else "memory_missing",
        decision_action_type=result.decision.proposal.action.action_type.value,
        selected_tool=result.selected_tool.value if result.selected_tool is not None else None,
        selected_public_target=result.selected_public_target,
        repair_count=1 if execution is not None and execution.repair_kind is not None else 0,
        fallback_count=1 if execution is not None and execution.output is None else 0,
        provider_requests=len(usages),
        input_tokens=sum(item.input_tokens for item in usages),
        output_tokens=sum(item.output_tokens for item in usages),
        estimated_cost_cny=sum(costs),
    )


def run_suite(*, manifest_path: Path, output_root: Path, resources, embedding_adapter_factory) -> tuple[ExposureArtifact, ...]:
    """Write sanitized, independently rooted scenario artifacts; never calls a provider."""
    manifest = load_manifest(manifest_path)
    suite_root = output_root / SUITE_ID
    suite_root.mkdir(parents=True, exist_ok=False)
    resolved = {
        "suite_id": SUITE_ID,
        "evaluation_only": True,
        "manifest_sha256": canonical_hash(manifest_path),
        "scenario_ids": [item.scenario_id for item in manifest.scenarios],
    }
    (suite_root / "manifest.json").write_text(
        json.dumps(resolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    artifacts = []
    for scenario in manifest.scenarios:
        scenario_root = suite_root / "scenarios" / scenario.scenario_id
        state_dir = scenario_root / "state"
        artifact = run_scenario(
            scenario=scenario, state_dir=state_dir, resources=resources,
            embedding_adapter=embedding_adapter_factory(),
        )
        scenario_root.mkdir(parents=True, exist_ok=True)
        (scenario_root / "artifact.json").write_text(
            artifact.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        artifacts.append(artifact)
    return tuple(artifacts)
