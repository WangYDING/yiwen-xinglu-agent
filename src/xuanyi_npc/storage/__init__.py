"""State persistence interfaces for the investigation runtime."""

from .json_store import JsonStateStore, StateConflictError, StateCorruptionError, StateNotFoundError, StorageError
from .sqlite_memory import MEMORY_SCHEMA_VERSION, SQLiteMemoryRepository
from .sqlite_cooperation import (
    COOPERATION_SCHEMA_VERSION,
    CooperativeHistoryError,
    CooperativePayloadConflict,
    CooperativeTurnRecord,
    SQLiteCooperativeHistoryRepository,
)

__all__ = [
    "JsonStateStore",
    "MEMORY_SCHEMA_VERSION",
    "SQLiteMemoryRepository",
    "COOPERATION_SCHEMA_VERSION",
    "CooperativeHistoryError",
    "CooperativePayloadConflict",
    "CooperativeTurnRecord",
    "SQLiteCooperativeHistoryRepository",
    "StateCorruptionError",
    "StateConflictError",
    "StateNotFoundError",
    "StorageError",
]
