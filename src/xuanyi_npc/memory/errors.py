"""Explicit, safe failure categories for M4 memory persistence."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .embeddings import MemoryIndexState


class MemoryError(RuntimeError):
    """Base memory boundary error with a stable safe code."""

    code = "memory_error"


class MemoryProjectionError(MemoryError):
    code = "memory_projection_error"


class UnsupportedMemorySourceError(MemoryProjectionError):
    code = "unsupported_memory_source"


class InvalidCommittedSourceError(MemoryProjectionError):
    code = "invalid_committed_source"


class MemoryStorageError(MemoryError):
    code = "memory_storage_error"


class MemoryStoreNotInitializedError(MemoryStorageError):
    code = "memory_store_not_initialized"


class MemorySchemaVersionError(MemoryStorageError):
    code = "memory_schema_version_incompatible"


class MemoryStoreCorruptionError(MemoryStorageError):
    code = "memory_store_corrupt"


class ProjectionConflictError(MemoryStorageError):
    code = "projection_conflict"


class MemoryNotFoundError(MemoryStorageError):
    code = "memory_not_found"


class MemoryPlayerIsolationError(MemoryStorageError):
    code = "memory_player_mismatch"


class MemoryTombstonedError(MemoryStorageError):
    code = "memory_tombstoned"


class MemoryLifecycleConflictError(MemoryStorageError):
    code = "memory_lifecycle_conflict"


class InvalidMemoryLifecycleError(MemoryStorageError):
    code = "invalid_memory_lifecycle"


class EmbeddingError(MemoryError):
    code = "embedding_error"


class EmbeddingContractError(EmbeddingError):
    code = "embedding_contract_error"


class EmbeddingSpaceMismatchError(EmbeddingContractError):
    code = "embedding_space_mismatch"


class EmbeddingVectorError(EmbeddingContractError):
    code = "embedding_vector_invalid"


class MemoryEmbeddingConflictError(MemoryStorageError):
    code = "memory_embedding_conflict"


class MemoryIndexIncompleteError(EmbeddingError):
    code = "memory_index_incomplete"

    def __init__(self, message: str, *, index_state: "MemoryIndexState") -> None:
        super().__init__(message)
        self.index_state = index_state
