"""Evaluation-only matched Reflection ON/OFF composition over the E9 harness."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict

from xuanyi_npc.agents.llm import LLMResponse
from xuanyi_npc.application.clinic import ClinicActionInput
from xuanyi_npc.application.reflection import (
    PublicAssessmentEvidence,
    PublicOutcomeEvidence,
    ReflectionEvidenceBuilder,
    ReflectionProposalGenerator,
)
from xuanyi_npc.application.reflection_lifecycle import ReflectionLifecycleService
from xuanyi_npc.application.reflection_memory import ReflectionMemoryConsolidationService
from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.reflection import (
    ApplicabilityScope,
    ApplicabilityScopeType,
    EvidenceRefType,
    ReflectionConfidence,
    ReflectionProposal,
    ReflectionTrigger,
    ReflectionTriggerType,
    ReusableLessonProposal,
    ReusableLessonType,
)
from xuanyi_npc.domain.reflection_lifecycle import ReflectionLifecycleStatus
from xuanyi_npc.memory import DeterministicFakeEmbedding

from .cross_session_memory_exposure import ExposureScenario, canonical_hash, run_scenario


SUITE_ID = "cross_session_reflection_ofat_v1"


class ReflectionCondition(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    suite_id: Literal["cross_session_reflection_ofat_v1"]
    condition: Literal["control", "ablation"]
    memory_mode: Literal["semantic"]
    reflection_mode: Literal["enabled", "disabled"]
    scenario_id: Literal["matched_reflection_transfer"]
    model_placeholder: str
    memory_threshold: Literal[0.35]
    player_script: str


class ReflectionOFATArtifact(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    suite_id: str = SUITE_ID
    condition: str
    memory_mode: str
    reflection_mode: str
    manifest_hash: str
    configuration_hash: str
    session_a_episode_id: str
    session_b_episode_id: str
    ordinary_memory_ids: tuple[str, ...]
    reflection_derived_memory_ids: tuple[str, ...]
    reflection_trigger_count: int
    reflection_generation_count: int
    reflection_write_count: int
    reflection_receipt_persisted: bool
    reflection_indexed_count: int
    memory_ordinary_write_count: int
    candidate_ids: tuple[str, ...]
    selected_ids: tuple[str, ...]
    ordinary_candidate_ids: tuple[str, ...]
    reflection_derived_candidate_ids: tuple[str, ...]
    reflection_derived_selected_ids: tuple[str, ...]
    declared_ids: tuple[str, ...]
    accepted_ids: tuple[str, ...]
    ordinary_declared_ids: tuple[str, ...]
    ordinary_accepted_ids: tuple[str, ...]
    reflection_derived_declared_ids: tuple[str, ...]
    reflection_derived_accepted_ids: tuple[str, ...]
    agent_input_memory_ids: tuple[str, ...]
    provider_requests: int
    input_tokens: int
    output_tokens: int
    estimated_cost_cny: float
    duration_seconds: float
    authority_violations: int
    infrastructure_failures: int
    repository_leakage: bool
    player_isolation_violation: bool
    current_session_leakage: bool


class _ScriptedAdapter:
    def __init__(self, output: str) -> None:
        self.output = output
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return LLMResponse(content=self.output)


def load_condition(path: Path) -> ReflectionCondition:
    return ReflectionCondition.model_validate_json(path.read_text(encoding="utf-8"))


def _complete_public_session_a(*, clinic, player_id, opened) -> None:
    investigations = (
        "observe_scholar", "ask_about_memory", "inspect_umbrella",
        "observe_contract_trace", "search_book_chest", "ask_about_promise",
    )
    for index, investigation_id in enumerate(investigations, start=1):
        clinic.submit_case_action(ClinicActionInput(
            player_id=player_id, case_id=opened.case_id, session_id=opened.session_id,
            operation_id=f"e11_inv_{index}", action_type="investigation",
            selection_id=investigation_id,
        ))
    observation = clinic.resume_case(player_id, opened.case_id, opened.session_id).observation
    clinic.submit_case_action(ClinicActionInput(
        player_id=player_id, case_id=opened.case_id, session_id=opened.session_id,
        operation_id="e11_diagnosis", action_type="diagnosis",
        selection_id="rain_vow_breach",
        evidence_clue_ids=tuple(item.clue_id for item in observation.discovered_clues),
    ))
    clinic.submit_case_action(ClinicActionInput(
        player_id=player_id, case_id=opened.case_id, session_id=opened.session_id,
        operation_id="e11_treatment", action_type="treatment",
        selection_id="return_token_and_fulfill_vow",
    ))


def _reflection_hook(state: dict, adapter_override=None):
    def hook(*, player_id, opened, repository, index_service, embedding_adapter, **_):
        trigger = ReflectionTrigger.create(
            trigger_type=ReflectionTriggerType.EPISODE_COMPLETED,
            episode_id=opened.session_id, case_id=opened.case_id,
            lifecycle_event_id=f"e11_completed_{opened.session_id}",
            reason="The public evaluation episode reached its completed lifecycle boundary.",
        )
        outcome = PublicOutcomeEvidence(
            outcome_id="e11_public_outcome",
            public_summary="The completed public investigation gathered reversible evidence before treatment.",
        )
        assessment = PublicAssessmentEvidence(
            assessment_id="e11_public_assessment",
            public_summary="The public completion state confirms evidence gathering preceded the final intervention.",
        )
        bundle = ReflectionEvidenceBuilder().build(
            trigger, tool_outcomes=(outcome,), assessments=(assessment,)
        )
        outcome_ref = next(item for item in bundle.evidence_refs if item.ref_type is EvidenceRefType.TOOL_OUTCOME)
        assessment_ref = next(item for item in bundle.evidence_refs if item.ref_type is EvidenceRefType.ASSESSMENT)
        proposal = ReflectionProposal(
            proposal_id="e11_reflection_proposal", trigger_id=trigger.trigger_id,
            reusable_lesson_candidates=(ReusableLessonProposal(
                lesson_type=ReusableLessonType.OUTCOME,
                public_safe_summary=outcome_ref.public_summary,
                applicability_scope=ApplicabilityScope(
                    scope_type=ApplicabilityScopeType.SIMILAR_TOOL_OUTCOME_PATTERN,
                    public_pattern_tags=(outcome_ref.ref_id,),
                    limitation="Only when reversible public evidence gathering remains available.",
                ),
                evidence_refs=(outcome_ref, assessment_ref),
                confidence=ReflectionConfidence.HIGH,
                proposed_memory_type=MemoryType.LEARNING,
            ),),
            overall_confidence=ReflectionConfidence.HIGH,
        )
        adapter = adapter_override or _ScriptedAdapter(proposal.model_dump_json())
        service = ReflectionLifecycleService(
            generator=ReflectionProposalGenerator(adapter),
            consolidation_service=ReflectionMemoryConsolidationService(
                repository=repository, index_service=index_service
            ),
            receipt_repository=repository,
        )
        result = service.process(
            trigger=trigger, player_id=player_id,
            tool_outcomes=(outcome,), assessments=(assessment,),
        )
        replay_adapter = _ScriptedAdapter(proposal.model_dump_json())
        replay = ReflectionLifecycleService(
            generator=ReflectionProposalGenerator(replay_adapter),
            consolidation_service=ReflectionMemoryConsolidationService(
                repository=repository, index_service=index_service
            ),
            receipt_repository=repository,
        ).process(
            trigger=trigger, player_id=player_id,
            tool_outcomes=(outcome,), assessments=(assessment,),
        )
        indexed_ids = {
            item.memory_id for item in repository.list_embeddings(
                player_id=player_id, embedding_space_id=embedding_adapter.embedding_space_id
            )
        }
        state.update(
            trigger=trigger, result=result,
            generation_count=result.generation_attempt_count,
            reflection_usages=tuple(getattr(adapter, "usages", ())),
            receipt_persisted=(
                replay.status is ReflectionLifecycleStatus.IDEMPOTENT_REPLAY
                and not replay_adapter.requests
            ),
            indexed_ids=indexed_ids,
        )
    return hook


def run_condition(
    *, condition_path: Path, state_dir: Path, resources,
    embedding_adapter=None, session_b_agent=None, reflection_adapter=None,
) -> ReflectionOFATArtifact:
    started = time.perf_counter()
    condition = load_condition(condition_path)
    reflection_state = {}
    scenario = ExposureScenario(
        scenario_id="matched_reflection_transfer", condition="positive_transfer",
        session_a_case_id="old_paper_umbrella", session_a_investigation_id="observe_scholar",
        session_b_case_id="gray_hearth_inn",
        expected_relation="Transfer the public strategy of reversible evidence gathering before intervention.",
    )
    base = run_scenario(
        scenario=scenario, state_dir=state_dir, resources=resources,
        embedding_adapter=embedding_adapter or DeterministicFakeEmbedding(),
        agent=session_b_agent,
        session_a_driver=_complete_public_session_a,
        session_a_hook=(
            _reflection_hook(reflection_state, reflection_adapter)
            if condition.reflection_mode == "enabled" else None
        ),
    )
    ordinary = set(base.expected_memory_ids)
    derived = set(getattr(reflection_state.get("result"), "written_memory_ids", ()))
    result = reflection_state.get("result")
    reflection_usages = reflection_state.get("reflection_usages", ())
    reflection_costs = [
        float(item.estimated_cost) for item in reflection_usages
        if item.estimated_cost is not None
    ]
    indexed = len(derived.intersection(reflection_state.get("indexed_ids", set())))
    trigger_count = 1  # Session A is deterministically completed in both conditions.
    agent_inputs = tuple(getattr(session_b_agent, "inputs", ())) if session_b_agent is not None else ()
    context = agent_inputs[-1].memory_context if agent_inputs else None
    input_ids = tuple(item.memory_id for item in context.memories) if context is not None else base.selected_ids
    return ReflectionOFATArtifact(
        condition=condition.condition, memory_mode=condition.memory_mode,
        reflection_mode=condition.reflection_mode,
        manifest_hash=canonical_hash(condition_path), configuration_hash=canonical_hash(condition_path),
        session_a_episode_id=base.session_a_episode_id,
        session_b_episode_id=base.session_b_episode_id,
        ordinary_memory_ids=tuple(sorted(ordinary)),
        reflection_derived_memory_ids=tuple(sorted(derived)),
        reflection_trigger_count=trigger_count,
        reflection_generation_count=reflection_state.get("generation_count", 0),
        reflection_write_count=len(derived),
        reflection_receipt_persisted=reflection_state.get("receipt_persisted", False),
        reflection_indexed_count=indexed,
        memory_ordinary_write_count=len(ordinary),
        candidate_ids=base.candidate_ids, selected_ids=base.selected_ids,
        ordinary_candidate_ids=tuple(item for item in base.candidate_ids if item in ordinary),
        reflection_derived_candidate_ids=tuple(item for item in base.candidate_ids if item in derived),
        reflection_derived_selected_ids=tuple(item for item in base.selected_ids if item in derived),
        declared_ids=base.declared_ids, accepted_ids=base.accepted_ids,
        ordinary_declared_ids=tuple(item for item in base.declared_ids if item in ordinary),
        ordinary_accepted_ids=tuple(item for item in base.accepted_ids if item in ordinary),
        reflection_derived_declared_ids=tuple(item for item in base.declared_ids if item in derived),
        reflection_derived_accepted_ids=tuple(item for item in base.accepted_ids if item in derived),
        agent_input_memory_ids=input_ids,
        provider_requests=base.provider_requests + len(reflection_usages),
        input_tokens=base.input_tokens + sum(item.input_tokens for item in reflection_usages),
        output_tokens=base.output_tokens + sum(item.output_tokens for item in reflection_usages),
        estimated_cost_cny=base.estimated_cost_cny + sum(reflection_costs),
        duration_seconds=time.perf_counter() - started,
        authority_violations=int(base.authority_violation),
        infrastructure_failures=int(base.infrastructure_status != "ok"),
        repository_leakage=not base.same_repository_path,
        player_isolation_violation=base.player_isolation_violation,
        current_session_leakage=base.current_session_leakage,
    )
