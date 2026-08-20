from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime, CooperativeTurnInput
from xuanyi_npc.domain import AgentAction, AgentActionType
from xuanyi_npc.domain.cooperation import (
    GameNPCDecisionProposal,
    NPCCapability,
    PlayerContributionEvaluation,
    SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalType,
    GoalCondition,
    GoalConditionType,
)
from xuanyi_npc.domain.planning_contract import (
    GameNPCTurnProposal,
    GoalDraft,
    GoalUpdateKind,
    GoalUpdateProposal,
    PlanUpdateKind,
    PlanUpdateProposal,
)
from xuanyi_npc.domain.reflection import ReflectionTriggerType
from xuanyi_npc.domain.reflection_lifecycle import (
    ReflectionLifecycleResult,
    ReflectionLifecycleStatus,
    ReflectionProposalStatus,
)

from .test_m2_cooperative_runtime_planning import (
    PlanningAgent,
    contribution,
    create_plan_proposal,
    opened_case,
)


class CapturingReflectionService:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def process(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("injected reflection failure")
        trigger = kwargs["trigger"]
        return ReflectionLifecycleResult(
            trigger_id=trigger.trigger_id,
            trigger_type=trigger.trigger_type,
            status=ReflectionLifecycleStatus.COMPLETED,
            proposal_status=ReflectionProposalStatus.VALID,
            reflection_attempt_count=1,
        )


def goal_completed_proposal(value):
    base = create_plan_proposal()(value)
    investigation_id = value.case_observation.available_investigations[0].investigation_id
    return base.model_copy(
        update={
            "goal_update": GoalUpdateProposal(
                update=GoalUpdateKind.REPLACE,
                draft=GoalDraft(
                    goal_type=AgentGoalType.GATHER_EVIDENCE,
                    public_description="完成一项公开调查并检查结果。",
                    priority=80,
                    completion_condition=GoalCondition(
                        condition_type=GoalConditionType.INVESTIGATION_COMPLETED,
                        reference_id=investigation_id,
                    ),
                ),
                public_rationale="建立可由本轮公开调查确定完成的目标。",
            )
        }
    )


def abandon_plan_proposal(value):
    return GameNPCTurnProposal(
        goal_update=GoalUpdateProposal(
            update=GoalUpdateKind.KEEP,
            public_rationale="保留当前公开目标。",
        ),
        plan_update=PlanUpdateProposal(
            update=PlanUpdateKind.ABANDON,
            public_rationale="当前计划不再适合，停止后重新讨论。",
        ),
        decision=GameNPCDecisionProposal(
            contribution_evaluation=PlayerContributionEvaluation(
                contribution_id=value.player_contribution.contribution_id,
                disposition=SuggestionDisposition.PROPOSE_ALTERNATIVE,
                reason_code="plan_abandoned_for_public_reason",
                explanation="当前计划需要停止并重新讨论。",
            ),
            capability=NPCCapability.EXPLAIN,
            action=AgentAction(
                action_id=f"npc_{value.turn_id}",
                action_type=AgentActionType.RESPOND,
                dialogue="我先停止当前计划，再与你重新核对方向。",
                confidence=0.8,
            ),
            explanation="本轮不执行工具。",
        ),
    )


def test_goal_completed_automatically_triggers_once_after_world_commit(tmp_path):
    service, player_id, opened = opened_case(tmp_path)
    reflection = CapturingReflectionService()
    result = CooperativeRuntime(
        service=service,
        agent=PlanningAgent([goal_completed_proposal]),
        reflection_service=reflection,
    ).handle(
        CooperativeTurnInput(contribution=contribution(player_id, opened.session_id))
    )
    assert result.reflection_triggered is True
    assert result.reflection_trigger_type is ReflectionTriggerType.GOAL_COMPLETED
    assert len(reflection.calls) == 1
    assert service.state_store.load_case_session(opened.session_id).revision == 1


def test_plan_abandoned_triggers_but_ordinary_turn_does_not(tmp_path):
    service, player_id, opened = opened_case(tmp_path)
    reflection = CapturingReflectionService()
    first = CooperativeRuntime(
        service=service,
        agent=PlanningAgent([create_plan_proposal()]),
        reflection_service=reflection,
    ).handle(
        CooperativeTurnInput(contribution=contribution(player_id, opened.session_id))
    )
    assert first.reflection_triggered is False
    assert reflection.calls == []

    second = CooperativeRuntime(
        service=service,
        agent=PlanningAgent([abandon_plan_proposal]),
        reflection_service=reflection,
    ).handle(
        CooperativeTurnInput(
            contribution=contribution(
                player_id, opened.session_id, "turn_abandon", "建议停止当前计划。"
            )
        )
    )
    assert second.reflection_trigger_type is ReflectionTriggerType.PLAN_ABANDONED
    assert len(reflection.calls) == 1


def test_reflection_failure_does_not_rollback_world_or_agent_state(tmp_path):
    service, player_id, opened = opened_case(tmp_path)
    result = CooperativeRuntime(
        service=service,
        agent=PlanningAgent([goal_completed_proposal]),
        reflection_service=CapturingReflectionService(fail=True),
    ).handle(
        CooperativeTurnInput(contribution=contribution(player_id, opened.session_id))
    )
    assert result.reflection_status is ReflectionLifecycleStatus.FAILED_SAFE
    assert service.state_store.load_case_session(opened.session_id).revision == 1
    assert service.state_store.load_cooperative_agent_state(opened.session_id).revision == 1
