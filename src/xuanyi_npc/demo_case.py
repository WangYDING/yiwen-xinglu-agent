"""Human-readable deterministic replay of the M1 technical case."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from xuanyi_npc.domain import (
    CaseDefinition,
    CaseSessionState,
    ExecuteTreatmentCommand,
    InvestigationCommand,
    PlayerState,
    RelationshipState,
    SkillState,
    SubmitDiagnosisCommand,
)
from xuanyi_npc.engine import CaseEngine


CASE_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "cases"
    / "old_paper_umbrella.json"
)


def build_demo_player() -> PlayerState:
    return PlayerState(
        player_id="player_demo_apprentice",
        display_name="演示学徒",
        skills={
            "observe_form": SkillState(
                skill_id="observe_form", proficiency=30, unlocked=True
            ),
            "ask_cause": SkillState(
                skill_id="ask_cause", proficiency=30, unlocked=True
            ),
            "inspect_object": SkillState(
                skill_id="inspect_object",
                proficiency=30,
                unlocked=True,
                prerequisite_ids={"observe_form"},
            ),
            "observe_qi": SkillState(
                skill_id="observe_qi",
                proficiency=25,
                unlocked=True,
                prerequisite_ids={"observe_form", "inspect_object"},
            ),
        },
        relationship=RelationshipState(affinity=10, trust=5, recognition=0),
    )


def main() -> int:
    case = CaseDefinition.model_validate_json(CASE_PATH.read_text(encoding="utf-8"))
    player = build_demo_player()
    session = CaseSessionState(
        session_id="session_demo_umbrella",
        case_id=case.case_id,
        player_id=player.player_id,
    )
    engine = CaseEngine()
    base_time = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)

    print(f"病例：{case.title}")
    print(case.synopsis)
    print()

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
        result = engine.execute(
            case,
            player,
            session,
            InvestigationCommand(
                investigation_id=investigation.investigation_id,
                action_type=investigation.action_type,
                target_id=investigation.target_id,
                occurred_at=base_time + timedelta(minutes=index),
            ),
        )
        session = result.session
        print(f"{index}. {result.message}")

    diagnosis_result = engine.execute(
        case,
        player,
        session,
        SubmitDiagnosisCommand(
            diagnosis_id="rain_vow_breach",
            evidence_clue_ids=session.discovered_clue_ids,
            occurred_at=base_time + timedelta(minutes=7),
        ),
    )
    session = diagnosis_result.session
    print(f"7. {diagnosis_result.message}")

    treatment_result = engine.execute(
        case,
        player,
        session,
        ExecuteTreatmentCommand(
            treatment_id="return_token_and_fulfill_vow",
            occurred_at=base_time + timedelta(minutes=8),
        ),
    )
    print(f"8. {treatment_result.message}")

    breakdown = treatment_result.score_breakdown
    if breakdown is None:
        raise RuntimeError("completed treatment did not produce a score")
    print()
    print(
        "评分："
        f"线索 {breakdown.clue_points} + "
        f"诊断 {breakdown.diagnosis_points} + "
        f"处置 {breakdown.treatment_points} - "
        f"危险处置惩罚 {breakdown.unsafe_treatment_penalty} "
        f"= {breakdown.total}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
