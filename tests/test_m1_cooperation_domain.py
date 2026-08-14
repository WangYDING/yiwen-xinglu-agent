from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from xuanyi_npc.domain.cooperation import (
    PlayerContribution,
    PlayerContributionType,
    SuggestionDisposition,
)


def test_player_contribution_is_a_non_executable_belief_contract() -> None:
    contribution = PlayerContribution(
        contribution_id="turn_001",
        player_id="player_1",
        case_id="case_1",
        session_id="session_1",
        contribution_type=PlayerContributionType.HYPOTHESIS,
        public_text="我怀疑与肺有关，建议先询问咳嗽情况。",
        created_at=datetime(2026, 8, 14, tzinfo=timezone.utc),
    )

    assert contribution.contribution_type is PlayerContributionType.HYPOTHESIS
    assert "action" not in PlayerContribution.model_fields
    assert "tool_call" not in PlayerContribution.model_fields
    assert SuggestionDisposition.PARTIAL_ACCEPT.value == "partial_accept"


def test_player_contribution_rejects_unknown_execution_fields() -> None:
    with pytest.raises(ValidationError):
        PlayerContribution.model_validate({
            "contribution_id": "turn_001",
            "player_id": "player_1",
            "case_id": "case_1",
            "session_id": "session_1",
            "contribution_type": "suggestion",
            "public_text": "直接治疗。",
            "tool_call": {"name": "execute_treatment"},
            "created_at": "2026-08-14T00:00:00Z",
        })
