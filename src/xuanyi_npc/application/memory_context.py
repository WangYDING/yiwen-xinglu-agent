"""Safe V1-only assembly of cross-Episode memory context."""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, StrictStr, StringConstraints, model_validator

from xuanyi_npc.agents.doctor import AgentDecision, FixedV0Curriculum
from xuanyi_npc.agents.llm import ChatMessage, ChatRole
from xuanyi_npc.agents.v1_doctor import (
    V1DoctorAgentInput,
    V1DoctorAgentInterface,
)
from xuanyi_npc.application.v0_tools import V0ToolExecutor
from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.domain.cases import CaseDefinition, CaseSessionState
from xuanyi_npc.domain.player import PlayerState
from xuanyi_npc.memory.embeddings import (
    ConservativeRetrievalConfigV2,
    MEMORY_QUERY_TEMPLATE_VERSION,
    MemoryRetrievalConfig,
)
from xuanyi_npc.application.retrieval_query import RetrievalQueryV2Builder
from xuanyi_npc.memory.errors import MemoryError

from .memory_retrieval import BasicCosineMemoryRetriever
from .diagnosis_readiness import FixedV0DiagnosisReadinessPolicy
from .views import (
    AgentContextFilter,
    CaseObservation,
    MemoryContextStatus,
    MemoryView,
    ViewContextError,
)


MAX_MEMORY_QUERY_LENGTH = 4096
MEMORY_CONTEXT_UNAVAILABLE = "memory_context_unavailable"
_WHITESPACE = re.compile(r"\s+", flags=re.UNICODE)
MemoryQueryText = Annotated[
    StrictStr,
    StringConstraints(strict=True, min_length=1, max_length=MAX_MEMORY_QUERY_LENGTH),
]


class MemoryQueryError(ValueError):
    code = MEMORY_CONTEXT_UNAVAILABLE


class MemoryQuery(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    version: Literal["memory_query_v1"] = "memory_query_v1"
    text: MemoryQueryText


class MemoryQueryBuilder:
    """Build stable embedding input from public current-Episode data only."""

    version = MEMORY_QUERY_TEMPLATE_VERSION

    def build(
        self,
        *,
        current_user_message: str,
        case_observation: CaseObservation,
        fixed_lesson: str,
    ) -> MemoryQuery:
        if not isinstance(case_observation, CaseObservation):
            raise MemoryQueryError("case observation must be a filtered public view")
        payload = {
            "version": self.version,
            "current_user_message": self._normalize_field(current_user_message),
            "case_title": self._normalize_field(case_observation.title),
            "case_synopsis": self._normalize_field(case_observation.synopsis),
            "discovered_clue_descriptions": [
                self._normalize_field(clue.description)
                for clue in case_observation.discovered_clues
            ],
            "fixed_lesson": self._normalize_field(fixed_lesson),
        }
        text = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(text) > MAX_MEMORY_QUERY_LENGTH:
            raise MemoryQueryError("public memory query exceeds the maximum length")
        return MemoryQuery(text=text)

    @staticmethod
    def _normalize_field(value: object) -> str:
        if not isinstance(value, str):
            raise MemoryQueryError("public memory query fields must be strings")
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return _WHITESPACE.sub(" ", normalized).strip()


class V1MemoryContext(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: MemoryContextStatus
    retrieved_memories: tuple[MemoryView, ...] = Field(default_factory=tuple)
    error_code: str | None = None

    @model_validator(mode="after")
    def require_consistent_status(self) -> "V1MemoryContext":
        if self.status is MemoryContextStatus.READY:
            if not self.retrieved_memories or self.error_code is not None:
                raise ValueError("ready memory context requires memories and no error")
        elif self.status is MemoryContextStatus.EMPTY:
            if self.retrieved_memories or self.error_code is not None:
                raise ValueError("empty memory context cannot contain data or an error")
        elif self.retrieved_memories or self.error_code != MEMORY_CONTEXT_UNAVAILABLE:
            raise ValueError("unavailable memory context requires only its safe error code")
        return self


class V1AgentContextResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_context: V1MemoryContext
    decision: AgentDecision | None = None

    @model_validator(mode="after")
    def require_decision_only_for_callable_context(self) -> "V1AgentContextResult":
        if self.memory_context.status is MemoryContextStatus.UNAVAILABLE:
            if self.decision is not None:
                raise ValueError("unavailable memory context cannot have a decision")
        elif self.decision is None:
            raise ValueError("ready or empty memory context requires a decision")
        return self


class V1AgentContextService:
    """Stop before LLM use unless complete, revalidated memory context is available."""

    def __init__(
        self,
        *,
        doctor_agent: V1DoctorAgentInterface,
        retriever: BasicCosineMemoryRetriever,
        retrieval_config: MemoryRetrievalConfig | ConservativeRetrievalConfigV2,
        context_filter: AgentContextFilter | None = None,
        tool_executor: V0ToolExecutor | None = None,
        query_builder: MemoryQueryBuilder | RetrievalQueryV2Builder | None = None,
        curriculum: FixedV0Curriculum | None = None,
    ) -> None:
        self.doctor_agent = doctor_agent
        self.retriever = retriever
        self.retrieval_config = retrieval_config
        self.context_filter = context_filter or AgentContextFilter()
        self.tool_executor = tool_executor or V0ToolExecutor(
            context_filter=self.context_filter,
            diagnosis_readiness_policy=FixedV0DiagnosisReadinessPolicy(),
        )
        if self.tool_executor.context_filter is not self.context_filter:
            raise ValueError("V1 service and tool executor must share one context filter")
        self.query_builder = query_builder or MemoryQueryBuilder()
        self.curriculum = curriculum or FixedV0Curriculum()

    def decide(
        self,
        *,
        step_index: int,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
        current_user_message: str,
        recent_messages: tuple[ChatMessage, ...] = (),
    ) -> V1AgentContextResult:
        try:
            player_view = self.context_filter.player_view(player)
            observation = self.tool_executor.case_observation(case, player, session)
            scope = self.context_filter.memory_scope(player, session)
            lesson = self.curriculum.lesson_for_step(step_index)
            agent_messages = (
                *recent_messages,
                ChatMessage(role=ChatRole.USER, content=current_user_message),
            )
            query = self.query_builder.build(
                current_user_message=current_user_message,
                case_observation=observation,
                fixed_lesson=lesson,
            )
            if isinstance(self.retrieval_config, ConservativeRetrievalConfigV2):
                result = self.retriever.retrieve_conservative_scoped(
                    scope=scope,
                    query_text=query.text,
                    config=self.retrieval_config,
                )
            else:
                result = self.retriever.retrieve_scoped(
                    scope=scope,
                    query_text=query.text,
                    config=self.retrieval_config,
                )
            memories = self.context_filter.memory_views(scope, result)
        except (MemoryError, MemoryQueryError, ViewContextError, ValueError):
            return V1AgentContextResult(
                memory_context=V1MemoryContext(
                    status=MemoryContextStatus.UNAVAILABLE,
                    error_code=MEMORY_CONTEXT_UNAVAILABLE,
                )
            )

        status = (
            MemoryContextStatus.READY if memories else MemoryContextStatus.EMPTY
        )
        memory_context = V1MemoryContext(
            status=status,
            retrieved_memories=memories,
        )
        decision = self.doctor_agent.decide(
            V1DoctorAgentInput(
                step_index=step_index,
                player_view=player_view,
                case_observation=observation,
                recent_messages=agent_messages,
                fixed_lesson=lesson,
                retrieved_memories=memories,
                memory_context_status=status,
            )
        )
        return V1AgentContextResult(
            memory_context=memory_context,
            decision=decision,
        )
