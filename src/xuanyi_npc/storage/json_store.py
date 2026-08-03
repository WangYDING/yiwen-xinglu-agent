"""Atomic JSON persistence for player and case-session state."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from xuanyi_npc.domain.base import Identifier
from xuanyi_npc.domain.cases import CaseSessionState
from xuanyi_npc.domain.player import PlayerState


class StorageError(RuntimeError):
    """Base error for state persistence failures."""


class StateNotFoundError(StorageError):
    """Raised when a requested state snapshot does not exist."""


class StateCorruptionError(StorageError):
    """Raised when stored JSON cannot be parsed as the expected model."""


ModelT = TypeVar("ModelT", bound=BaseModel)
_identifier_adapter = TypeAdapter(Identifier)


class JsonStateStore:
    """Small M0 store with atomic replacement and typed load boundaries."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def save_player(self, state: PlayerState) -> Path:
        return self._write("players", state.player_id, state)

    def load_player(self, player_id: str) -> PlayerState:
        return self._read("players", player_id, PlayerState)

    def save_case_session(self, state: CaseSessionState) -> Path:
        return self._write("case_sessions", state.session_id, state)

    def load_case_session(self, session_id: str) -> CaseSessionState:
        return self._read("case_sessions", session_id, CaseSessionState)

    def _path(self, namespace: str, identifier: str) -> Path:
        try:
            safe_identifier = _identifier_adapter.validate_python(identifier)
        except ValidationError as exc:
            raise StorageError("state identifier is invalid") from exc
        return self.root / namespace / f"{safe_identifier}.json"

    def _write(self, namespace: str, identifier: str, state: BaseModel) -> Path:
        target = self._path(namespace, identifier)
        temp_path: Path | None = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = state.model_dump_json(indent=2)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=target.parent,
                prefix=f".{target.stem}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
        except OSError as exc:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            raise StorageError(f"failed to save {namespace} state") from exc
        return target

    def _read(
        self,
        namespace: str,
        identifier: str,
        model_type: type[ModelT],
    ) -> ModelT:
        source = self._path(namespace, identifier)
        try:
            payload = source.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise StateNotFoundError(f"{namespace} state does not exist") from exc
        except OSError as exc:
            raise StorageError(f"failed to read {namespace} state") from exc

        try:
            return model_type.model_validate_json(payload)
        except (ValidationError, ValueError) as exc:
            raise StateCorruptionError(f"{namespace} state is invalid") from exc
