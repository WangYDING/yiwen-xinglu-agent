"""Explicit, safe failure categories for M4 memory persistence."""


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
