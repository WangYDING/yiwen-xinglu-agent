"""Hand-authored event replay fixtures; expected states are not produced by CaseEngine."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from xuanyi_npc.domain import CaseEvent, CaseSessionState
from xuanyi_npc.engine import CaseEventReplayer


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "event_replay"
FIXTURE_SHA256 = {
    "repeated_investigation_and_revision.json": "544796f0506a56e528115de2c893ec47a6e27d8aed98ecc8c33a707df9c41c57",
    "unsafe_treatment.json": "c2207450f09d9fe238b32c34b406b5b894500d589efa1958fde04d2ce1ddf7c6",
}
event_sequence_adapter = TypeAdapter(tuple[CaseEvent, ...])


@pytest.mark.parametrize(
    "snapshot_name",
    [
        "unsafe_treatment.json",
        "repeated_investigation_and_revision.json",
    ],
)
def test_hand_authored_event_replay_fixture(snapshot_name: str) -> None:
    path = FIXTURE_DIR / snapshot_name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == FIXTURE_SHA256[snapshot_name]
    payload = json.loads(path.read_text(encoding="utf-8"))
    initial = CaseSessionState.model_validate(payload["initial_session"])
    events = event_sequence_adapter.validate_python(payload["events"])
    expected = CaseSessionState.model_validate(payload["expected_final_session"])

    replayed = CaseEventReplayer().replay(initial, events)

    assert replayed == expected
