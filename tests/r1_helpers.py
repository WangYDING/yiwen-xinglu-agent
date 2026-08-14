from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from xuanyi_npc.application import (
    CampaignRuleSet,
    CaseCatalog,
    CreatePlayerInput,
    MultiCaseEpisodeService,
    StartEpisodeInput,
    SubmitActionInput,
)
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseActionType,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.storage import JsonStateStore


ROOT = Path(__file__).parents[1]
RESOURCE_ROOT = ROOT / "src" / "xuanyi_npc" / "resources"
CASE_DIR = RESOURCE_ROOT / "cases"
CAMPAIGN_RULES = RESOURCE_ROOT / "campaign" / "cross_episode_rules_v1.json"

TRACES = {
    "old_paper_umbrella": (
        "rain_vow_breach",
        "return_token_and_fulfill_vow",
    ),
    "gray_hearth_inn": (
        "displaced_hearth_contract",
        "restore_token_and_clear_flue",
    ),
    "moon_well_echo": (
        "misbound_message_handoff",
        "verify_recipient_and_deliver",
    ),
}

TOOLS = {
    CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
    CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
    CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
    CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
    CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
}


class FixedClock:
    value = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self.value


class FixedPlayerIds:
    def __init__(self) -> None:
        self.index = 0

    def new_player_id(self) -> str:
        self.index += 1
        return f"player_r1_{self.index}"


class FixedSessionIds:
    def __init__(self) -> None:
        self.index = 0

    def new_session_id(self) -> str:
        self.index += 1
        return f"session_r1_{self.index}"


def build_service(
    state_dir: Path,
    *,
    store: JsonStateStore | None = None,
) -> tuple[MultiCaseEpisodeService, JsonStateStore]:
    actual_store = store or JsonStateStore(state_dir)
    catalog = CaseCatalog(CASE_DIR)
    service = MultiCaseEpisodeService(
        state_store=actual_store,
        case_catalog=catalog,
        campaign_rules=CampaignRuleSet.load(CAMPAIGN_RULES, catalog),
        player_id_factory=FixedPlayerIds(),
        session_id_factory=FixedSessionIds(),
        clock=FixedClock(),
    )
    return service, actual_store


def create_player(service: MultiCaseEpisodeService, name: str = "R1学徒") -> str:
    result = service.create_player(CreatePlayerInput(display_name=name))
    assert result.ok and result.player_id is not None
    for exercise in service.progression_policy.config.foundation_exercises:
        completed=service.complete_foundation_exercise(result.player_id,exercise.exercise_id,exercise.required_action_id)
        assert completed.ok
    return result.player_id


def action(tool: ToolName, arguments: dict[str, object], index: int) -> AgentAction:
    return AgentAction(
        action_id=f"r1_action_{index}",
        action_type=AgentActionType.USE_TOOL,
        dialogue="确定性R1轨迹",
        tool_call=ToolCallRequest(name=tool, arguments=arguments),
        confidence=1.0,
    )


def complete_case(
    service: MultiCaseEpisodeService,
    player_id: str,
    case_id: str,
    *,
    diagnosis_id: str | None = None,
    treatment_id: str | None = None,
):
    started = service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id=case_id)
    )
    assert started.ok and started.session_id is not None
    session_id = started.session_id
    case = service.case_catalog.get(case_id)
    assert case is not None
    index = 0
    for investigation in case.investigations:
        index += 1
        result = service.submit_action(
            SubmitActionInput(
                player_id=player_id,
                case_id=case_id,
                session_id=session_id,
                action=action(
                    TOOLS[investigation.action_type],
                    {"investigation_id": investigation.investigation_id},
                    index,
                ),
            )
        )
        assert result.ok, result
    session = service.state_store.load_case_session(session_id)
    correct_diagnosis, correct_treatment = TRACES[case_id]
    index += 1
    diagnosed = service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case_id,
            session_id=session_id,
            action=action(
                ToolName.SUBMIT_DIAGNOSIS,
                {
                    "diagnosis_id": diagnosis_id or correct_diagnosis,
                    "evidence_clue_ids": sorted(session.discovered_clue_ids),
                },
                index,
            ),
        )
    )
    assert diagnosed.ok
    index += 1
    result = service.submit_action(
        SubmitActionInput(
            player_id=player_id,
            case_id=case_id,
            session_id=session_id,
            action=action(
                ToolName.EXECUTE_TREATMENT,
                {"treatment_id": treatment_id or correct_treatment},
                index,
            ),
        )
    )
    return session_id, result
