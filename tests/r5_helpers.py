from tests.r1_helpers import FixedClock, FixedPlayerIds, FixedSessionIds, TOOLS, action
from xuanyi_npc.application import (
    CampaignRuleSet, CaseCatalog, CreatePlayerInput, MultiCaseEpisodeService,
    StartEpisodeInput, SubmitActionInput,
)
from xuanyi_npc.domain import ToolName
from xuanyi_npc.storage import JsonStateStore


def build_six_case_service(tmp_path):
    from pathlib import Path
    root = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"
    catalog = CaseCatalog(root / "cases")
    store = JsonStateStore(tmp_path)
    service = MultiCaseEpisodeService(
        state_store=store, case_catalog=catalog,
        campaign_rules=CampaignRuleSet.load(root / "campaign" / "cross_episode_rules_v2.json", catalog),
        player_id_factory=FixedPlayerIds(), session_id_factory=FixedSessionIds(), clock=FixedClock(),
    )
    return service, store


def complete_case(service, store, player_id, contract, order=None):
    case = service.case_catalog.get(contract.case_id)
    started = service.start_episode(StartEpisodeInput(player_id=player_id, case_id=case.case_id))
    investigation_ids = order or tuple(item.investigation_id for item in case.investigations)
    index = 0
    for investigation_id in investigation_ids:
        investigation = next(item for item in case.investigations if item.investigation_id == investigation_id)
        index += 1
        result = service.submit_action(SubmitActionInput(
            player_id=player_id, case_id=case.case_id, session_id=started.session_id,
            action=action(TOOLS[investigation.action_type], {"investigation_id": investigation_id}, index),
        ))
        assert result.ok, result
    session = store.load_case_session(started.session_id)
    index += 1
    assert service.submit_action(SubmitActionInput(
        player_id=player_id, case_id=case.case_id, session_id=started.session_id,
        action=action(ToolName.SUBMIT_DIAGNOSIS, {
            "diagnosis_id": contract.correct_diagnosis_id,
            "evidence_clue_ids": sorted(session.discovered_clue_ids),
        }, index),
    )).ok
    index += 1
    result = service.submit_action(SubmitActionInput(
        player_id=player_id, case_id=case.case_id, session_id=started.session_id,
        action=action(ToolName.EXECUTE_TREATMENT, {"treatment_id": contract.resolved_treatment_id}, index),
    ))
    assert result.ok
    return started.session_id, result

