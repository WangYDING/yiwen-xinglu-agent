"""Fixture-aware offline agents used only to prove the V2.1 execution chain."""
from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace

from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import (
    AgentRuntimeKind, GameNPCDecision, GameNPCDecisionProposal, NPCCapability,
    PlayerContributionEvaluation, SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_planning import GoalCondition, GoalConditionType, PlanStepIntent
from xuanyi_npc.domain.planning_contract import (
    GameNPCTurnProposal, GoalUpdateKind, GoalUpdateProposal, PlanDraft,
    PlanStepDraft, PlanUpdateKind, PlanUpdateProposal,
)
from xuanyi_npc.agents.deepseek import DeepSeekRequestBudgetGuard


class OfflineBudgetAdapter:
    """No-network adapter surface; agent substitutes never call complete()."""
    def __init__(self, cap: float) -> None:
        self.request_budget=DeepSeekRequestBudgetGuard(Decimal(str(cap)))
        self.config=SimpleNamespace(model="offline-pipeline-substitute")
    def complete(self, request):
        raise AssertionError("offline preflight attempted a provider call")


class OfflineOracleActionAgent:
    runtime_kind=AgentRuntimeKind.TEST_DOUBLE
    architecture_id="A0-offline-substitute"

    def __init__(self, case_root: Path, adapter) -> None:
        self.adapter=adapter; self.case_root=case_root; self._last_input=None; self._last_proposal=None

    def _oracle(self, case_id):
        raw=json.loads((self.case_root/f"{case_id}.json").read_text(encoding="utf-8"))
        diagnosis=raw["valid_diagnosis_ids"][0]
        treatment=next(key for key,value in raw["treatments"].items() if value["outcome"]=="resolved")
        return diagnosis,treatment

    def _proposal(self,value):
        self._last_input=value; obs=value.case_observation; diagnosis,treatment=self._oracle(obs.case_id)
        if obs.available_investigations:
            option=obs.available_investigations[0]; tool=INVESTIGATION_TOOL_BY_ACTION[option.action_type]
            capability=NPCCapability.USE_TOOL; arguments={"investigation_id":option.investigation_id}
        elif obs.submitted_diagnosis_id is None:
            tool=ToolName.SUBMIT_DIAGNOSIS; capability=NPCCapability.PROPOSE_DIAGNOSIS
            arguments={"diagnosis_id":diagnosis,"evidence_clue_ids":[c.clue_id for c in obs.discovered_clues]}
        else:
            tool=ToolName.EXECUTE_TREATMENT; capability=NPCCapability.PROPOSE_TREATMENT
            arguments={"treatment_id":treatment}
        evaluation=None
        if value.player_contribution is not None:
            evaluation=PlayerContributionEvaluation(contribution_id=value.player_contribution.contribution_id,
                disposition=SuggestionDisposition.ACCEPT,reason_code="offline_chain_probe",
                explanation="离线替身仅验证公开执行链。")
        self._last_proposal=GameNPCDecisionProposal(contribution_evaluation=evaluation,capability=capability,
            action=AgentAction(action_id=f"npc_{value.turn_id}",action_type=AgentActionType.USE_TOOL,
                dialogue="按公开动作空间执行离线链路验证。",tool_call=ToolCallRequest(name=tool,arguments=arguments),confidence=1.0),
            explanation="该选择来自冻结 fixture oracle，仅用于管线预检。")
        return self._last_proposal

    def decide(self,value):
        proposal=self._proposal(value)
        return GameNPCDecision(decision_id=f"decision_{value.turn_id}",turn_id=value.turn_id,
            proposal=proposal,llm_attempts=1,used_fallback=False)

    def repair_action_contract(self,value,prior,feedback): return prior
    def action_contract_fallback(self,prior): return prior
    def last_planning_execution(self): return None
    def last_planning_proposal(self): return self._last_proposal
    def last_planning_input(self): return self._last_input
    def last_action_contract_attempts(self): return ()


class OfflineOraclePlanningAgent(OfflineOracleActionAgent):
    architecture_id="A1-offline-substitute"

    def propose_turn(self,value):
        proposal=self._proposal(value); call=proposal.action.tool_call; tool=call.name
        if tool is ToolName.SUBMIT_DIAGNOSIS:
            intent=PlanStepIntent.PROPOSE_DIAGNOSIS; target=call.arguments["diagnosis_id"]
            signal=GoalCondition(condition_type=GoalConditionType.DIAGNOSIS_SUBMITTED)
        elif tool is ToolName.EXECUTE_TREATMENT:
            intent=PlanStepIntent.PROPOSE_TREATMENT; target=call.arguments["treatment_id"]
            signal=GoalCondition(condition_type=GoalConditionType.CASE_COMPLETED)
        else:
            intent=PlanStepIntent.INVESTIGATE; target=call.arguments["investigation_id"]
            signal=GoalCondition(condition_type=GoalConditionType.INVESTIGATION_COMPLETED,reference_id=target)
        update=PlanUpdateKind.REVISE if value.current_plan is not None else PlanUpdateKind.CREATE
        turn=GameNPCTurnProposal(
            goal_update=GoalUpdateProposal(update=GoalUpdateKind.KEEP,public_rationale="保持当前公开目标。"),
            plan_update=PlanUpdateProposal(update=update,draft=PlanDraft(steps=(
                PlanStepDraft(intent=intent,capability=proposal.capability,suggested_tool=tool,
                    public_target_id=target,public_summary="执行当前公开动作。",completion_signal=signal),
                PlanStepDraft(intent=PlanStepIntent.DISCUSS_WITH_PLAYER,capability=NPCCapability.EXPLAIN,
                    public_summary="核对公开结果。",completion_signal=GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT,threshold=1)),
            )),public_rationale="离线替身生成最短合法计划。"),decision=proposal)
        self._last_proposal=turn
        return turn
