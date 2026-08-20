from tests.test_m3_cooperative_web_memory import render_memory_page


def test_web_shows_learning_notice_only_when_memory_was_persisted(tmp_path):
    page = render_memory_page(
        tmp_path,
        reflection_triggered="1",
        reflection_trigger_type="episode_completed",
        reflection_trigger_id="rtr_public",
        reflection_status="completed",
        reflection_proposal_status="valid",
        reflection_candidate_ids="rmc_candidate",
        reflection_write_outcomes="write_new",
        reflection_written_memory_ids="memory_written",
        reflection_provenance_ref_ids="ev_outcome,ev_assessment",
        public_consolidation_summary="NPC 从本次经历中沉淀了一条可复用经验。",
    )
    assert "经验沉淀" in page
    assert "NPC 从本次经历中沉淀了一条可复用经验。" in page


def test_web_does_not_claim_learning_when_all_candidates_rejected(tmp_path):
    page = render_memory_page(
        tmp_path,
        reflection_triggered="1",
        reflection_trigger_type="goal_completed",
        reflection_status="completed",
        reflection_proposal_status="valid",
        reflection_candidate_ids="rmc_rejected",
        reflection_write_outcomes="reject_weak_evidence",
        reflection_rejection_reasons="low_reflection_confidence",
        reflection_written_memory_ids="",
        public_consolidation_summary="这段学习成功提示不应显示。",
    )
    assert "经验沉淀" not in page
    assert "这段学习成功提示不应显示。" not in page


def test_reflection_debug_is_folded_and_excludes_private_material(tmp_path):
    page = render_memory_page(
        tmp_path,
        reflection_triggered="1",
        reflection_trigger_type="plan_abandoned",
        reflection_trigger_id="rtr_debug",
        reflection_status="completed",
        reflection_proposal_status="valid",
        reflection_candidate_ids="rmc_debug",
        reflection_write_outcomes="reject_conflict",
        reflection_rejection_reasons="active_memory_conflict",
        reflection_provenance_ref_ids="ev_plan,ev_plan_evaluation",
    )
    assert "reflection trigger type：plan_abandoned" in page
    assert "candidate IDs：rmc_debug" in page
    assert "provenance refs：ev_plan,ev_plan_evaluation" in page
    assert "<details><summary>开发信息</summary>" in page
    assert "<details open" not in page
    forbidden = ("chain-of-thought", "raw prompt", "hidden facts", "raw DB record")
    assert not any(item.lower() in page.lower() for item in forbidden)
