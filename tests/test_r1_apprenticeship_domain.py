from datetime import datetime, timezone

import pytest

from xuanyi_npc.application import ProgressionPolicy
from xuanyi_npc.domain import (
    AbilityId,
    ApprenticeshipEventReplayer,
    ApprenticeshipState,
)


def test_initial_state_has_seven_locked_unlearned_abilities_and_replays() -> None:
    policy = ProgressionPolicy.load_default()
    state = policy.initialize(
        "player_domain_r1",
        datetime(2026, 8, 11, tzinfo=timezone.utc),
    )

    assert set(state.abilities) == set(AbilityId)
    assert len(state.abilities)==7
    assert {item.proficiency for item in state.abilities.values()} == {0}
    assert not any(item.unlocked for item in state.abilities.values())
    assert state.relationship.model_dump() == {
        "affinity": 10,
        "trust": 10,
        "recognition": 10,
    }
    assert state.revision == 1
    assert state.completed_source_sessions == ()
    assert ApprenticeshipEventReplayer().replay(state.events) == state


def test_completed_sessions_cannot_be_independently_changed() -> None:
    policy = ProgressionPolicy.load_default()
    state = policy.initialize(
        "player_domain_r2",
        datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    payload = state.model_dump(mode="python")
    payload["completed_source_sessions"] = ("session_forged",)

    with pytest.raises(ValueError, match="derived from events"):
        ApprenticeshipState.model_validate(payload)
