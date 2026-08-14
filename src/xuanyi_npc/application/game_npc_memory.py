"""M3-1 bounded memory retrieval and projection for GameNPCAgent."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from pydantic import Field, StrictInt

from xuanyi_npc.application.memory_retrieval import BasicCosineMemoryRetriever
from xuanyi_npc.application.views import CaseObservation, MemoryScope, V1_READABLE_MEMORY_TYPES
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText
from xuanyi_npc.domain.cooperation import PlayerContribution
from xuanyi_npc.domain.cooperative_memory import (
    AgentMemoryContext,
    AgentMemoryItem,
    AgentMemorySourceType,
)
from xuanyi_npc.domain.cooperative_planning import AgentGoalState, AgentPlan, PlanEvaluation
from xuanyi_npc.memory.contracts import (
    AuthoritativeMemoryRecord,
    DiagnosisPublicPayload,
    InvestigationPublicPayload,
    MemoryStatus,
    PublicMemoryPayload,
    StructuredTeachingPublicPayload,
    TreatmentPublicPayload,
    VerifiedMemorySource,
)
from xuanyi_npc.memory.embeddings import InternalMemorySearchHit, MemoryRetrievalConfig


GAME_NPC_MEMORY_QUERY_TEMPLATE_VERSION = "game_npc_memory_query_v1"
GAME_NPC_MEMORY_PROJECTION_VERSION = "game_npc_memory_projection_v1"
_WHITESPACE = re.compile(r"\s+")


class GameNPCMemoryError(ValueError):
    """Raised when retrieved memory crosses the cooperative trust boundary."""


class GameNPCMemoryRepository(Protocol):
    def list_memories(
        self,
        *,
        player_id: str,
        include_inactive: bool = True,
    ) -> tuple[AuthoritativeMemoryRecord, ...]: ...

    def get_source_receipt(
        self,
        *,
        player_id: str,
        source_event_id: str,
        projection_version: str,
        projection_ordinal: int,
    ) -> VerifiedMemorySource: ...

    def tombstone_exists(self, memory_id: str) -> bool: ...


class GameNPCMemoryQuery(DomainModel):
    query_id: Identifier
    template_version: Identifier = GAME_NPC_MEMORY_QUERY_TEMPLATE_VERSION
    text: NonEmptyText


class GameNPCMemoryRetrievalConfig(DomainModel):
    max_selected: StrictInt = Field(default=4, ge=1, le=5)
    char_budget: StrictInt = Field(default=900, ge=120, le=4000)
    min_relevance: float = Field(default=0.05, strict=True, ge=-1.0, le=1.0)
    allow_conflicting_memory: bool = False


class GameNPCMemoryQueryBuilder:
    """Build a public-only retrieval query from current cooperative state."""

    def build(
        self,
        *,
        turn_id: str,
        observation: CaseObservation,
        current_goal: AgentGoalState | None,
        current_plan: AgentPlan | None,
        player_contribution: PlayerContribution | None,
        last_plan_evaluation: PlanEvaluation | None,
    ) -> GameNPCMemoryQuery:
        payload = {
            "template_version": GAME_NPC_MEMORY_QUERY_TEMPLATE_VERSION,
            "case": {
                "case_id": observation.case_id,
                "title": observation.title,
                "synopsis": observation.synopsis,
                "patient_profile": observation.patient_public_profile,
                "session_status": observation.session_status.value,
                "session_revision": observation.session_revision,
            },
            "discovered_clues": [
                {"clue_id": item.clue_id, "description": item.description}
                for item in observation.discovered_clues
            ],
            "available_investigations": [
                {
                    "investigation_id": item.investigation_id,
                    "action_type": item.action_type.value,
                    "target_id": item.target_id,
                    "public_description": item.public_description,
                }
                for item in observation.available_investigations
            ],
            "diagnosis_candidates": [
                {
                    "diagnosis_id": item.diagnosis_id,
                    "public_description": item.public_description,
                }
                for item in observation.diagnosis_candidates
            ],
            "available_treatments": [
                {
                    "treatment_id": item.treatment_id,
                    "public_description": item.public_description,
                }
                for item in observation.available_treatments
            ],
            "current_goal": (
                {
                    "goal_type": current_goal.goal_type.value,
                    "public_description": current_goal.public_description,
                    "status": current_goal.status.value,
                    "priority": current_goal.priority,
                }
                if current_goal is not None
                else None
            ),
            "current_plan": (
                {
                    "status": current_plan.status.value,
                    "current_step_index": current_plan.current_step_index,
                    "steps": [
                        {
                            "intent": item.intent.value,
                            "capability": item.capability.value,
                            "suggested_tool": (
                                item.suggested_tool.value
                                if item.suggested_tool is not None
                                else None
                            ),
                            "public_target_id": item.public_target_id,
                            "public_summary": item.public_summary,
                            "status": item.status.value,
                        }
                        for item in current_plan.steps
                    ],
                }
                if current_plan is not None
                else None
            ),
            "player_belief": (
                {
                    "contribution_type": player_contribution.contribution_type.value,
                    "text": player_contribution.public_text,
                }
                if player_contribution is not None
                else None
            ),
            "last_plan_evaluation": (
                {
                    "outcome": last_plan_evaluation.outcome.value,
                    "reason_code": last_plan_evaluation.reason_code.value,
                    "public_summary": last_plan_evaluation.public_summary,
                }
                if last_plan_evaluation is not None
                else None
            ),
        }
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return GameNPCMemoryQuery(query_id=f"memory_query_{turn_id}", text=text)


@dataclass(frozen=True)
class _Candidate:
    hit: InternalMemorySearchHit
    memory: AuthoritativeMemoryRecord
    source: VerifiedMemorySource


class GameNPCMemoryProjectionPolicy:
    """Project semantic candidates into bounded, public, non-authoritative memory."""

    def __init__(
        self,
        *,
        repository: GameNPCMemoryRepository,
        clock=None,
    ) -> None:
        self.repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def project(
        self,
        *,
        retrieval_id: str,
        query: GameNPCMemoryQuery,
        player_id: str,
        current_session_id: str,
        observation: CaseObservation,
        hits: tuple[InternalMemorySearchHit, ...],
        config: GameNPCMemoryRetrievalConfig,
        embedding_space_id: str,
        index_state,
    ) -> AgentMemoryContext:
        active = {
            item.memory_id: item
            for item in self.repository.list_memories(
                player_id=player_id,
                include_inactive=False,
            )
        }
        candidates: list[_Candidate] = []
        for hit in hits:
            if hit.player_id != player_id:
                raise GameNPCMemoryError("retrieved memory belongs to another player")
            if hit.source_session_id == current_session_id:
                continue
            if hit.memory_type not in V1_READABLE_MEMORY_TYPES:
                continue
            if hit.similarity < config.min_relevance:
                continue
            memory = active.get(hit.memory_id)
            if memory is None:
                continue
            if memory.status is not MemoryStatus.ACTIVE:
                continue
            if self.repository.tombstone_exists(hit.memory_id):
                continue
            source = self.repository.get_source_receipt(
                player_id=player_id,
                source_event_id=memory.source_event_id,
                projection_version=memory.projection_version,
                projection_ordinal=memory.projection_ordinal,
            )
            if source.player_id != player_id:
                raise GameNPCMemoryError("memory source belongs to another player")
            if source.source_session_id == current_session_id:
                continue
            candidates.append(_Candidate(hit=hit, memory=memory, source=source))

        selected: list[AgentMemoryItem] = []
        seen_summaries: set[str] = set()
        selected_chars = 0
        for candidate in candidates:
            item = self._project_candidate(candidate, observation=observation)
            summary_key = _normalize_public_text(item.public_summary)
            if summary_key in seen_summaries:
                continue
            if item.conflict_with_current_observation and not config.allow_conflicting_memory:
                continue
            next_chars = selected_chars + len(item.public_summary)
            if next_chars > config.char_budget:
                continue
            selected.append(item)
            seen_summaries.add(summary_key)
            selected_chars = next_chars
            if len(selected) >= config.max_selected:
                break

        selected_ids = tuple(item.memory_id for item in selected)
        return AgentMemoryContext(
            retrieval_id=retrieval_id,
            query_basis=query.text,
            normalized_query=query.text,
            memories=tuple(selected),
            retrieval_summary=(
                f"selected {len(selected)} of {len(candidates)} semantic memory candidates"
            ),
            candidate_memory_ids=tuple(candidate.hit.memory_id for candidate in candidates),
            selected_memory_ids=selected_ids,
            total_candidates=len(candidates),
            selected_count=len(selected),
            max_selected=config.max_selected,
            char_budget=config.char_budget,
            selected_chars=selected_chars,
            embedding_space_id=embedding_space_id,
            query_template_version=query.template_version,
            index_status=index_state.status.value,
            active_memory_count=index_state.active_memory_count,
            valid_embedding_count=index_state.valid_embedding_count,
        )

    def _project_candidate(
        self,
        candidate: _Candidate,
        *,
        observation: CaseObservation,
    ) -> AgentMemoryItem:
        payload = candidate.source.public_payload
        summary = _payload_summary(payload, fallback=candidate.memory.content)
        source_case_id = _payload_case_id(payload) or candidate.memory.related_case_id
        conflict = _conflicts_with_observation(payload, observation)
        confidence = min(1.0, 0.55 + candidate.memory.importance * 0.08)
        if conflict:
            confidence = min(confidence, 0.35)
            summary = "历史经验，与当前公开观察不一致，不能作为当前事实：" + summary
        return AgentMemoryItem(
            memory_id=candidate.memory.memory_id,
            memory_type=candidate.memory.memory_type,
            public_summary=summary,
            source_type=AgentMemorySourceType(candidate.source.source_event_type.value),
            source_episode_id=candidate.memory.source_session_id,
            source_case_id=source_case_id,
            relevance_score=candidate.hit.similarity,
            confidence=confidence,
            reason_code=_reason_code(payload),
            occurred_at=candidate.memory.occurred_at,
            last_verified_at=self._clock(),
            conflict_with_current_observation=conflict,
        )


class GameNPCMemoryRetrievalService:
    def __init__(
        self,
        *,
        retriever: BasicCosineMemoryRetriever,
        retrieval_config: MemoryRetrievalConfig,
        projection_policy: GameNPCMemoryProjectionPolicy,
        query_builder: GameNPCMemoryQueryBuilder | None = None,
        projection_config: GameNPCMemoryRetrievalConfig | None = None,
    ) -> None:
        self.retriever = retriever
        self.retrieval_config = retrieval_config
        self.projection_policy = projection_policy
        self.query_builder = query_builder or GameNPCMemoryQueryBuilder()
        self.projection_config = projection_config or GameNPCMemoryRetrievalConfig()

    def retrieve(
        self,
        *,
        turn_id: str,
        player_id: str,
        current_session_id: str,
        observation: CaseObservation,
        current_goal: AgentGoalState | None = None,
        current_plan: AgentPlan | None = None,
        player_contribution: PlayerContribution | None = None,
        last_plan_evaluation: PlanEvaluation | None = None,
    ) -> AgentMemoryContext:
        query = self.query_builder.build(
            turn_id=turn_id,
            observation=observation,
            current_goal=current_goal,
            current_plan=current_plan,
            player_contribution=player_contribution,
            last_plan_evaluation=last_plan_evaluation,
        )
        result = self.retriever.retrieve_scoped(
            scope=MemoryScope(
                player_id=player_id,
                allowed_memory_types=V1_READABLE_MEMORY_TYPES,
                excluded_source_session_id=current_session_id,
            ),
            query_text=query.text,
            config=self.retrieval_config,
        )
        return self.projection_policy.project(
            retrieval_id=f"memory_retrieval_{turn_id}",
            query=query,
            player_id=player_id,
            current_session_id=current_session_id,
            observation=observation,
            hits=result.hits,
            config=self.projection_config,
            embedding_space_id=result.embedding_space_id,
            index_state=result.index_state,
        )


def _normalize_public_text(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip().casefold()


def _payload_summary(payload: PublicMemoryPayload, *, fallback: str) -> str:
    if isinstance(payload, InvestigationPublicPayload):
        clues = "；".join(item.description for item in payload.newly_discovered_clues)
        suffix = f"发现：{clues}" if clues else "未记录新的公开线索"
        return f"过去病例《{payload.case_title}》中执行过调查：{payload.public_action_description}，{suffix}。"
    if isinstance(payload, DiagnosisPublicPayload):
        evidence = "；".join(item.description for item in payload.cited_evidence)
        suffix = f"引用证据：{evidence}" if evidence else "未记录引用证据"
        return f"过去病例《{payload.case_title}》中提交过诊断假设：{payload.public_hypothesis_description}，{suffix}。"
    if isinstance(payload, TreatmentPublicPayload):
        return f"过去病例《{payload.case_title}》中执行过处置：{payload.public_action_description}，公开结果：{payload.public_result}。"
    if isinstance(payload, StructuredTeachingPublicPayload):
        return payload.public_summary
    return fallback


def _payload_case_id(payload: PublicMemoryPayload) -> str | None:
    if isinstance(
        payload,
        (InvestigationPublicPayload, DiagnosisPublicPayload, TreatmentPublicPayload),
    ):
        return payload.case_id
    if isinstance(payload, StructuredTeachingPublicPayload):
        return payload.source_case_id
    return None


def _reason_code(payload: PublicMemoryPayload) -> str:
    if isinstance(payload, StructuredTeachingPublicPayload):
        return payload.reason_code
    return payload.payload_type


def _conflicts_with_observation(
    payload: PublicMemoryPayload,
    observation: CaseObservation,
) -> bool:
    if isinstance(payload, InvestigationPublicPayload):
        current_clue_ids = {item.clue_id for item in observation.discovered_clues}
        payload_clue_ids = {item.clue_id for item in payload.newly_discovered_clues}
        return bool(payload.case_id == observation.case_id and payload_clue_ids - current_clue_ids)
    if isinstance(payload, DiagnosisPublicPayload):
        current_clue_ids = {item.clue_id for item in observation.discovered_clues}
        cited_ids = {item.clue_id for item in payload.cited_evidence}
        return bool(payload.case_id == observation.case_id and cited_ids - current_clue_ids)
    return False
