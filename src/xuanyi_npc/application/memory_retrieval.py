"""Explicit V1-only indexing and cosine retrieval for M4-P2."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Callable, Protocol

from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.memory.contracts import AuthoritativeMemoryRecord, VerifiedMemorySource
from xuanyi_npc.memory.embeddings import (
    ConservativeRetrievalConfigV2,
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
    RepresentationIndexState,
    RepresentationIndexStatus,
    normalize_embedding_text,
    validate_embedding_batch,
    vector_l2_norm,
)
from xuanyi_npc.memory.errors import (
    EmbeddingContractError,
    EmbeddingSpaceMismatchError,
    MemoryIndexIncompleteError,
)
from xuanyi_npc.memory.representations import (
    EmbeddingDocumentV1Builder,
    EmbeddingDocumentV2Builder,
)

from .views import MemoryScope


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

    def list_player_embeddings(
        self,
        *,
        player_id: str,
    ) -> tuple[DerivedEmbeddingRecord, ...]: ...

    def get_source_receipt(
        self,
        *,
        player_id: str,
        source_event_id: str,
        projection_version: str,
        projection_ordinal: int,
    ) -> VerifiedMemorySource: ...

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
        document_builder: EmbeddingDocumentV1Builder | EmbeddingDocumentV2Builder | None = None,
    ) -> None:
        self.repository = repository
        self.adapter = adapter
        self.document_builder = document_builder or EmbeddingDocumentV1Builder()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def inspect_index(self, *, player_id: str) -> MemoryIndexState:
        active = self._active_memories(player_id)
        return self.inspect_candidates(player_id=player_id, memories=active)

    def inspect_candidates(
        self,
        *,
        player_id: str,
        memories: tuple[AuthoritativeMemoryRecord, ...],
    ) -> MemoryIndexState:
        """Inspect only an already permission-filtered candidate set."""

        if any(memory.player_id != player_id for memory in memories):
            raise ValueError("memory candidate player does not match retrieval player")
        embeddings = self.repository.list_embeddings(
            player_id=player_id,
            embedding_space_id=self.adapter.embedding_space_id,
        )
        by_memory_id = {record.memory_id: record for record in embeddings}
        missing: list[str] = []
        stale: list[str] = []
        valid_count = 0
        for memory in memories:
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
            if not memories
            else (
                MemoryIndexStatus.COMPLETE
                if not missing and not stale and valid_count == len(memories)
                else MemoryIndexStatus.INCOMPLETE
            )
        )
        return MemoryIndexState(
            player_id=player_id,
            embedding_space_id=self.adapter.embedding_space_id,
            active_memory_count=len(memories),
            valid_embedding_count=valid_count,
            missing_memory_ids=tuple(sorted(missing)),
            stale_memory_ids=tuple(sorted(stale)),
            status=status,
        )

    def inspect_representation_candidates(
        self,
        *,
        player_id: str,
        memories: tuple[AuthoritativeMemoryRecord, ...],
    ) -> RepresentationIndexState:
        """Distinguish a missing V2 build from vectors in an older representation."""

        legacy = self.inspect_candidates(player_id=player_id, memories=memories)
        if not memories:
            return RepresentationIndexState(
                player_id=player_id,
                embedding_space_id=self.adapter.embedding_space_id,
                active_memory_count=0,
                valid_embedding_count=0,
                status=RepresentationIndexStatus.EMPTY,
            )
        old_ids: set[str] = set()
        if legacy.missing_memory_ids:
            all_embeddings = self.repository.list_player_embeddings(player_id=player_id)
            current_space = self.adapter.embedding_space_id
            old_ids = {
                item.memory_id
                for item in all_embeddings
                if item.embedding_space_id != current_space
            }
        stale_representation = tuple(
            sorted(set(legacy.missing_memory_ids) & old_ids)
        )
        missing = tuple(
            sorted(set(legacy.missing_memory_ids) - set(stale_representation))
        )
        status = (
            RepresentationIndexStatus.STALE_REPRESENTATION
            if stale_representation
            else (
                RepresentationIndexStatus.INCOMPLETE
                if missing or legacy.stale_memory_ids
                else RepresentationIndexStatus.READY
            )
        )
        return RepresentationIndexState(
            player_id=player_id,
            embedding_space_id=self.adapter.embedding_space_id,
            active_memory_count=legacy.active_memory_count,
            valid_embedding_count=legacy.valid_embedding_count,
            missing_memory_ids=missing,
            stale_content_memory_ids=legacy.stale_memory_ids,
            stale_representation_memory_ids=stale_representation,
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
        documents = tuple(
            self.document_builder.build(
                memory=memory,
                source=(
                    self.repository.get_source_receipt(
                        player_id=player_id,
                        source_event_id=memory.source_event_id,
                        projection_version=memory.projection_version,
                        projection_ordinal=memory.projection_ordinal,
                    )
                    if self.document_builder.requires_source
                    else None
                ),
            )
            for memory in memories
        )
        request = EmbeddingRequest(
            embedding_space_id=self.adapter.embedding_space_id,
            dimension=self.adapter.dimension,
            items=tuple(
                EmbeddingRequestItem(item_id=memory.memory_id, text=document.text)
                for memory, document in zip(memories, documents, strict=True)
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
        document_builder: EmbeddingDocumentV1Builder | EmbeddingDocumentV2Builder | None = None,
    ) -> None:
        self.repository = repository
        self.adapter = adapter
        self.index_service = MemoryIndexService(
            repository=repository,
            adapter=adapter,
            document_builder=document_builder,
        )

    def retrieve(
        self,
        *,
        player_id: str,
        query_text: str,
        config: MemoryRetrievalConfig,
    ) -> InternalMemorySearchResult:
        return self._retrieve(
            player_id=player_id,
            query_text=query_text,
            config=config,
        )

    def retrieve_scoped(
        self,
        *,
        scope: MemoryScope,
        query_text: str,
        config: MemoryRetrievalConfig,
    ) -> InternalMemorySearchResult:
        """Retrieve cross-Episode V1 candidates after mandatory pre-filtering."""

        return self._retrieve(
            player_id=scope.player_id,
            query_text=query_text,
            config=config,
            allowed_memory_types=scope.allowed_memory_types,
            excluded_source_session_id=scope.excluded_source_session_id,
        )

    def retrieve_conservative_scoped(
        self,
        *,
        scope: MemoryScope,
        query_text: str,
        config: ConservativeRetrievalConfigV2,
    ) -> InternalMemorySearchResult:
        """Use V2 representation completeness plus an absolute and relative gate."""

        return self._retrieve(
            player_id=scope.player_id,
            query_text=query_text,
            config=config,
            allowed_memory_types=scope.allowed_memory_types,
            excluded_source_session_id=scope.excluded_source_session_id,
        )

    def _retrieve(
        self,
        *,
        player_id: str,
        query_text: str,
        config: MemoryRetrievalConfig | ConservativeRetrievalConfigV2,
        allowed_memory_types: tuple[MemoryType, ...] | None = None,
        excluded_source_session_id: str | None = None,
    ) -> InternalMemorySearchResult:
        if config.embedding_space_id != self.adapter.embedding_space_id:
            raise EmbeddingSpaceMismatchError(
                "retrieval config and embedding adapter spaces do not match"
            )
        memories = tuple(
            memory
            for memory in self.repository.list_memories(
                player_id=player_id,
                include_inactive=False,
            )
            if (
                allowed_memory_types is None
                or memory.memory_type in allowed_memory_types
            )
            and memory.source_session_id != excluded_source_session_id
        )
        if isinstance(config, ConservativeRetrievalConfigV2):
            representation_state = self.index_service.inspect_representation_candidates(
                player_id=player_id,
                memories=memories,
            )
            if representation_state.status in {
                RepresentationIndexStatus.INCOMPLETE,
                RepresentationIndexStatus.STALE_REPRESENTATION,
            }:
                raise MemoryIndexIncompleteError(
                    "active memory representation index is incomplete or stale",
                    index_state=representation_state,
                )
            state = self.index_service.inspect_candidates(
                player_id=player_id,
                memories=memories,
            )
        else:
            state = self.index_service.inspect_candidates(
                player_id=player_id,
                memories=memories,
            )
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
                    source_session_id=memory.source_session_id,
                    occurred_at=memory.occurred_at,
                    similarity=similarity,
                )
            )
        scored.sort(key=lambda item: (-item.similarity, item.memory_id))
        if isinstance(config, ConservativeRetrievalConfigV2):
            maximum = config.max_results
            if len(scored) >= 2 and (
                scored[0].similarity - scored[1].similarity
                < config.minimum_margin
            ):
                scored = []
        else:
            maximum = config.top_k
        return InternalMemorySearchResult(
            player_id=player_id,
            embedding_space_id=config.embedding_space_id,
            query_template_version=config.query_template_version,
            normalized_query=normalized_query,
            index_state=state,
            hits=tuple(scored[:maximum]),
        )
