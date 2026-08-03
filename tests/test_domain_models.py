from datetime import datetime

import pytest
from pydantic import ValidationError

from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseDefinition,
    CaseSessionState,
    MemoryEvent,
    MemoryType,
    PlayerState,
    RelationshipState,
    SkillState,
    StateChangeProposal,
    ProposedChangeTarget,
)


def test_all_seven_core_models_round_trip(
    player_state: PlayerState,
    case_definition: CaseDefinition,
) -> None:
    models = [
        player_state,
        SkillState(skill_id="observe_form", proficiency=25, unlocked=True),
        RelationshipState(affinity=10, trust=5, recognition=0),
        case_definition,
        CaseSessionState(
            session_id="session_umbrella",
            case_id=case_definition.case_id,
            player_id=player_state.player_id,
        ),
        MemoryEvent(
            event_id="event_first_visit",
            player_id=player_state.player_id,
            event_type=MemoryType.EPISODIC,
            content="玩家第一次进入医馆。",
            importance=2,
        ),
        AgentAction(
            action_id="action_greeting",
            action_type=AgentActionType.RESPOND,
            dialogue="先看清眼前之事，再谈结论。",
            confidence=0.9,
        ),
    ]

    for model in models:
        restored = type(model).model_validate_json(model.model_dump_json())
        assert restored == model


@pytest.mark.parametrize("field", ["affinity", "trust", "recognition"])
@pytest.mark.parametrize("invalid_value", [-1, 101, "10"])
def test_relationship_rejects_out_of_range_or_coerced_values(
    field: str,
    invalid_value: object,
) -> None:
    values: dict[str, object] = {"affinity": 0, "trust": 0, "recognition": 0}
    values[field] = invalid_value

    with pytest.raises(ValidationError):
        RelationshipState.model_validate(values)


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        RelationshipState.model_validate(
            {"affinity": 0, "trust": 0, "recognition": 0, "favor": 99}
        )


def test_locked_skill_cannot_hold_proficiency() -> None:
    with pytest.raises(ValidationError, match="locked skill"):
        SkillState(skill_id="observe_qi", proficiency=1, unlocked=False)


def test_player_rejects_missing_skill_prerequisite() -> None:
    with pytest.raises(ValidationError, match="missing prerequisites"):
        PlayerState(
            player_id="player_apprentice",
            display_name="学徒",
            skills={
                "observe_qi": SkillState(
                    skill_id="observe_qi",
                    proficiency=20,
                    unlocked=True,
                    prerequisite_ids={"observe_form"},
                )
            },
        )


def test_player_rejects_locked_skill_prerequisite() -> None:
    with pytest.raises(ValidationError, match="locked prerequisites"):
        PlayerState(
            player_id="player_apprentice",
            display_name="学徒",
            skills={
                "observe_form": SkillState(
                    skill_id="observe_form",
                    proficiency=0,
                    unlocked=False,
                ),
                "observe_qi": SkillState(
                    skill_id="observe_qi",
                    proficiency=20,
                    unlocked=True,
                    prerequisite_ids={"observe_form"},
                ),
            },
        )


def test_agent_action_rejects_unknown_action_type() -> None:
    with pytest.raises(ValidationError):
        AgentAction.model_validate(
            {
                "action_id": "action_invalid",
                "action_type": "rewrite_world_truth",
                "dialogue": "病例已经被我改写。",
                "confidence": 1.0,
            }
        )


def test_agent_tool_action_requires_tool_request() -> None:
    with pytest.raises(ValidationError, match="require tool_call"):
        AgentAction(
            action_id="action_missing_tool",
            action_type=AgentActionType.USE_TOOL,
            dialogue="让我先检查。",
            confidence=0.8,
        )


def test_skill_proposal_requires_skill_id() -> None:
    with pytest.raises(ValidationError, match="require skill_id"):
        StateChangeProposal(
            target=ProposedChangeTarget.SKILL_PROFICIENCY,
            delta=2,
            reason="观察过程完整。",
        )


def test_memory_event_rejects_naive_timestamp(player_state: PlayerState) -> None:
    with pytest.raises(ValidationError, match="timezone"):
        MemoryEvent(
            event_id="event_naive_time",
            player_id=player_state.player_id,
            event_type=MemoryType.LEARNING,
            content="测试事件。",
            importance=1,
            occurred_at=datetime(2026, 8, 3, 12, 0, 0),
        )


def test_case_session_rejects_incomplete_completion(
    player_state: PlayerState,
    case_definition: CaseDefinition,
) -> None:
    with pytest.raises(ValidationError, match="completed session"):
        CaseSessionState(
            session_id="session_incomplete",
            case_id=case_definition.case_id,
            player_id=player_state.player_id,
            status="completed",
        )
