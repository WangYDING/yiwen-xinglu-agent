"""State persistence interfaces for the M0 vertical foundation."""

from .json_store import JsonStateStore, StateCorruptionError, StateNotFoundError, StorageError

__all__ = [
    "JsonStateStore",
    "StateCorruptionError",
    "StateNotFoundError",
    "StorageError",
]
