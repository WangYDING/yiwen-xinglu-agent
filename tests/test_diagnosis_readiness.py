from datetime import datetime, timedelta, timezone

import pytest

from xuanyi_npc.application import (
    CaseObservation,
    DiagnosisReadinessDecision,
    FixedV0DiagnosisReadinessPolicy,
    PlayerView,
)
from xuanyi_npc.application.v0_tools import (
    DiagnosisNotReadyError,
    V0ToolExecutor,
)
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    DiagnosisSubmittedEvent,
    InvestigationCommand,
    PlayerState,
    SubmitDiagnosisCommand,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.engine import CaseEngine, CaseEventReplayer


BASE_TIME = datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc)


class AlwaysReadyPolicy:
    """Test double proving readiness can change without changing CaseEngine."""

    policy_id = "test_always_ready"

    def evaluate(
        self,
        *,
        player_view: PlayerView,
        case_observation: CaseObservation,
        proposed_action: AgentAction | None = None,
    ) -> DiagnosisReadinessDecision:
        del player_view, case_observation, proposed_action
        return DiagnosisReadinessDecision(
            policy_id=self.policy_id,
            can_submit_diagnosis=True,
        )


def _session(
    case_definition: CaseDefinition,
    player: PlayerState,
    suffix: str,
) -> CaseSessionState:
    return CaseSessionState(
        session_id=f"diagnosis_readiness_{suffix}",
        case_id=case_definition.case_id,
        player_id=player.player_id,
    )


def _diagnosis_action(diagnosis_id: str) -> AgentAction:
    return AgentAction(
        action_id="agent_step_001",
        action_type=AgentActionType.USE_TOOL,
        dialogue="提交当前判断。",
        tool_call=ToolCallRequest(
            name=ToolName.SUBMIT_DIAGNOSIS,
            arguments={"diagnosis_id": diagnosis_id, "evidence_clue_ids": []},
        ),
        confidence=0.5,
    )


def test_fixed_v0_blocks_early_diagnosis_without_events_or_state_change(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    executor = V0ToolExecutor(
        diagnosis_readiness_policy=FixedV0DiagnosisReadinessPolicy(),
    )
    initial = _session(case_definition, qualified_player_state, "fixed_block")
    observation = executor.case_observation(
        case_definition,
        qualified_player_state,
        initial,
    )

    assert observation.available_investigations
    assert observation.can_submit_diagnosis is False
    with pytest.raises(DiagnosisNotReadyError) as captured:
        executor.execute(
            _diagnosis_action("rain_vow_breach"),
            case_definition,
            qualified_player_state,
            initial,
            BASE_TIME,
        )

    assert captured.value.code == "diagnosis_not_ready"
    assert initial.revision == 0
    assert initial.action_history == ()
    assert initial.submitted_diagnosis_id is None


def test_replacing_policy_allows_engine_valid_early_diagnosis(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    executor = V0ToolExecutor(
        diagnosis_readiness_policy=AlwaysReadyPolicy(),
    )
    initial = _session(case_definition, qualified_player_state, "replaceable")

    observation = executor.case_observation(
        case_definition,
        qualified_player_state,
        initial,
    )
    result = executor.execute(
        _diagnosis_action("rain_vow_breach"),
        case_definition,
        qualified_player_state,
        initial,
        BASE_TIME,
    )

    assert observation.can_submit_diagnosis is True
    assert result.session.submitted_diagnosis_id == "rain_vow_breach"
    assert len(result.events) == 1
    assert isinstance(result.events[0], DiagnosisSubmittedEvent)
    assert initial.revision == 0


def test_domain_events_allow_diagnosis_then_investigation_then_revision(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    initial = _session(case_definition, qualified_player_state, "revision")
    first = engine.execute(
        case_definition,
        qualified_player_state,
        initial,
        SubmitDiagnosisCommand(
            diagnosis_id="evil_spirit_attack",
            occurred_at=BASE_TIME,
        ),
    )
    investigated = engine.execute(
        case_definition,
        qualified_player_state,
        first.session,
        InvestigationCommand(
            investigation_id="observe_scholar",
            action_type=CaseActionType.OBSERVE_PATIENT,
            target_id="scholar_lu",
            occurred_at=BASE_TIME + timedelta(minutes=1),
        ),
    )
    revised = engine.execute(
        case_definition,
        qualified_player_state,
        investigated.session,
        SubmitDiagnosisCommand(
            diagnosis_id="rain_vow_breach",
            evidence_clue_ids={"fading_shadow"},
            occurred_at=BASE_TIME + timedelta(minutes=2),
        ),
    )
    events = (*first.events, *investigated.events, *revised.events)

    assert revised.session.submitted_diagnosis_id == "rain_vow_breach"
    assert tuple(record.action_type for record in revised.session.action_history) == (
        CaseActionType.SUBMIT_DIAGNOSIS,
        CaseActionType.OBSERVE_PATIENT,
        CaseActionType.SUBMIT_DIAGNOSIS,
    )
    assert CaseEventReplayer().replay(initial, events) == revised.session
