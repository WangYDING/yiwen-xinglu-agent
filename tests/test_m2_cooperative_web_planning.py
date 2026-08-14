from pathlib import Path
from urllib.parse import urlencode

import pytest

from xuanyi_npc.domain.cooperation import NPCCapability
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    AgentPlan,
    AgentPlanStatus,
    CooperativeAgentState,
    GoalCondition,
    GoalConditionType,
    PlanEvaluation,
    PlanEvaluationOutcome,
    PlanEvaluationReason,
    PlanStep,
    PlanStepIntent,
    PlanStepStatus,
)
from tests.test_m1_cooperative_web import serve, stop
from tests.test_r5_clinic_http import request
from tests.test_r5_clinic_service import build_clinic


def planning_state(player_id, opened, outcome: PlanEvaluationOutcome):
    episode = AgentGoalState(
        goal_id="episode_web", goal_type=AgentGoalType.RESOLVE_CASE,
        public_description="与玩家协作完成当前病例。", status=AgentGoalStatus.ACTIVE,
        priority=100, completion_condition=GoalCondition(condition_type=GoalConditionType.CASE_COMPLETED),
        created_turn_id="turn_0", updated_turn_id="turn_1",
    )
    goal_status = AgentGoalStatus.COMPLETED if outcome is PlanEvaluationOutcome.COMPLETE_GOAL else AgentGoalStatus.ACTIVE
    goal = AgentGoalState(
        goal_id="goal_web", goal_type=AgentGoalType.GATHER_EVIDENCE,
        public_description="确认灶火异常的公开来源。", status=goal_status,
        priority=80, completion_condition=GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=3),
        source_contribution_id="turn_1", created_turn_id="turn_0", updated_turn_id="turn_1",
    )
    if outcome is PlanEvaluationOutcome.KEEP_PLAN:
        plan_status = AgentPlanStatus.ACTIVE
        statuses = (PlanStepStatus.COMPLETED, PlanStepStatus.ACTIVE, PlanStepStatus.PENDING)
        current = 1
        reason = PlanEvaluationReason.EXPECTED_EVIDENCE_FOUND
        summary = "刚获得的证据与预期一致，下一步仍然有效。"
    elif outcome is PlanEvaluationOutcome.REVISE_PLAN:
        plan_status = AgentPlanStatus.NEEDS_REVISION
        statuses = (PlanStepStatus.COMPLETED, PlanStepStatus.OBSOLETE, PlanStepStatus.OBSOLETE)
        current = 0
        reason = PlanEvaluationReason.NEW_EVIDENCE_CHANGES_DIRECTION
        summary = "新证据使原来的下一步不再合适。"
    else:
        plan_status = AgentPlanStatus.COMPLETED
        statuses = (PlanStepStatus.COMPLETED, PlanStepStatus.OBSOLETE, PlanStepStatus.OBSOLETE)
        current = 0
        reason = PlanEvaluationReason.GOAL_COMPLETED
        summary = "确定性完成条件已经满足。"
    summaries = ("观察患者离开灶边后的变化", "检查灶台附近异常痕迹", "与玩家复核辨证条件")
    steps = tuple(
        PlanStep(
            step_id=f"step_web_{index}", ordinal=index,
            intent=PlanStepIntent.DISCUSS_WITH_PLAYER,
            capability=NPCCapability.EXPLAIN,
            public_summary=text,
            completion_signal=GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=index + 1),
            status=statuses[index],
        )
        for index, text in enumerate(summaries)
    )
    plan = AgentPlan(
        plan_id="plan_web", goal_id=goal.goal_id, status=plan_status,
        steps=steps, current_step_index=current, based_on_observation_revision=1,
        source_contribution_id="turn_1", created_turn_id="turn_0", updated_turn_id="turn_1", revision=2,
    )
    evaluation = PlanEvaluation(
        evaluation_id="evaluation_web", plan_id=plan.plan_id, outcome=outcome,
        reason_code=reason, observation_revision_before=0, observation_revision_after=1,
        completed_step_ids=(steps[0].step_id,),
        obsolete_step_ids=tuple(step.step_id for step in steps if step.status is PlanStepStatus.OBSOLETE),
        next_goal_status=goal.status, public_summary=summary, evaluated_turn_id="turn_1",
    )
    return CooperativeAgentState(
        player_id=player_id, case_id=opened.case_id, session_id=opened.session_id,
        episode_goal=episode, current_goal=goal, current_plan=plan,
        last_plan_evaluation=evaluation, revision=1, updated_turn_id="turn_1",
    )


def rendered_page(tmp_path: Path, outcome: PlanEvaluationOutcome):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("规划展示玩家").player_summary.player_id
    opened = clinic.start_case(player, "old_paper_umbrella")
    state = planning_state(player, opened, outcome)
    clinic.store.save_cooperative_agent_state(state, expected_revision=0)
    server, thread = serve(clinic)
    query = urlencode({
        "player_id": player, "case_id": opened.case_id, "session_id": opened.session_id,
        "npc_reply": "我会先核对公开证据。", "suggestion_disposition": "partial_accept",
        "suggestion_explanation": "接受可验证部分。", "npc_tool_public": "观察患者",
        "npc_rationale": "依据公开病例状态。", "environment_feedback": "发现一条公开线索。",
        "runtime_kind": "test_double", "debug_tool_name": "observe_patient",
        "goal_changed": "1", "plan_changed": "1", "contribution_id": "turn_1",
    })
    try:
        status, _, page = request(server.server_address[1], "GET", f"/cases?{query}")
    finally:
        stop(server, thread)
    assert status == 200
    return page, clinic, opened


def test_cooperative_page_shows_public_goal_plan_active_step_and_m1_result(tmp_path: Path) -> None:
    page, clinic, opened = rendered_page(tmp_path, PlanEvaluationOutcome.KEEP_PLAN)

    assert "NPC 当前思路" in page
    assert "确认灶火异常的公开来源" in page
    assert "收集证据" in page and "进行中" in page
    assert page.count('class="plan-step') == 3
    assert "✓ 已完成" in page and "→ 当前" in page and "○ 待进行" in page
    assert "NPC 当前准备：</strong>检查灶台附近异常痕迹" in page
    assert "NPC 根据你的建议调整了调查计划" in page
    assert "建议评价" in page and "NPC 回应" in page
    assert "采取行动" in page and "行动依据" in page and "环境反馈" in page

    case = clinic.base_catalog.get(opened.case_id)
    session = clinic.store.load_case_session(opened.session_id)
    hidden_descriptions = [item.description for clue_id, item in case.clues.items() if clue_id not in session.discovered_clue_ids]
    assert all(description not in page for description in hidden_descriptions)
    assert "raw prompt" not in page.lower() and "chain-of-thought" not in page.lower()


@pytest.mark.parametrize(
    ("outcome", "visible"),
    [
        (PlanEvaluationOutcome.KEEP_PLAN, "继续计划"),
        (PlanEvaluationOutcome.REVISE_PLAN, "计划调整"),
        (PlanEvaluationOutcome.COMPLETE_GOAL, "当前目标已完成"),
    ],
)
def test_plan_evaluation_has_player_friendly_status(tmp_path: Path, outcome, visible) -> None:
    page, _, _ = rendered_page(tmp_path, outcome)
    assert visible in page
    assert "new_evidence_changes_direction" not in page.split("<details>", 1)[0]


def test_obsolete_step_is_not_presented_as_current_and_debug_is_folded(tmp_path: Path) -> None:
    page, _, _ = rendered_page(tmp_path, PlanEvaluationOutcome.REVISE_PLAN)

    assert "↷ 已调整：</strong>检查灶台附近异常痕迹" in page
    assert "NPC 当前准备" not in page
    assert "<details><summary>开发信息</summary>" in page
    assert "goal ID：goal_web" in page
    assert "plan revision：2" in page
    assert "evaluation reason：new_evidence_changes_direction" in page
    assert "runtime：test_double" in page
    assert "<details open" not in page
