from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from xuanyi_npc.config import AgentVariant
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    ExecuteTreatmentCommand,
    InvestigationCommand,
    PlayerState,
    SubmitDiagnosisCommand,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.engine import CaseEngine, CaseEventReplayer, EventReplayError
from xuanyi_npc.evaluation import EpisodeResult, EpisodeStatus, EpisodeStep


BASE_TIME = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)


ACTION_TOOL_NAMES = {
    CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
    CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
    CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
    CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
    CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
}


def run_completed_episode(
    case: CaseDefinition,
    player: PlayerState,
) -> EpisodeResult:
    engine = CaseEngine()
    initial = CaseSessionState(
        session_id="session_episode_replay",
        case_id=case.case_id,
        player_id=player.player_id,
    )
    current = initial
    events = []
    steps = []

    def record(command: object, tool_name: ToolName, index: int) -> None:
        nonlocal current
        result = engine.execute(case, player, current, command)  # type: ignore[arg-type]
        current = result.session
        events.extend(result.events)
        steps.append(
            EpisodeStep(
                step_index=index,
                action=AgentAction(
                    action_id=f"agent_action_{index:02d}",
                    action_type=AgentActionType.USE_TOOL,
                    dialogue="执行经过约束的病例操作。",
                    tool_call=ToolCallRequest(name=tool_name, arguments={}),
                    confidence=0.9,
                ),
                accepted=True,
                event_sequences=tuple(event.sequence for event in result.events),
            )
        )

    investigation_ids = (
        "observe_scholar",
        "ask_about_memory",
        "inspect_umbrella",
        "observe_contract_trace",
        "search_book_chest",
        "ask_about_promise",
    )
    for index, investigation_id in enumerate(investigation_ids, start=1):
        investigation = next(
            item
            for item in case.investigations
            if item.investigation_id == investigation_id
        )
        record(
            InvestigationCommand(
                investigation_id=investigation.investigation_id,
                action_type=investigation.action_type,
                target_id=investigation.target_id,
                occurred_at=BASE_TIME + timedelta(minutes=index),
            ),
            ACTION_TOOL_NAMES[investigation.action_type],
            index,
        )

    record(
        SubmitDiagnosisCommand(
            diagnosis_id="unfulfilled_rain_vow_contract",
            evidence_clue_ids=current.discovered_clue_ids,
            occurred_at=BASE_TIME + timedelta(minutes=7),
        ),
        ToolName.SUBMIT_DIAGNOSIS,
        7,
    )
    treatment_result = engine.execute(
        case,
        player,
        current,
        ExecuteTreatmentCommand(
            treatment_id="return_token_and_fulfill_vow",
            occurred_at=BASE_TIME + timedelta(minutes=8),
        ),
    )
    current = treatment_result.session
    events.extend(treatment_result.events)
    steps.append(
        EpisodeStep(
            step_index=8,
            action=AgentAction(
                action_id="agent_action_08",
                action_type=AgentActionType.USE_TOOL,
                dialogue="执行经过约束的病例操作。",
                tool_call=ToolCallRequest(
                    name=ToolName.EXECUTE_TREATMENT,
                    arguments={},
                ),
                confidence=0.9,
            ),
            accepted=True,
            event_sequences=tuple(
                event.sequence for event in treatment_result.events
            ),
        )
    )
    assert treatment_result.score_breakdown is not None
    return EpisodeResult(
        episode_id="episode_correct_route",
        variant=AgentVariant.V0,
        status=EpisodeStatus.COMPLETED,
        max_steps=12,
        initial_session=initial,
        final_session=current,
        steps=tuple(steps),
        events=tuple(events),
        score_breakdown=treatment_result.score_breakdown,
    )


def test_initial_state_plus_events_rebuilds_identical_final_state(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    episode = run_completed_episode(case_definition, qualified_player_state)

    replayed = CaseEventReplayer().replay(
        episode.initial_session,
        episode.events,
    )

    assert replayed == episode.final_session


def test_episode_result_serialization_round_trip(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    episode = run_completed_episode(case_definition, qualified_player_state)

    restored = EpisodeResult.model_validate_json(episode.model_dump_json())

    assert restored == episode


def test_replay_rejects_event_sequence_gap(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    episode = run_completed_episode(case_definition, qualified_player_state)
    first_event = episode.events[0].model_copy(update={"sequence": 2})

    with pytest.raises(EventReplayError, match="expected event sequence"):
        CaseEventReplayer().replay(episode.initial_session, (first_event,))


def test_replay_rejects_events_after_completion(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    episode = run_completed_episode(case_definition, qualified_player_state)
    extra_event = episode.events[0].model_copy(
        update={"sequence": len(episode.events) + 1}
    )

    with pytest.raises(EventReplayError, match="after case completion"):
        CaseEventReplayer().replay(
            episode.initial_session,
            (*episode.events, extra_event),
        )


def test_max_steps_boundary_is_enforced(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    session = CaseSessionState(
        session_id="session_max_steps",
        case_id=case_definition.case_id,
        player_id=qualified_player_state.player_id,
    )
    first_step = EpisodeStep(
        step_index=1,
        action=AgentAction(
            action_id="agent_action_wait",
            action_type=AgentActionType.RESPOND,
            dialogue="暂不行动。",
            confidence=0.5,
        ),
        accepted=True,
    )
    valid = EpisodeResult(
        episode_id="episode_max_steps",
        variant=AgentVariant.V0,
        status=EpisodeStatus.MAX_STEPS_REACHED,
        max_steps=1,
        initial_session=session,
        final_session=session,
        steps=(first_step,),
    )
    assert valid.status is EpisodeStatus.MAX_STEPS_REACHED

    second_step = EpisodeStep(
        step_index=2,
        action=AgentAction(
            action_id="agent_action_wait_again",
            action_type=AgentActionType.RESPOND,
            dialogue="仍不行动。",
            confidence=0.5,
        ),
        accepted=True,
    )
    with pytest.raises(ValidationError, match="exceed max_steps"):
        EpisodeResult(
            episode_id="episode_too_many_steps",
            variant=AgentVariant.V0,
            status=EpisodeStatus.MAX_STEPS_REACHED,
            max_steps=1,
            initial_session=session,
            final_session=session,
            steps=(first_step, second_step),
        )


def test_episode_result_rejects_unknown_fields(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    episode = run_completed_episode(case_definition, qualified_player_state)
    data = episode.model_dump(mode="json")
    data["hidden_truth"] = case_definition.root_cause

    with pytest.raises(ValidationError):
        EpisodeResult.model_validate(data)


def test_episode_result_rejects_final_state_that_disagrees_with_events(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    episode = run_completed_episode(case_definition, qualified_player_state)
    data = episode.model_dump(mode="json")
    data["final_session"]["score"] = 99

    with pytest.raises(ValidationError, match="event-replayed state"):
        EpisodeResult.model_validate(data)
