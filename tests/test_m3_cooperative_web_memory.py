from pathlib import Path
from urllib.parse import urlencode

from tests.test_m1_cooperative_web import serve, stop
from tests.test_m2_cooperative_web_planning import planning_state
from tests.test_r5_clinic_http import request
from tests.test_r5_clinic_service import build_clinic
from xuanyi_npc.domain.cooperative_planning import PlanEvaluationOutcome


def render_memory_page(tmp_path: Path, **memory_query):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("记忆展示玩家").player_summary.player_id
    opened = clinic.start_case(player, "old_paper_umbrella")
    clinic.store.save_cooperative_agent_state(
        planning_state(player, opened, PlanEvaluationOutcome.KEEP_PLAN),
        expected_revision=0,
    )
    query = {
        "player_id": player,
        "case_id": opened.case_id,
        "session_id": opened.session_id,
        "npc_reply": "我会先核对公开证据。",
        "suggestion_disposition": "partial_accept",
        "suggestion_explanation": "接受可验证部分。",
        "npc_tool_public": "观察患者",
        "npc_rationale": "依据公开病例状态。",
        "environment_feedback": "发现一条公开线索。",
        "runtime_kind": "test_double",
        "debug_tool_name": "observe_patient",
        "goal_changed": "1",
        "plan_changed": "1",
        "contribution_id": "turn_1",
    }
    query.update(memory_query)
    server, thread = serve(clinic)
    try:
        status, _, page = request(server.server_address[1], "GET", f"/cases?{urlencode(query)}")
    finally:
        stop(server, thread)
    assert status == 200
    return page


def test_web_shows_public_memory_effect_only_for_accepted_influence(tmp_path: Path) -> None:
    page = render_memory_page(
        tmp_path,
        memory_public_effect="NPC 参考了此前类似经历，并调整了当前调查顺序。",
        memory_accepted_used_ids="memory_plan",
        memory_declared_used_ids="memory_plan",
        memory_selected_ids="memory_plan",
        memory_candidate_ids="memory_plan,memory_other",
        memory_selected_count="1",
        memory_retrieval_status="success",
        memory_retrieval_id="retrieval_web",
        memory_attribution_status="accepted",
        memory_influence_types="plan_priority",
    )

    assert "过往经验" in page
    assert "NPC 参考了此前类似经历，并调整了当前调查顺序。" in page
    assert "NPC 根据过往经验调整了调查计划" in page


def test_web_does_not_claim_memory_for_retrieved_but_unused(tmp_path: Path) -> None:
    page = render_memory_page(
        tmp_path,
        memory_public_effect="这段文字不应给普通玩家展示。",
        memory_accepted_used_ids="",
        memory_declared_used_ids="",
        memory_selected_ids="memory_unused",
        memory_candidate_ids="memory_unused",
        memory_selected_count="1",
        memory_retrieval_status="success",
        memory_attribution_status="rejected",
    )

    assert "过往经验" not in page
    assert "这段文字不应给普通玩家展示。" not in page
    assert "NPC 根据过往经验调整了调查计划" not in page


def test_web_failed_safe_memory_debug_is_folded_and_page_runs(tmp_path: Path) -> None:
    page = render_memory_page(
        tmp_path,
        memory_retrieval_status="failed_safe",
        memory_retrieval_id="",
        memory_selected_count="0",
        memory_attribution_status="rejected",
    )

    assert "NPC 协作结果" in page
    assert "memory retrieval status：failed_safe" in page
    assert "<details><summary>开发信息</summary>" in page
    assert "<details open" not in page


def test_web_debug_shows_memory_layers_without_raw_payload_or_cot(tmp_path: Path) -> None:
    page = render_memory_page(
        tmp_path,
        memory_candidate_ids="memory_candidate",
        memory_selected_ids="memory_selected",
        memory_declared_used_ids="memory_selected",
        memory_accepted_used_ids="memory_selected",
        memory_rejected_ids="memory_rejected",
        memory_selected_count="1",
        memory_retrieval_status="success",
        memory_retrieval_id="retrieval_debug",
        memory_attribution_status="accepted",
        memory_influence_types="tool_priority",
        memory_public_effect="NPC 根据过往协作经验调整了计划。",
    )

    assert "candidate memory IDs：memory_candidate" in page
    assert "selected memory IDs：memory_selected" in page
    assert "declared used memory IDs：memory_selected" in page
    assert "accepted used memory IDs：memory_selected" in page
    assert "rejected memory IDs：memory_rejected" in page
    forbidden = ("raw SQLite", "embedding vector", "hidden payload", "raw prompt", "chain-of-thought")
    assert not any(item.lower() in page.lower() for item in forbidden)
    assert "师父已提醒" not in page
