"""Hand-authored Gold snapshots; expected states are not produced by CaseEngine."""

import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from xuanyi_npc.domain import CaseEvent, CaseSessionState
from xuanyi_npc.engine import CaseEventReplayer


GOLD_DIR = Path(__file__).parent / "gold" / "event_replay"
event_sequence_adapter = TypeAdapter(tuple[CaseEvent, ...])


@pytest.mark.parametrize(
    "snapshot_name",
    [
        "unsafe_treatment.json",
        "repeated_investigation_and_revision.json",
    ],
)
def test_hand_authored_event_replay_gold_snapshot(snapshot_name: str) -> None:
    payload = json.loads((GOLD_DIR / snapshot_name).read_text(encoding="utf-8"))
    initial = CaseSessionState.model_validate(payload["initial_session"])
    events = event_sequence_adapter.validate_python(payload["events"])
    expected = CaseSessionState.model_validate(payload["expected_final_session"])

    replayed = CaseEventReplayer().replay(initial, events)

    assert replayed == expected
