"""Atomic JSON persistence for player and case-session state."""

from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

from xuanyi_npc.domain.base import Identifier
from xuanyi_npc.domain.campaign import CampaignState
from xuanyi_npc.domain.cases import CaseSessionState
from xuanyi_npc.domain.cooperative_planning import CooperativeAgentState
from xuanyi_npc.domain.player import PlayerState


class StorageError(RuntimeError):
    """Base error for state persistence failures."""


class StateNotFoundError(StorageError):
    """Raised when a requested state snapshot does not exist."""


class StateCorruptionError(StorageError):
    """Raised when stored JSON cannot be parsed as the expected model."""


class StateConflictError(StorageError):
    """Raised when a revision-checked state update is stale."""


ModelT = TypeVar("ModelT", bound=BaseModel)
_identifier_adapter = TypeAdapter(Identifier)


class JsonStateStore:
    """Small M0 store with atomic replacement and typed load boundaries."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def save_player(self, state: PlayerState) -> Path:
        return self._write("players", state.player_id, state)

    def load_player(self, player_id: str) -> PlayerState:
        source = self._path("players", player_id)
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise StateNotFoundError("players state does not exist") from exc
        except OSError as exc:
            raise StorageError("failed to read players state") from exc
        except (json.JSONDecodeError, TypeError) as exc:
            raise StateCorruptionError("players state is invalid") from exc

        # Removed growth-system fields are ignored only at this persistence
        # boundary, allowing pre-cleanup player snapshots to remain playable.
        if isinstance(data, dict):
            data.pop("teaching_stage", None)
            data.pop("relationship", None)
        try:
            return PlayerState.model_validate(data)
        except (ValidationError, ValueError) as exc:
            raise StateCorruptionError("players state is invalid") from exc

    def save_case_session(self, state: CaseSessionState) -> Path:
        return self._write("case_sessions", state.session_id, state)

    def load_case_session(self, session_id: str) -> CaseSessionState:
        return self._read("case_sessions", session_id, CaseSessionState)

    def save_cooperative_agent_state(
        self,
        state: CooperativeAgentState,
        *,
        expected_revision: int,
    ) -> Path:
        """Atomically persist one session-owned Agent state with optimistic revision."""

        if expected_revision < 0:
            raise StateConflictError("expected revision cannot be negative")
        try:
            session = self.load_case_session(state.session_id)
        except StateNotFoundError as exc:
            raise StateCorruptionError(
                "cooperative Agent state requires an existing case session"
            ) from exc
        if (session.player_id, session.case_id) != (state.player_id, state.case_id):
            raise StateCorruptionError(
                "cooperative Agent state ownership does not match case session"
            )
        try:
            existing = self.load_cooperative_agent_state(state.session_id)
        except StateNotFoundError:
            existing = None
        if existing is None:
            if expected_revision != 0 or state.revision != 1:
                raise StateConflictError(
                    "initial cooperative Agent state requires revision one"
                )
        else:
            if (existing.player_id, existing.case_id, existing.session_id) != (
                state.player_id,
                state.case_id,
                state.session_id,
            ):
                raise StateCorruptionError(
                    "cooperative Agent state ownership cannot change"
                )
            if existing.revision != expected_revision:
                raise StateConflictError("cooperative Agent state revision is stale")
            if state.revision != existing.revision + 1:
                raise StateConflictError(
                    "cooperative Agent state revision must advance exactly once"
                )
        return self._write("cooperative_agents", state.session_id, state)

    def load_cooperative_agent_state(
        self,
        session_id: str,
        *,
        player_id: str | None = None,
        case_id: str | None = None,
    ) -> CooperativeAgentState:
        state = self._read(
            "cooperative_agents",
            session_id,
            CooperativeAgentState,
        )
        if state.session_id != session_id:
            raise StateCorruptionError(
                "cooperative Agent state session does not match its file"
            )
        if player_id is not None and state.player_id != player_id:
            raise StateCorruptionError("cooperative Agent state player mismatch")
        if case_id is not None and state.case_id != case_id:
            raise StateCorruptionError("cooperative Agent state case mismatch")
        return state

    def save_campaign(self, state: CampaignState) -> Path:
        return self._write("campaigns", state.player_id, state)

    def load_campaign(self, player_id: str) -> CampaignState:
        return self._read("campaigns", player_id, CampaignState)

    def list_players(self) -> tuple[PlayerState, ...]:
        """Return all validated player snapshots in stable ID order."""

        return self._list("players", PlayerState, "player_id")

    def list_case_sessions(self) -> tuple[CaseSessionState, ...]:
        """Return all validated case sessions in stable ID order."""

        return self._list("case_sessions", CaseSessionState, "session_id")

    def list_campaigns(self) -> tuple[CampaignState, ...]:
        """Return all validated Campaign snapshots in stable player order."""

        return self._list("campaigns", CampaignState, "player_id")

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

    def _list(
        self,
        namespace: str,
        model_type: type[ModelT],
        identifier_field: str,
    ) -> tuple[ModelT, ...]:
        directory = self.root / namespace
        try:
            if not directory.exists():
                return ()
            if not directory.is_dir():
                raise StateCorruptionError(f"{namespace} state namespace is invalid")
            paths = tuple(sorted(directory.glob("*.json"), key=lambda path: path.name))
        except OSError as exc:
            raise StorageError(f"failed to list {namespace} state") from exc

        items: list[ModelT] = []
        for path in paths:
            try:
                payload = path.read_text(encoding="utf-8")
                item = model_type.model_validate_json(payload)
            except OSError as exc:
                raise StorageError(f"failed to read {namespace} state") from exc
            except (ValidationError, ValueError) as exc:
                raise StateCorruptionError(f"{namespace} state is invalid") from exc
            if getattr(item, identifier_field) != path.stem:
                raise StateCorruptionError(
                    f"{namespace} snapshot identifier does not match its file"
                )
            items.append(item)
        return tuple(items)
