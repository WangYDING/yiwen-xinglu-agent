"""Explicit V1-only indexing and cosine retrieval for M4-P2."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable, Protocol

from xuanyi_npc.memory.contracts import AuthoritativeMemoryRecord
from xuanyi_npc.memory.embeddings import (
    DerivedEmbeddingRecord,
    EmbeddingAdapter,
    EmbeddingRequest,
    EmbeddingRequestItem,
    EmbeddingWriteResult,
    InternalMemorySearchHit,
    InternalMemorySearchResult,
    MemoryIndexBuildResult,
    MemoryIndexState,
    MemoryIndexStatus,
    MemoryRetrievalConfig,
    normalize_embedding_text,
    validate_embedding_batch,
    vector_l2_norm,
)
from xuanyi_npc.memory.errors import (
    EmbeddingContractError,
    EmbeddingSpaceMismatchError,
    MemoryIndexIncompleteError,
)


class MemoryVectorRepository(Protocol):
    def list_memories(
        self,
        *,
        player_id: str,
        include_inactive: bool = True,
    ) -> tuple[AuthoritativeMemoryRecord, ...]: ...

    def list_embeddings(
        self,
        *,
        player_id: str,
        embedding_space_id: str,
    ) -> tuple[DerivedEmbeddingRecord, ...]: ...

    def write_embeddings(
        self,
        *,
        player_id: str,
        records: tuple[DerivedEmbeddingRecord, ...],
    ) -> tuple[EmbeddingWriteResult, ...]: ...

    def replace_embeddings_for_space(
        self,
        *,
        player_id: str,
        embedding_space_id: str,
        records: tuple[DerivedEmbeddingRecord, ...],
    ) -> tuple[EmbeddingWriteResult, ...]: ...


class MemoryIndexService:
    """Build derived vectors only for one explicitly supplied player."""

    def __init__(
        self,
        *,
        repository: MemoryVectorRepository,
        adapter: EmbeddingAdapter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.adapter = adapter
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def inspect_index(self, *, player_id: str) -> MemoryIndexState:
        active = self._active_memories(player_id)
        embeddings = self.repository.list_embeddings(
            player_id=player_id,
            embedding_space_id=self.adapter.embedding_space_id,
        )
        by_memory_id = {record.memory_id: record for record in embeddings}
        missing: list[str] = []
        stale: list[str] = []
        valid_count = 0
        for memory in active:
            embedding = by_memory_id.get(memory.memory_id)
            if embedding is None:
                missing.append(memory.memory_id)
                continue
            if embedding.dimension != self.adapter.dimension:
                raise EmbeddingContractError(
                    "stored embedding dimension does not match adapter space"
                )
            if embedding.content_hash != memory.content_hash:
                stale.append(memory.memory_id)
                continue
            valid_count += 1
        status = (
            MemoryIndexStatus.NO_ACTIVE_MEMORY
            if not active
            else (
                MemoryIndexStatus.COMPLETE
                if not missing and not stale and valid_count == len(active)
                else MemoryIndexStatus.INCOMPLETE
            )
        )
        return MemoryIndexState(
            player_id=player_id,
            embedding_space_id=self.adapter.embedding_space_id,
            active_memory_count=len(active),
            valid_embedding_count=valid_count,
            missing_memory_ids=tuple(sorted(missing)),
            stale_memory_ids=tuple(sorted(stale)),
            status=status,
        )

    def index_player(self, *, player_id: str) -> MemoryIndexBuildResult:
        active = self._active_memories(player_id)
        records = self._embed_memories(player_id=player_id, memories=active)
        writes = self.repository.write_embeddings(
            player_id=player_id,
            records=records,
        )
        state = self.inspect_index(player_id=player_id)
        return MemoryIndexBuildResult(
            player_id=player_id,
            embedding_space_id=self.adapter.embedding_space_id,
            active_memory_count=len(active),
            write_results=writes,
            state=state,
        )

    def rebuild_player(self, *, player_id: str) -> MemoryIndexBuildResult:
        active = self._active_memories(player_id)
        records = self._embed_memories(player_id=player_id, memories=active)
        writes = self.repository.replace_embeddings_for_space(
            player_id=player_id,
            embedding_space_id=self.adapter.embedding_space_id,
            records=records,
        )
        state = self.inspect_index(player_id=player_id)
        return MemoryIndexBuildResult(
            player_id=player_id,
            embedding_space_id=self.adapter.embedding_space_id,
            active_memory_count=len(active),
            write_results=writes,
            state=state,
        )

    def _active_memories(
        self,
        player_id: str,
    ) -> tuple[AuthoritativeMemoryRecord, ...]:
        return tuple(
            sorted(
                self.repository.list_memories(
                    player_id=player_id,
                    include_inactive=False,
                ),
                key=lambda item: item.memory_id,
            )
        )

    def _embed_memories(
        self,
        *,
        player_id: str,
        memories: tuple[AuthoritativeMemoryRecord, ...],
    ) -> tuple[DerivedEmbeddingRecord, ...]:
        if not memories:
            return ()
        request = EmbeddingRequest(
            embedding_space_id=self.adapter.embedding_space_id,
            dimension=self.adapter.dimension,
            items=tuple(
                EmbeddingRequestItem(item_id=memory.memory_id, text=memory.content)
                for memory in memories
            ),
        )
        result = self.adapter.embed(request)
        validate_embedding_batch(request, result)
        generated_at = self._clock()
        return tuple(
            DerivedEmbeddingRecord(
                memory_id=memory.memory_id,
                player_id=player_id,
                embedding_space_id=result.embedding_space_id,
                content_hash=memory.content_hash,
                dimension=result.dimension,
                vector=embedded.vector,
                l2_norm=vector_l2_norm(embedded.vector),
                generated_at=generated_at,
            )
            for memory, embedded in zip(memories, result.items, strict=True)
        )


class BasicCosineMemoryRetriever:
    """Return internal hits only; M4-P2 does not construct Agent MemoryView."""

    def __init__(
        self,
        *,
        repository: MemoryVectorRepository,
        adapter: EmbeddingAdapter,
    ) -> None:
        self.repository = repository
        self.adapter = adapter
        self.index_service = MemoryIndexService(
            repository=repository,
            adapter=adapter,
        )

    def retrieve(
        self,
        *,
        player_id: str,
        query_text: str,
        config: MemoryRetrievalConfig,
    ) -> InternalMemorySearchResult:
        if config.embedding_space_id != self.adapter.embedding_space_id:
            raise EmbeddingSpaceMismatchError(
                "retrieval config and embedding adapter spaces do not match"
            )
        state = self.index_service.inspect_index(player_id=player_id)
        normalized_query = normalize_embedding_text(query_text)
        if state.status is MemoryIndexStatus.INCOMPLETE:
            raise MemoryIndexIncompleteError(
                "active memory vector index is missing or stale",
                index_state=state,
            )
        if state.status is MemoryIndexStatus.NO_ACTIVE_MEMORY:
            return InternalMemorySearchResult(
                player_id=player_id,
                embedding_space_id=config.embedding_space_id,
                query_template_version=config.query_template_version,
                normalized_query=normalized_query,
                index_state=state,
            )

        memories = self.repository.list_memories(
            player_id=player_id,
            include_inactive=False,
        )
        embeddings = self.repository.list_embeddings(
            player_id=player_id,
            embedding_space_id=config.embedding_space_id,
        )
        embedding_by_id = {item.memory_id: item for item in embeddings}
        request = EmbeddingRequest(
            embedding_space_id=self.adapter.embedding_space_id,
            dimension=self.adapter.dimension,
            items=(EmbeddingRequestItem(item_id="memory_query", text=normalized_query),),
        )
        result = self.adapter.embed(request)
        validate_embedding_batch(request, result)
        query_vector = result.items[0].vector
        query_norm = vector_l2_norm(query_vector)

        scored: list[InternalMemorySearchHit] = []
        for memory in memories:
            embedding = embedding_by_id[memory.memory_id]
            similarity = math.fsum(
                left * right
                for left, right in zip(
                    query_vector,
                    embedding.vector,
                    strict=True,
                )
            ) / (query_norm * embedding.l2_norm)
            similarity = max(-1.0, min(1.0, similarity))
            if similarity < config.min_similarity:
                continue
            scored.append(
                InternalMemorySearchHit(
                    memory_id=memory.memory_id,
                    player_id=player_id,
                    memory_type=memory.memory_type,
                    content=memory.content,
                    content_hash=memory.content_hash,
                    occurred_at=memory.occurred_at,
                    similarity=similarity,
                )
            )
        scored.sort(key=lambda item: (-item.similarity, item.memory_id))
        return InternalMemorySearchResult(
            player_id=player_id,
            embedding_space_id=config.embedding_space_id,
            query_template_version=config.query_template_version,
            normalized_query=normalized_query,
            index_state=state,
            hits=tuple(scored[: config.top_k]),
        )
