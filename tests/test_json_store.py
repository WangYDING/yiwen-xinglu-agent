from pathlib import Path

import pytest

from xuanyi_npc.domain import CaseDefinition, CaseSessionState, PlayerState
from xuanyi_npc.storage import (
    JsonStateStore,
    StateCorruptionError,
    StateNotFoundError,
    StorageError,
)


def test_player_state_save_and_load(
    tmp_path: Path,
    player_state: PlayerState,
) -> None:
    store = JsonStateStore(tmp_path)

    saved_path = store.save_player(player_state)

    assert saved_path.exists()
    assert store.load_player(player_state.player_id) == player_state


def test_case_session_save_and_load(
    tmp_path: Path,
    player_state: PlayerState,
    case_definition: CaseDefinition,
) -> None:
    store = JsonStateStore(tmp_path)
    session = CaseSessionState(
        session_id="session_umbrella",
        case_id=case_definition.case_id,
        player_id=player_state.player_id,
    )

    saved_path = store.save_case_session(session)

    assert saved_path.exists()
    assert store.load_case_session(session.session_id) == session


def test_missing_state_has_explicit_error(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path)

    with pytest.raises(StateNotFoundError):
        store.load_player("player_missing")


def test_corrupted_state_has_explicit_error(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path)
    corrupt_path = tmp_path / "players" / "player_broken.json"
    corrupt_path.parent.mkdir(parents=True)
    corrupt_path.write_text('{"player_id": "player_broken"}', encoding="utf-8")

    with pytest.raises(StateCorruptionError):
        store.load_player("player_broken")


def test_invalid_identifier_cannot_escape_storage_root(tmp_path: Path) -> None:
    store = JsonStateStore(tmp_path)

    with pytest.raises(StorageError, match="identifier"):
        store.load_player("../outside")


def test_directory_creation_failure_has_explicit_error(
    tmp_path: Path,
    player_state: PlayerState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonStateStore(tmp_path)

    def fail_to_create_directory(*args: object, **kwargs: object) -> None:
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(Path, "mkdir", fail_to_create_directory)

    with pytest.raises(StorageError, match="failed to save"):
        store.save_player(player_state)
