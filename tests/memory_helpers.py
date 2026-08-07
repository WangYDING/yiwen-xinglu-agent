from __future__ import annotations

from datetime import datetime, timedelta, timezone

from xuanyi_npc.domain import (
    CaseDefinition,
    CaseSessionState,
    ExecuteTreatmentCommand,
    InvestigationCommand,
    PlayerState,
    SubmitDiagnosisCommand,
)
from xuanyi_npc.engine import CaseEngine, EngineResult


MEMORY_BASE_TIME = datetime(2026, 8, 7, 9, 0, tzinfo=timezone.utc)


def reference_case_results(
    case: CaseDefinition,
    player: PlayerState,
    *,
    session_id: str = "session_memory_reference",
    diagnosis_id: str = "rain_vow_breach",
) -> tuple[CaseSessionState, tuple[tuple[CaseSessionState, EngineResult], ...]]:
    engine = CaseEngine()
    initial = CaseSessionState(
        session_id=session_id,
        case_id=case.case_id,
        player_id=player.player_id,
    )
    current = initial
    results: list[tuple[CaseSessionState, EngineResult]] = []
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
        before = current
        result = engine.execute(
            case,
            player,
            before,
            InvestigationCommand(
                investigation_id=investigation.investigation_id,
                action_type=investigation.action_type,
                target_id=investigation.target_id,
                occurred_at=MEMORY_BASE_TIME + timedelta(minutes=index),
            ),
        )
        results.append((before, result))
        current = result.session

    before = current
    diagnosis_result = engine.execute(
        case,
        player,
        before,
        SubmitDiagnosisCommand(
            diagnosis_id=diagnosis_id,
            evidence_clue_ids=current.discovered_clue_ids,
            occurred_at=MEMORY_BASE_TIME + timedelta(minutes=7),
        ),
    )
    results.append((before, diagnosis_result))
    current = diagnosis_result.session

    before = current
    treatment_result = engine.execute(
        case,
        player,
        before,
        ExecuteTreatmentCommand(
            treatment_id="return_token_and_fulfill_vow",
            occurred_at=MEMORY_BASE_TIME + timedelta(minutes=8),
        ),
    )
    results.append((before, treatment_result))
    return initial, tuple(results)
