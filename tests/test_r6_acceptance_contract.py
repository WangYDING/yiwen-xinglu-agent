from pathlib import Path
from xuanyi_npc.domain.product_acceptance import ProductAcceptanceV1


RESOURCE = Path(__file__).parents[1] / "src/xuanyi_npc/resources/acceptance/product_acceptance_v1.json"


def test_r6_final_acceptance_contract_is_strict_and_complete():
    contract = ProductAcceptanceV1.model_validate_json(RESOURCE.read_text(encoding="utf-8"))
    assert len(contract.gates) == 5 and len(contract.routes) == 8
    assert contract.determinism.runs == 2 and contract.determinism.hashes_must_match
    assert contract.status_on_offline_pass == "r6_in_progress"


def test_r6_contract_freezes_external_boundaries_and_truthful_claims():
    contract = ProductAcceptanceV1.model_validate_json(RESOURCE.read_text(encoding="utf-8"))
    assert {"deepseek_models", "deepseek_chat", "external_network", "contact_playtester", "push", "release"}.issubset(contract.prohibited_external_actions)
    assert contract.real_pilot_budget_cny == 0.05
    assert len(contract.forbidden_claim_conflations) >= 3


def test_r6_contract_freezes_all_severe_playtest_release_blockers():
    contract = ProductAcceptanceV1.model_validate_json(RESOURCE.read_text(encoding="utf-8"))
    assert set(contract.release_blockers) == {
        "cannot_start", "operation_not_understood", "save_lost", "answer_leak",
        "mentor_acts_for_player", "growth_explanation_wrong", "cross_player_leak",
        "exam_inheritance_state_wrong",
    }
