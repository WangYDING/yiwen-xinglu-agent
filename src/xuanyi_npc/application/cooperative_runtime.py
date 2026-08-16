"""One-action cooperative runtime with deterministic M2 Goal/Plan lifecycle."""

from typing import Protocol

from pydantic import ConfigDict

from xuanyi_npc.agents.game_npc import GameNPCAgentInput, GameNPCAgentInterface
from xuanyi_npc.application.action_contract import (
    PublicActionContractError,
    PublicActionContractValidator,
    build_safe_action_feedback,
)
from xuanyi_npc.application.goal_plan_policy import GoalPlanPolicy
from xuanyi_npc.application.multicase import ResumeEpisodeInput, SubmitActionInput
from xuanyi_npc.application.plan_evaluator import DeterministicPlanEvaluator
from xuanyi_npc.domain import AgentAction, AgentActionType
from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.domain.cooperation import (
    AuthorityMode,
    AgentRuntimeKind,
    CooperativeTurnResult,
    CooperativeTurnStatus,
    GameNPCDecision,
    GameNPCDecisionProposal,
    NPCCapability,
    PendingActionConfirmation,
    PlayerContribution,
    PlayerContributionType,
    PlayerContributionEvaluation,
    SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalState,
    AgentGoalStatus,
    AgentGoalType,
    AgentPlan,
    AgentPlanStatus,
    CooperativeAgentState,
    GoalBlockedReason,
    GoalCondition,
    GoalConditionType,
    PlanEvaluation,
    PlanEvaluationOutcome,
    PlanEvaluationReason,
    PlanStep,
    PlanStepStatus,
)
from xuanyi_npc.domain.cooperative_memory import (
    MemoryRetrievalStatus,
    MemoryUsageAttributionStatus,
    MemoryUsageTrace,
)
from xuanyi_npc.domain.planning_contract import GoalUpdateKind, PlanUpdateKind
from xuanyi_npc.storage import StateNotFoundError, StorageError

from .npc_authority import NPCAuthorityPolicy


class CooperativeRuntimeError(ValueError):
    pass


class CooperativeService(Protocol):
    state_store: object
    context_filter: object

    def resume_episode(self, request): ...
    def submit_action_with_receipt(self, request): ...


class CooperativeMemoryService(Protocol):
    def retrieve(self, **kwargs): ...


class CooperativeTurnInput(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contribution: PlayerContribution
    pending_action: PendingActionConfirmation | None = None


class CooperativeRuntime:
    def __init__(
        self,
        *,
        service: CooperativeService,
        agent: GameNPCAgentInterface,
        authority_policy: NPCAuthorityPolicy | None = None,
        action_validator: PublicActionContractValidator | None = None,
        goal_plan_policy: GoalPlanPolicy | None = None,
        plan_evaluator: DeterministicPlanEvaluator | None = None,
        memory_service: CooperativeMemoryService | None = None,
    ) -> None:
        self.service = service
        self.agent = agent
        self.authority_policy = authority_policy or NPCAuthorityPolicy()
        self.action_validator = action_validator or PublicActionContractValidator()
        self.goal_plan_policy = goal_plan_policy or GoalPlanPolicy()
        self.plan_evaluator = plan_evaluator or DeterministicPlanEvaluator()
        self.memory_service = memory_service

    def handle(self, request: CooperativeTurnInput) -> CooperativeTurnResult:
        contribution = request.contribution
        public = self._resume(contribution)
        observation = public.observation
        session = self.service.state_store.load_case_session(contribution.session_id)
        player = self.service.state_store.load_player(contribution.player_id)
        pending = self._validated_pending(request.pending_action, contribution, session.revision)
        state, expected_revision = self._load_or_initialize(contribution, observation)
        state = self._mark_invalid_plan(state, observation, contribution.contribution_id)
        memory_context, memory_trace = self._retrieve_memory_context(
            contribution=contribution,
            observation=observation,
            state=state,
        )
        if (
            state.current_goal.status is AgentGoalStatus.ACTIVE
            and self.plan_evaluator.condition_met(state.current_goal.completion_condition, observation)
        ):
            state = self._complete_satisfied_goal(state, observation, contribution.contribution_id)
            state = self._advance_state_revision(state, contribution.contribution_id, expected_revision)
            self._save_state(state, expected_revision)
            decision = self._completion_decision(contribution, state.current_goal.goal_id)
            return self._result(
                state, decision, goal_changed=True, plan_changed=state.current_plan is not None,
                status=CooperativeTurnStatus.RESPONDED,
                authority_mode=AuthorityMode.AUTONOMOUS,
                public_rationale="当前目标的确定性完成条件已经满足；本轮不启动下一目标。",
                memory_usage_trace=memory_trace,
            )
        agent_input = GameNPCAgentInput(
            turn_id=contribution.contribution_id,
            step_index=len(session.action_history) + 1,
            player_view=self.service.context_filter.player_view(player),
            case_observation=observation,
            player_contribution=contribution,
            authority_view=self.authority_policy.view(),
            current_goal=state.current_goal,
            current_plan=state.current_plan,
            last_plan_evaluation=state.last_plan_evaluation,
            last_environment_feedback=(
                state.last_plan_evaluation.public_summary
                if state.last_plan_evaluation is not None else None
            ),
            memory_context=memory_context,
        )

        planning_supported = callable(getattr(self.agent, "propose_turn", None))
        goal_changed = False
        plan_changed = False
        turn_proposal = None
        if planning_supported:
            turn_proposal = self.agent.propose_turn(agent_input)
            self.goal_plan_policy.validate(
                turn_proposal,
                current_goal=state.current_goal,
                current_plan=state.current_plan,
                observation=observation,
                authority_view=agent_input.authority_view,
            )
            state, goal_changed, plan_changed = self._apply_proposal(
                state, turn_proposal, contribution.contribution_id, observation.session_revision,
                contribution.contribution_id,
            )
            memory_trace = self._accepted_memory_trace(
                base=memory_trace,
                proposal=turn_proposal,
                goal_changed=goal_changed,
                plan_changed=plan_changed,
            )
            decision = GameNPCDecision(
                decision_id=f"decision_{contribution.contribution_id}",
                turn_id=contribution.contribution_id,
                proposal=turn_proposal.decision,
                llm_attempts=1,
                used_fallback=False,
            )
            decision = self._associate_decision(decision, state)
            if not self._action_matches_plan(decision, state):
                state = self._advance_state_revision(state, contribution.contribution_id, expected_revision)
                self._save_state(state, expected_revision)
                return self._result(
                    state, decision, goal_changed=goal_changed, plan_changed=plan_changed,
                    status=CooperativeTurnStatus.ACTION_REJECTED,
                    authority_mode=AuthorityMode.FORBIDDEN,
                    memory_usage_trace=self._reject_decision_memory_trace(memory_trace),
                    error_code="action_outside_active_plan",
                    public_rationale="本轮行动与当前计划步骤不一致，未执行。",
                )
        else:
            # M1/manual test doubles remain a compatibility baseline. The M2 state is
            # still initialized and persisted, but no planning state is fabricated.
            decision = self.agent.decide(agent_input)

        decision = self._resolve_contract(agent_input, decision, observation)
        if turn_proposal is not None:
            memory_trace = self._finalize_decision_memory_trace(
                trace=memory_trace,
                proposal=turn_proposal,
                decision=decision,
            )
        action = decision.proposal.action
        selected_tool = action.tool_call.name if action.tool_call is not None else None
        selected_public_target = self._public_target(action, observation)

        if action.action_type is AgentActionType.RESPOND:
            state = self._advance_state_revision(state, contribution.contribution_id, expected_revision)
            self._save_state(state, expected_revision)
            return self._result(
                state, decision, goal_changed=goal_changed, plan_changed=plan_changed,
                status=CooperativeTurnStatus.RESPONDED,
                authority_mode=AuthorityMode.AUTONOMOUS,
                selected_tool=selected_tool,
                selected_public_target=selected_public_target,
                memory_usage_trace=memory_trace,
            )

        confirmed_id = None
        authority_decision_id = None
        if pending is not None and pending.action.tool_call == action.tool_call:
            confirmed_id = pending.decision_id
            authority_decision_id = pending.decision_id
        authority = self.authority_policy.evaluate(
            action,
            confirmed_decision_id=confirmed_id,
            decision_id=authority_decision_id,
        )
        if authority.mode in {AuthorityMode.PROPOSAL_ONLY, AuthorityMode.CONFIRMATION_REQUIRED}:
            pending_action = PendingActionConfirmation(
                confirmation_id=f"confirm_{decision.decision_id}",
                decision_id=decision.decision_id,
                player_id=contribution.player_id,
                case_id=contribution.case_id,
                session_id=contribution.session_id,
                action=action,
                authority_mode=authority.mode,
                public_rationale=decision.proposal.explanation,
                case_revision=session.revision,
            )
            state = self._advance_state_revision(state, contribution.contribution_id, expected_revision)
            self._save_state(state, expected_revision)
            status = (
                CooperativeTurnStatus.PROPOSAL_PENDING
                if authority.mode is AuthorityMode.PROPOSAL_ONLY
                else CooperativeTurnStatus.CONFIRMATION_REQUIRED
            )
            return self._result(
                state, decision, goal_changed=goal_changed, plan_changed=plan_changed,
                status=status, authority_mode=authority.mode,
                selected_tool=selected_tool, selected_public_target=selected_public_target,
                pending_action=pending_action,
                memory_usage_trace=memory_trace,
            )
        if authority.mode is AuthorityMode.FORBIDDEN:
            state = self._advance_state_revision(state, contribution.contribution_id, expected_revision)
            self._save_state(state, expected_revision)
            return self._result(
                state, decision, goal_changed=goal_changed, plan_changed=plan_changed,
                status=CooperativeTurnStatus.ACTION_REJECTED,
                authority_mode=authority.mode, error_code=authority.reason_code,
                selected_tool=selected_tool, selected_public_target=selected_public_target,
                memory_usage_trace=memory_trace,
            )

        receipt = self.service.submit_action_with_receipt(SubmitActionInput(
            player_id=contribution.player_id,
            case_id=contribution.case_id,
            session_id=contribution.session_id,
            action=action,
        ))
        result = receipt.result
        if not result.ok:
            if state.current_plan is not None and planning_supported:
                transition = self.plan_evaluator.evaluate(
                    pre_observation=observation,
                    post_observation=observation,
                    goal=state.current_goal,
                    plan=state.current_plan,
                    executed_action=action,
                    tool_succeeded=False,
                    turn_id=contribution.contribution_id,
                    environment_message=result.message,
                    event_sequences=result.event_sequences,
                    pending_confirmation=pending,
                )
                state = state.model_copy(update={
                    "current_goal": transition.goal,
                    "current_plan": transition.plan,
                    "last_plan_evaluation": transition.evaluation,
                })
                plan_changed = True
            state = self._advance_state_revision(state, contribution.contribution_id, expected_revision)
            self._save_state(state, expected_revision)
            return self._result(
                state, decision, goal_changed=goal_changed, plan_changed=plan_changed,
                status=CooperativeTurnStatus.ACTION_REJECTED,
                authority_mode=authority.mode, environment_message=result.message,
                error_code=result.error_code, selected_tool=selected_tool,
                selected_public_target=selected_public_target,
                memory_usage_trace=memory_trace,
            )

        # The world commit is authoritative. Always reload its public projection before
        # evaluating or persisting the cooperative Agent projection.
        post_observation = self._resume(contribution).observation
        if state.current_plan is not None and planning_supported:
            transition = self.plan_evaluator.evaluate(
                pre_observation=observation,
                post_observation=post_observation,
                goal=state.current_goal,
                plan=state.current_plan,
                executed_action=action,
                tool_succeeded=True,
                turn_id=contribution.contribution_id,
                environment_message=result.message,
                event_sequences=result.event_sequences,
                pending_confirmation=pending,
            )
            state = state.model_copy(update={
                "current_goal": transition.goal,
                "current_plan": transition.plan,
                "last_plan_evaluation": transition.evaluation,
            })
            if (
                post_observation.session_status.value == "completed"
                and state.episode_goal.status is AgentGoalStatus.ACTIVE
            ):
                state = state.model_copy(update={
                    "episode_goal": state.episode_goal.model_copy(update={
                        "status": AgentGoalStatus.COMPLETED,
                        "updated_turn_id": contribution.contribution_id,
                        "revision": state.episode_goal.revision + 1,
                    })
                })
            goal_changed = goal_changed or transition.goal.status is AgentGoalStatus.COMPLETED
            plan_changed = True
        state = self._advance_state_revision(state, contribution.contribution_id, expected_revision)
        try:
            self._save_state(state, expected_revision)
            projection_error = None
        except StorageError:
            projection_error = "agent_state_projection_pending"
        return self._result(
            state, decision, goal_changed=goal_changed, plan_changed=plan_changed,
            status=CooperativeTurnStatus.ACTION_EXECUTED,
            authority_mode=authority.mode, environment_message=result.message,
            event_sequences=result.event_sequences, error_code=projection_error,
            selected_tool=selected_tool, selected_public_target=selected_public_target,
            memory_usage_trace=memory_trace,
        )

    def _retrieve_memory_context(self, *, contribution, observation, state):
        if self.memory_service is None:
            return None, MemoryUsageTrace(
                retrieval_status=MemoryRetrievalStatus.UNAVAILABLE,
                attribution_status=MemoryUsageAttributionStatus.REJECTED,
                error_code="memory_service_unavailable",
            )
        try:
            context = self.memory_service.retrieve(
                turn_id=contribution.contribution_id,
                player_id=contribution.player_id,
                current_session_id=contribution.session_id,
                observation=observation,
                current_goal=state.current_goal,
                current_plan=state.current_plan,
                player_contribution=contribution,
                last_plan_evaluation=state.last_plan_evaluation,
            )
        except Exception:
            return None, MemoryUsageTrace(
                retrieval_status=MemoryRetrievalStatus.FAILED_SAFE,
                attribution_status=MemoryUsageAttributionStatus.REJECTED,
                error_code="memory_retrieval_failed_safe",
            )
        status = (
            MemoryRetrievalStatus.EMPTY
            if context.selected_count == 0
            else MemoryRetrievalStatus.SUCCESS
        )
        return context, MemoryUsageTrace(
            retrieval_id=context.retrieval_id,
            retrieval_status=status,
            candidate_memory_ids=context.candidate_memory_ids,
            selected_memory_ids=context.selected_memory_ids,
            attribution_status=MemoryUsageAttributionStatus.REJECTED,
        )

    @staticmethod
    def _accepted_memory_trace(*, base, proposal, goal_changed, plan_changed):
        usage = getattr(proposal, "memory_usage", None)
        if usage is None or not usage.used_memory_ids:
            return base.model_copy(update={
                "attribution_status": MemoryUsageAttributionStatus.REJECTED,
            })
        accepted = []
        if usage.affected_goal and goal_changed:
            accepted.extend(usage.used_memory_ids)
        if usage.affected_plan and plan_changed:
            accepted.extend(usage.used_memory_ids)
        accepted_ids = tuple(dict.fromkeys(accepted))
        status = (
            MemoryUsageAttributionStatus.ACCEPTED
            if accepted_ids
            else MemoryUsageAttributionStatus.DECLARED_ONLY
        )
        return base.model_copy(update={
            "declared_used_memory_ids": usage.used_memory_ids,
            "accepted_used_memory_ids": accepted_ids,
            "rejected_memory_ids": tuple(
                item for item in usage.used_memory_ids if item not in accepted_ids
            ),
            "influence_types": usage.influence_types,
            "attribution_status": status,
            "goal_changed": usage.affected_goal and goal_changed,
            "plan_changed": usage.affected_plan and plan_changed,
            "decision_influenced": usage.affected_decision and bool(accepted_ids),
            "tool_priority_influenced": False,
            "communication_influenced": False,
            "public_effect_summary": usage.public_effect_summary,
        })

    @staticmethod
    def _finalize_decision_memory_trace(*, trace, proposal, decision):
        usage = getattr(proposal, "memory_usage", None)
        if usage is None or not usage.used_memory_ids:
            return trace
        accepted = list(trace.accepted_used_memory_ids)
        decision_accepts = False
        if usage.affected_decision:
            decision_accepts = decision.proposal.action == proposal.decision.action
        tool_accepts = False
        if usage.affected_tool_priority:
            action = decision.proposal.action
            tool_accepts = (
                decision.proposal.action == proposal.decision.action
                and action.action_type is AgentActionType.USE_TOOL
                and action.tool_call is not None
            )
        communication_accepts = False
        if usage.affected_communication:
            communication_accepts = (
                decision.proposal.action == proposal.decision.action
                and decision.proposal.capability == proposal.decision.capability
            )
        if decision_accepts or tool_accepts or communication_accepts:
            accepted.extend(usage.used_memory_ids)
        accepted_ids = tuple(dict.fromkeys(accepted))
        status = (
            MemoryUsageAttributionStatus.ACCEPTED
            if accepted_ids
            else MemoryUsageAttributionStatus.DECLARED_ONLY
        )
        return trace.model_copy(update={
            "accepted_used_memory_ids": accepted_ids,
            "rejected_memory_ids": tuple(
                item for item in usage.used_memory_ids if item not in accepted_ids
            ),
            "attribution_status": status,
            "decision_influenced": decision_accepts,
            "tool_priority_influenced": tool_accepts,
            "communication_influenced": communication_accepts,
        })

    @staticmethod
    def _reject_decision_memory_trace(trace):
        if not trace.declared_used_memory_ids:
            return trace
        return trace.model_copy(update={
            "accepted_used_memory_ids": (),
            "rejected_memory_ids": trace.declared_used_memory_ids,
            "attribution_status": MemoryUsageAttributionStatus.DECLARED_ONLY,
            "decision_influenced": False,
            "tool_priority_influenced": False,
            "communication_influenced": False,
        })

    def _resume(self, contribution):
        public = self.service.resume_episode(ResumeEpisodeInput(
            player_id=contribution.player_id,
            case_id=contribution.case_id,
            session_id=contribution.session_id,
        ))
        if not public.ok or public.observation is None:
            raise CooperativeRuntimeError("safe case observation is unavailable")
        return public

    def _load_or_initialize(self, contribution, observation):
        try:
            state = self.service.state_store.load_cooperative_agent_state(
                contribution.session_id,
                player_id=contribution.player_id,
                case_id=contribution.case_id,
            )
            return state, state.revision
        except StateNotFoundError:
            episode = AgentGoalState(
                goal_id=f"episode_{contribution.session_id}",
                goal_type=AgentGoalType.RESOLVE_CASE,
                public_description="与玩家协作完成当前病例。",
                status=AgentGoalStatus.ACTIVE,
                priority=100,
                completion_condition=GoalCondition(condition_type=GoalConditionType.CASE_COMPLETED),
                created_turn_id=contribution.contribution_id,
                updated_turn_id=contribution.contribution_id,
            )
            if observation.available_investigations:
                goal_type = AgentGoalType.GATHER_EVIDENCE
                completion = GoalCondition(condition_type=GoalConditionType.MINIMUM_CLUE_COUNT, threshold=3)
                description = "收集足以推进病例判断的公开证据。"
            elif observation.submitted_diagnosis_id is None:
                goal_type = AgentGoalType.FORM_DIAGNOSIS
                completion = GoalCondition(condition_type=GoalConditionType.DIAGNOSIS_SUBMITTED)
                description = "与玩家形成并协商公开诊断。"
            else:
                goal_type = AgentGoalType.SELECT_TREATMENT
                completion = GoalCondition(condition_type=GoalConditionType.CASE_COMPLETED)
                description = "与玩家协商安全处置。"
            current = AgentGoalState(
                goal_id=f"goal_{contribution.session_id}_1",
                goal_type=goal_type,
                public_description=description,
                status=AgentGoalStatus.ACTIVE,
                priority=80,
                completion_condition=completion,
                created_turn_id=contribution.contribution_id,
                updated_turn_id=contribution.contribution_id,
            )
            return CooperativeAgentState(
                player_id=contribution.player_id,
                case_id=contribution.case_id,
                session_id=contribution.session_id,
                episode_goal=episode,
                current_goal=current,
                revision=1,
                updated_turn_id=contribution.contribution_id,
            ), 0

    def _apply_proposal(self, state, proposal, turn_id, observation_revision, source_id):
        goal = state.current_goal
        plan = state.current_plan
        goal_changed = proposal.goal_update.update is not GoalUpdateKind.KEEP
        plan_changed = proposal.plan_update.update is not PlanUpdateKind.KEEP
        if proposal.goal_update.update is GoalUpdateKind.REPLACE:
            draft = proposal.goal_update.draft
            goal = AgentGoalState(
                goal_id=f"goal_{turn_id}", goal_type=draft.goal_type,
                public_description=draft.public_description, status=AgentGoalStatus.ACTIVE,
                priority=draft.priority, evidence_requirements=draft.evidence_requirements,
                completion_condition=draft.completion_condition,
                source_contribution_id=source_id, created_turn_id=turn_id,
                updated_turn_id=turn_id, revision=1,
            )
        elif proposal.goal_update.update is GoalUpdateKind.BLOCK:
            goal = goal.model_copy(update={"status": AgentGoalStatus.BLOCKED, "blocked_reason": proposal.goal_update.blocked_reason, "updated_turn_id": turn_id, "revision": goal.revision + 1})
        elif proposal.goal_update.update is GoalUpdateKind.ABANDON:
            goal = goal.model_copy(update={"status": AgentGoalStatus.ABANDONED, "updated_turn_id": turn_id, "revision": goal.revision + 1})

        if proposal.plan_update.update in {PlanUpdateKind.CREATE, PlanUpdateKind.REVISE}:
            draft = proposal.plan_update.draft
            prior_revision = plan.revision if plan is not None else 0
            plan_id = plan.plan_id if plan is not None else f"plan_{turn_id}"
            steps = tuple(
                PlanStep(
                    step_id=f"{plan_id}_r{prior_revision + 1}_s{index}", ordinal=index,
                    intent=item.intent, capability=item.capability,
                    suggested_tool=item.suggested_tool, public_target_id=item.public_target_id,
                    public_summary=item.public_summary, expected_information=item.expected_information,
                    completion_signal=item.completion_signal,
                    status=PlanStepStatus.ACTIVE if index == 0 else PlanStepStatus.PENDING,
                )
                for index, item in enumerate(draft.steps)
            )
            plan = AgentPlan(
                plan_id=plan_id, goal_id=goal.goal_id, status=AgentPlanStatus.ACTIVE,
                steps=steps, current_step_index=0,
                based_on_observation_revision=observation_revision,
                source_contribution_id=source_id, created_turn_id=(plan.created_turn_id if plan else turn_id),
                updated_turn_id=turn_id, revision=prior_revision + 1,
            )
        elif proposal.plan_update.update is PlanUpdateKind.ABANDON and plan is not None:
            steps = tuple(item.model_copy(update={"status": PlanStepStatus.OBSOLETE}) if item.status in {PlanStepStatus.ACTIVE, PlanStepStatus.PENDING} else item for item in plan.steps)
            plan = plan.model_copy(update={"status": AgentPlanStatus.ABANDONED, "steps": steps, "updated_turn_id": turn_id, "revision": plan.revision + 1})
        return state.model_copy(update={"current_goal": goal, "current_plan": plan}), goal_changed, plan_changed

    def _mark_invalid_plan(self, state, observation, turn_id):
        plan = state.current_plan
        if plan is None or plan.status is not AgentPlanStatus.ACTIVE or self.plan_evaluator.plan_compatible(plan, observation):
            return state
        steps = tuple(item.model_copy(update={"status": PlanStepStatus.OBSOLETE}) if item.status in {PlanStepStatus.ACTIVE, PlanStepStatus.PENDING} else item for item in plan.steps)
        return state.model_copy(update={"current_plan": plan.model_copy(update={"status": AgentPlanStatus.NEEDS_REVISION, "steps": steps, "updated_turn_id": turn_id, "revision": plan.revision + 1})})

    @staticmethod
    def _complete_satisfied_goal(state, observation, turn_id):
        goal = state.current_goal.model_copy(update={
            "status": AgentGoalStatus.COMPLETED,
            "updated_turn_id": turn_id,
            "revision": state.current_goal.revision + 1,
        })
        plan = state.current_plan
        evaluation = None
        if plan is not None:
            steps = tuple(
                item.model_copy(update={"status": PlanStepStatus.OBSOLETE})
                if item.status in {PlanStepStatus.ACTIVE, PlanStepStatus.PENDING}
                else item
                for item in plan.steps
            )
            plan = plan.model_copy(update={
                "status": AgentPlanStatus.COMPLETED,
                "steps": steps,
                "updated_turn_id": turn_id,
                "revision": plan.revision + 1,
            })
            evaluation = PlanEvaluation(
                evaluation_id=f"evaluation_{turn_id}", plan_id=plan.plan_id,
                outcome=PlanEvaluationOutcome.COMPLETE_GOAL,
                reason_code=PlanEvaluationReason.GOAL_COMPLETED,
                observation_revision_before=observation.session_revision,
                observation_revision_after=observation.session_revision,
                obsolete_step_ids=tuple(item.step_id for item in steps if item.status is PlanStepStatus.OBSOLETE),
                next_goal_status=AgentGoalStatus.COMPLETED,
                public_summary="确定性完成条件在行动前已经满足。",
                evaluated_turn_id=turn_id,
            )
        return state.model_copy(update={
            "current_goal": goal,
            "current_plan": plan,
            "last_plan_evaluation": evaluation,
        })

    @staticmethod
    def _completion_decision(contribution, goal_id):
        return GameNPCDecision(
            decision_id=f"decision_{contribution.contribution_id}",
            turn_id=contribution.contribution_id,
            proposal=GameNPCDecisionProposal(
                contribution_evaluation=PlayerContributionEvaluation(
                    contribution_id=contribution.contribution_id,
                    disposition=SuggestionDisposition.PROPOSE_ALTERNATIVE,
                    reason_code="goal_already_complete",
                    explanation="当前目标已经由公开状态确定性完成。",
                ),
                capability=NPCCapability.EXPLAIN,
                action=AgentAction(
                    action_id=f"npc_{contribution.contribution_id}",
                    action_type=AgentActionType.RESPOND,
                    dialogue="当前目标已经完成；我们下一轮再协商新的目标。",
                    confidence=1.0,
                ),
                explanation="完成目标的本轮不自动执行下一目标工具。",
            ),
            llm_attempts=1,
            used_fallback=False,
            goal_id=goal_id,
        )

    @staticmethod
    def _associate_decision(decision, state):
        plan = state.current_plan
        if plan is None or plan.status is not AgentPlanStatus.ACTIVE:
            return decision.model_copy(update={"goal_id": state.current_goal.goal_id})
        step = plan.steps[plan.current_step_index]
        return decision.model_copy(update={"goal_id": state.current_goal.goal_id, "plan_id": plan.plan_id, "plan_step_id": step.step_id, "planning_intent": step.intent.value})

    @staticmethod
    def _action_matches_plan(decision, state):
        action = decision.proposal.action
        if action.action_type is AgentActionType.RESPOND:
            return True
        plan = state.current_plan
        if plan is None or plan.status is not AgentPlanStatus.ACTIVE:
            return False
        step = plan.steps[plan.current_step_index]
        if action.tool_call is None or action.tool_call.name is not step.suggested_tool:
            return False
        target = next(iter(action.tool_call.arguments.values()), None)
        return target == step.public_target_id

    @staticmethod
    def _advance_state_revision(state, turn_id, expected_revision):
        return state.model_copy(update={
            "revision": 1 if expected_revision == 0 else expected_revision + 1,
            "updated_turn_id": turn_id,
        })

    def _save_state(self, state, expected_revision):
        # A newly initialized in-memory state is already revision one. Existing state
        # advances exactly once per cooperative turn.
        self.service.state_store.save_cooperative_agent_state(state, expected_revision=expected_revision)

    def _result(self, state, decision, *, goal_changed, plan_changed, status, authority_mode, public_rationale=None, memory_usage_trace=None, **kwargs):
        plan = state.current_plan
        current_step = None
        summaries = ()
        if plan is not None:
            summaries = tuple(item.public_summary for item in plan.steps)
            current_step = plan.steps[plan.current_step_index].public_summary
        evaluation = state.last_plan_evaluation
        return CooperativeTurnResult(
            turn_id=decision.turn_id, status=status, decision=decision,
            runtime_kind=getattr(self.agent, "runtime_kind", AgentRuntimeKind.UNKNOWN),
            authority_mode=authority_mode, public_rationale=public_rationale or decision.proposal.explanation,
            current_goal_description=state.current_goal.public_description,
            plan_public_summary=summaries, current_step_summary=current_step,
            goal_changed=goal_changed, plan_changed=plan_changed,
            plan_evaluation_outcome=evaluation.outcome.value if evaluation else None,
            public_plan_change_reason=evaluation.public_summary if evaluation else None,
            agent_state_revision=state.revision,
            memory_retrieval_status=memory_usage_trace.retrieval_status if memory_usage_trace else None,
            memory_retrieval_id=memory_usage_trace.retrieval_id if memory_usage_trace else None,
            selected_memory_count=len(memory_usage_trace.selected_memory_ids) if memory_usage_trace else 0,
            memory_usage_trace=memory_usage_trace,
            public_memory_effect_summary=(
                memory_usage_trace.public_effect_summary if memory_usage_trace else None
            ),
            **kwargs,
        )

    @staticmethod
    def _public_target(action, observation):
        if action.tool_call is None:
            return None
        arguments = action.tool_call.arguments
        if "investigation_id" in arguments:
            target = next((item for item in observation.available_investigations if item.investigation_id == arguments["investigation_id"]), None)
            return target.public_description if target is not None else None
        if "diagnosis_id" in arguments:
            target = next((item for item in observation.diagnosis_candidates if item.diagnosis_id == arguments["diagnosis_id"]), None)
            return target.public_description if target is not None else None
        if "treatment_id" in arguments:
            target = next((item for item in observation.available_treatments if item.treatment_id == arguments["treatment_id"]), None)
            return target.public_description if target is not None else None
        return None

    def _resolve_contract(self, agent_input, decision, observation):
        try:
            self.action_validator.validate(decision.proposal.action, observation)
            return decision
        except PublicActionContractError as first:
            repaired = self.agent.repair_action_contract(agent_input, decision, build_safe_action_feedback(first.code, observation))
        if repaired.used_fallback:
            return repaired
        try:
            self.action_validator.validate(repaired.proposal.action, observation)
            return repaired
        except PublicActionContractError:
            return self.agent.action_contract_fallback(repaired)

    @staticmethod
    def _validated_pending(pending, contribution, revision):
        if pending is None or contribution.contribution_type is not PlayerContributionType.APPROVAL:
            return None
        if (pending.player_id, pending.case_id, pending.session_id) != (contribution.player_id, contribution.case_id, contribution.session_id):
            return None
        if contribution.responds_to_decision_id != pending.decision_id or pending.case_revision != revision:
            return None
        return pending
