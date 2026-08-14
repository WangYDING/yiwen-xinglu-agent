"""State persistence interfaces for the M0 vertical foundation."""

from .json_store import JsonStateStore, StateConflictError, StateCorruptionError, StateNotFoundError, StorageError
from .sqlite_memory import MEMORY_SCHEMA_VERSION, SQLiteMemoryRepository

__all__ = [
    "JsonStateStore",
    "MEMORY_SCHEMA_VERSION",
    "SQLiteMemoryRepository",
    "StateCorruptionError",
    "StateConflictError",
    "StateNotFoundError",
    "StorageError",
]
