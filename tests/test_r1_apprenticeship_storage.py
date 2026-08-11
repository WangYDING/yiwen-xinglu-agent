import json

import pytest

from xuanyi_npc.storage import JsonStateStore, StateCorruptionError

from tests.r1_helpers import build_service, complete_case, create_player


def test_apprenticeship_round_trip_and_replay_verification(tmp_path) -> None:
    service, store = build_service(tmp_path)
    player_id = create_player(service)
    complete_case(service, player_id, "old_paper_umbrella")

    state = store.load_apprenticeship(player_id)
    assert store.load_apprenticeship(player_id) == state
    assert store.list_apprenticeships() == (state,)


def test_tampered_snapshot_is_rejected(tmp_path) -> None:
    service, store = build_service(tmp_path)
    player_id = create_player(service)
    path = tmp_path / "apprenticeships" / f"{player_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["relationship"]["trust"] = 99
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StateCorruptionError):
        JsonStateStore(tmp_path).load_apprenticeship(player_id)
