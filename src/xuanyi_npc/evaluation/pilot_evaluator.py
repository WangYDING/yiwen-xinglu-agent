"""Deterministic evaluator for real-model behavior probes."""

from xuanyi_npc.domain import AgentActionType, ToolName
from xuanyi_npc.engine import CaseEventReplayer, EventReplayError

from .episode import EpisodeResult
from .pilot_contracts import (
    PilotBehaviorProbe,
    PilotEvaluationResult,
    PilotFailureCategory,
    PilotFormatOutcome,
)


_PREMATURE_ERROR_CODES = {
    "evidence_not_discovered",
    "diagnosis_required",
    "treatment_prerequisite_missing",
}


class PilotBehaviorEvaluator:
    """Evaluate task behavior without requiring injected faults or repair."""

    def evaluate(
        self,
        probe: PilotBehaviorProbe,
        episode: EpisodeResult,
    ) -> PilotEvaluationResult:
        failures: set[PilotFailureCategory] = set()
        truth = probe.ground_truth
        criteria = probe.success_conditions

        if episode.initial_session.case_id != truth.case_id:
            failures.add(PilotFailureCategory.CASE_MISMATCH)
        if episode.status is not criteria.expected_status:
            failures.add(PilotFailureCategory.EPISODE_NOT_COMPLETED)

        expected_sequences = tuple(
            range(
                len(episode.initial_session.action_history) + 1,
                len(episode.initial_session.action_history) + len(episode.events) + 1,
            )
        )
        actual_sequences = tuple(event.sequence for event in episode.events)
        contiguous = actual_sequences == expected_sequences
        if criteria.require_contiguous_events and not contiguous:
            failures.add(PilotFailureCategory.EVENT_SEQUENCE_INVALID)

        replay_consistent = False
        try:
            replayed = CaseEventReplayer().replay(
                episode.initial_session,
                episode.events,
            )
        except EventReplayError:
            failures.add(PilotFailureCategory.EVENT_REPLAY_FAILED)
        else:
            replay_consistent = replayed == episode.final_session
            if criteria.require_replay_match and not replay_consistent:
                failures.add(PilotFailureCategory.EVENT_REPLAY_FAILED)

        first_pass = sum(
            step.llm_attempts == 1 and not step.used_fallback
            for step in episode.steps
        )
        repaired = sum(
            step.llm_attempts == 2 and not step.used_fallback
            for step in episode.steps
        )
        fallback = sum(step.used_fallback for step in episode.steps)
        format_outcome = (
            PilotFormatOutcome.FALLBACK
            if fallback
            else PilotFormatOutcome.REPAIRED
            if repaired
            else PilotFormatOutcome.FIRST_PASS
        )
        if fallback > criteria.maximum_fallback_steps:
            failures.add(PilotFailureCategory.FORMAT_FALLBACK)

        rejected = sum(not step.accepted for step in episode.steps)
        if rejected > criteria.maximum_rejected_steps:
            failures.add(PilotFailureCategory.RULE_REJECTION)

        diagnosis_steps = tuple(
            step
            for step in episode.steps
            if step.action.action_type is AgentActionType.USE_TOOL
            and step.action.tool_call is not None
            and step.action.tool_call.name is ToolName.SUBMIT_DIAGNOSIS
        )
        treatment_steps = tuple(
            step
            for step in episode.steps
            if step.action.action_type is AgentActionType.USE_TOOL
            and step.action.tool_call is not None
            and step.action.tool_call.name is ToolName.EXECUTE_TREATMENT
        )
        diagnosis_tool_called = bool(diagnosis_steps)
        treatment_tool_called = bool(treatment_steps)
        diagnosis_id = episode.final_session.submitted_diagnosis_id
        diagnosis_correct = (
            None if diagnosis_id is None else diagnosis_id in truth.valid_diagnosis_ids
        )
        treatment_id = episode.final_session.selected_treatment_id
        treatment_resolving = (
            None if treatment_id is None else treatment_id == truth.resolving_treatment_id
        )

        if not diagnosis_tool_called or diagnosis_id is None:
            failures.add(PilotFailureCategory.DIAGNOSIS_NOT_SUBMITTED)
        elif not diagnosis_correct:
            failures.add(PilotFailureCategory.WRONG_DIAGNOSIS)
        if not treatment_tool_called or treatment_id is None:
            failures.add(PilotFailureCategory.TREATMENT_MISSING)
        elif not treatment_resolving:
            failures.add(PilotFailureCategory.WRONG_TREATMENT)
        if episode.final_session.outcome is not truth.expected_outcome:
            failures.add(PilotFailureCategory.OUTCOME_NOT_RESOLVED)
        if (
            episode.final_session.score is None
            or episode.final_session.score < truth.target_score
        ):
            failures.add(PilotFailureCategory.SCORE_BELOW_TARGET)

        premature = sum(
            step.error_code in _PREMATURE_ERROR_CODES for step in episode.steps
        )
        for step in diagnosis_steps:
            if not step.accepted or step.action.tool_call is None:
                continue
            evidence = set(step.action.tool_call.arguments.get("evidence_clue_ids", []))
            if not truth.diagnosis_evidence_floor.issubset(evidence):
                premature += 1
        if premature > criteria.maximum_premature_actions:
            failures.add(PilotFailureCategory.PREMATURE_ACTION)

        progressless_responds = sum(
            step.action.action_type is AgentActionType.RESPOND
            for step in episode.steps
        )
        if progressless_responds > criteria.maximum_progressless_responds:
            failures.add(PilotFailureCategory.RESPOND_WITH_PROGRESS_AVAILABLE)

        ordered = tuple(sorted(failures, key=lambda item: item.value))
        return PilotEvaluationResult(
            probe_id=probe.probe_id,
            task_passed=not ordered,
            failure_categories=ordered,
            episode_status=episode.status,
            format_outcome=format_outcome,
            first_pass_structured_steps=first_pass,
            repaired_steps=repaired,
            fallback_steps=fallback,
            rejected_steps=rejected,
            event_count=len(episode.events),
            event_sequences_contiguous=contiguous,
            replay_consistent=replay_consistent,
            diagnosis_tool_called=diagnosis_tool_called,
            diagnosis_correct=diagnosis_correct,
            treatment_tool_called=treatment_tool_called,
            treatment_resolving=treatment_resolving,
            premature_actions=premature,
            progressless_responds=progressless_responds,
            final_score=episode.final_session.score,
        )
