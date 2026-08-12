from pathlib import Path

from xuanyi_npc.domain.clinic import R5AcceptanceContract
from xuanyi_npc.domain.cases import CaseSessionState
from xuanyi_npc.engine.replay import CaseEventReplayer
from tests.test_play_cli import replay_events
from tests.r1_helpers import create_player
from tests.r5_helpers import build_six_case_service, complete_case


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"


def contracts():
    value = R5AcceptanceContract.model_validate_json((ROOT / "clinic" / "r5_acceptance_v1.json").read_text(encoding="utf-8"))
    return value.advanced_cases


def test_each_advanced_case_two_gold_orders_use_same_generic_engine(tmp_path):
    for ordinal, contract in enumerate(contracts()):
        for order_index, order in enumerate(contract.gold_investigation_orders):
            service, store = build_six_case_service(tmp_path / f"{ordinal}_{order_index}")
            player = create_player(service)
            session_id, result = complete_case(service, store, player, contract, order)
            assert result.episode_result.score == 100
            assert result.episode_result.outcome.value == "resolved"
            state = store.load_case_session(session_id)
            initial = CaseSessionState(session_id=session_id, case_id=contract.case_id, player_id=player)
            assert CaseEventReplayer().replay(initial, replay_events(service.case_catalog.get(contract.case_id), state)) == state
            assert state.revision == 8


def test_advanced_cases_replay_and_player_isolation(tmp_path):
    service, store = build_six_case_service(tmp_path)
    first = create_player(service, "进阶甲")
    second = create_player(service, "进阶乙")
    contract = contracts()[0]
    session_id, _ = complete_case(service, store, first, contract)
    assert store.load_case_session(session_id).player_id == first
    assert not [item for item in store.list_case_sessions() if item.player_id == second]


def test_no_case_specific_branch_was_added_to_engine_source():
    source = (ROOT.parents[2] / "src" / "xuanyi_npc" / "engine" / "case_engine.py").read_text(encoding="utf-8")
    assert all(contract.case_id not in source for contract in contracts())


def test_historical_three_case_campaign_can_coexist_with_six_case_catalog(tmp_path):
    from xuanyi_npc.application import CampaignRuleSet, CaseCatalog
    catalog = CaseCatalog(ROOT / "cases")
    rules = CampaignRuleSet.load(ROOT / "campaign" / "cross_episode_rules_v1.json", catalog)
    assert len(rules.config.recommended_case_order) == 3
