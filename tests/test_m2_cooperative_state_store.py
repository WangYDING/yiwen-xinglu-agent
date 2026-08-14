from pathlib import Path

import pytest

from xuanyi_npc.domain import CaseSessionState
from xuanyi_npc.domain.cooperative_planning import CooperativeAgentState
from xuanyi_npc.storage import (
    JsonStateStore,
    StateConflictError,
    StateCorruptionError,
    StateNotFoundError,
    StorageError,
)
from tests.test_m2_goal_plan_domain import active_plan, current_goal, episode_goal


def state(revision: int = 1, *, player_id="player_one", case_id="case_one") -> CooperativeAgentState:
    return CooperativeAgentState(
        player_id=player_id,
        case_id=case_id,
        session_id="session_one",
        episode_goal=episode_goal(),
        current_goal=current_goal(),
        current_plan=active_plan(),
        revision=revision,
        updated_turn_id=f"turn_{revision}",
    )


def store_with_session(tmp_path: Path) -> JsonStateStore:
    store = JsonStateStore(tmp_path)
    store.save_case_session(CaseSessionState(
        session_id="session_one",
        case_id="case_one",
        player_id="player_one",
    ))
    return store


def test_cooperative_agent_state_round_trips_under_existing_json_store(tmp_path: Path) -> None:
    store = store_with_session(tmp_path)
    saved = store.save_cooperative_agent_state(state(), expected_revision=0)
    assert saved == tmp_path / "cooperative_agents" / "session_one.json"
    assert store.load_cooperative_agent_state(
        "session_one", player_id="player_one", case_id="case_one"
    ) == state()


def test_cooperative_agent_state_persists_across_store_instances(tmp_path: Path) -> None:
    store_with_session(tmp_path).save_cooperative_agent_state(state(), expected_revision=0)
    assert JsonStateStore(tmp_path).load_cooperative_agent_state("session_one") == state()


def test_revision_checked_update_advances_exactly_once(tmp_path: Path) -> None:
    store = store_with_session(tmp_path)
    store.save_cooperative_agent_state(state(), expected_revision=0)
    store.save_cooperative_agent_state(state(2), expected_revision=1)
    assert store.load_cooperative_agent_state("session_one").revision == 2


def test_missing_state_and_stale_revision_are_explicit(tmp_path: Path) -> None:
    store = store_with_session(tmp_path)
    with pytest.raises(StateNotFoundError):
        store.load_cooperative_agent_state("session_one")
    store.save_cooperative_agent_state(state(), expected_revision=0)
    with pytest.raises(StateConflictError, match="stale"):
        store.save_cooperative_agent_state(state(2), expected_revision=0)
    with pytest.raises(StateConflictError, match="exactly once"):
        store.save_cooperative_agent_state(state(3), expected_revision=1)


def test_state_ownership_must_match_authoritative_case_session(tmp_path: Path) -> None:
    store = store_with_session(tmp_path)
    with pytest.raises(StateCorruptionError, match="ownership"):
        store.save_cooperative_agent_state(state(player_id="player_other"), expected_revision=0)
    with pytest.raises(StateCorruptionError, match="ownership"):
        store.save_cooperative_agent_state(state(case_id="case_other"), expected_revision=0)


def test_load_scope_rejects_cross_player_and_cross_case_access(tmp_path: Path) -> None:
    store = store_with_session(tmp_path)
    store.save_cooperative_agent_state(state(), expected_revision=0)
    with pytest.raises(StateCorruptionError, match="player"):
        store.load_cooperative_agent_state("session_one", player_id="player_other")
    with pytest.raises(StateCorruptionError, match="case"):
        store.load_cooperative_agent_state("session_one", case_id="case_other")


def test_failed_atomic_replace_preserves_previous_snapshot(tmp_path: Path, monkeypatch) -> None:
    store = store_with_session(tmp_path)
    store.save_cooperative_agent_state(state(), expected_revision=0)

    def fail_replace(source, target):
        del source, target
        raise OSError("simulated replace failure")

    monkeypatch.setattr("xuanyi_npc.storage.json_store.os.replace", fail_replace)
    with pytest.raises(StorageError, match="failed to save"):
        store.save_cooperative_agent_state(state(2), expected_revision=1)
    assert store.load_cooperative_agent_state("session_one") == state()
