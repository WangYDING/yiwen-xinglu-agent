from datetime import datetime, timezone

import pytest

from xuanyi_npc.domain import LessonAssigned, TeachingEventReplayer


def test_assignment_replays_and_rejects_sequence_gap():
    event = LessonAssigned(
        sequence=1,
        teaching_session_id="teaching_test",
        occurred_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        player_id="player_test",
        mentor_id="xuanyi_mentor",
        lesson_id="evidence_before_diagnosis_v1",
        case_session_id="session_test",
    )
    state = TeachingEventReplayer().replay((event,))
    assert state.revision == 1
    with pytest.raises(ValueError):
        TeachingEventReplayer().replay((event.model_copy(update={"sequence": 2}),))
