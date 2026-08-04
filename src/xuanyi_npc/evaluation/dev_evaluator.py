"""Deterministic evaluator for M2b-P0 dev episodes."""

from xuanyi_npc.engine import CaseEventReplayer, EventReplayError

from .dev_contracts import (
    DevEvaluationResult,
    DevFailureCategory,
    DevScenario,
)
from .episode import EpisodeResult


class DevEpisodeEvaluator:
    """Classify one unified EpisodeResult without calling an Agent or model."""

    def evaluate(
        self,
        scenario: DevScenario,
        trajectory_id: str,
        episode: EpisodeResult,
    ) -> DevEvaluationResult:
        failures: set[DevFailureCategory] = set()
        truth = scenario.ground_truth
        criteria = scenario.success_conditions

        if episode.initial_session.case_id != truth.case_id:
            failures.add(DevFailureCategory.CASE_MISMATCH)
        if episode.status is not criteria.expected_status:
            failures.add(DevFailureCategory.EPISODE_NOT_COMPLETED)

        expected_sequences = tuple(
            range(
                len(episode.initial_session.action_history) + 1,
                len(episode.initial_session.action_history) + len(episode.events) + 1,
            )
        )
        actual_sequences = tuple(event.sequence for event in episode.events)
        if criteria.require_contiguous_events and actual_sequences != expected_sequences:
            failures.add(DevFailureCategory.EVENT_SEQUENCE_INVALID)
        if len(episode.events) != criteria.expected_event_count:
            failures.add(DevFailureCategory.EVENT_COUNT_MISMATCH)

        replay_consistent = False
        try:
            replayed = CaseEventReplayer().replay(
                episode.initial_session,
                episode.events,
            )
        except EventReplayError:
            failures.add(DevFailureCategory.EVENT_REPLAY_FAILED)
        else:
            replay_consistent = replayed == episode.final_session
            if criteria.require_replay_match and not replay_consistent:
                failures.add(DevFailureCategory.EVENT_REPLAY_FAILED)

        rejected_steps = sum(not step.accepted for step in episode.steps)
        repaired_steps = sum(
            step.llm_attempts == 2 and not step.used_fallback
            for step in episode.steps
        )
        fallback_steps = sum(step.used_fallback for step in episode.steps)
        if rejected_steps > criteria.maximum_rejected_steps:
            failures.add(DevFailureCategory.RULE_REJECTION)
        if repaired_steps < criteria.minimum_repaired_steps:
            failures.add(DevFailureCategory.REQUIRED_RECOVERY_MISSING)
        if fallback_steps > criteria.maximum_fallback_steps:
            failures.add(DevFailureCategory.FORMAT_RECOVERY_FAILED)

        diagnosis_id = episode.final_session.submitted_diagnosis_id
        if diagnosis_id is None:
            failures.add(DevFailureCategory.DIAGNOSIS_MISSING)
        elif diagnosis_id not in truth.valid_diagnosis_ids:
            failures.add(DevFailureCategory.WRONG_HYPOTHESIS)

        treatment_id = episode.final_session.selected_treatment_id
        if treatment_id is None:
            failures.add(DevFailureCategory.TREATMENT_MISSING)
        elif treatment_id != truth.resolving_treatment_id:
            failures.add(DevFailureCategory.TREATMENT_MISMATCH)

        if episode.final_session.outcome is not truth.expected_outcome:
            failures.add(DevFailureCategory.OUTCOME_MISMATCH)
        if episode.score_breakdown != truth.expected_score_breakdown:
            failures.add(DevFailureCategory.SCORE_MISMATCH)

        usage_measured = episode.usage is not None
        if criteria.require_unmeasured_usage and usage_measured:
            failures.add(DevFailureCategory.UNEXPECTED_MEASURED_USAGE)

        ordered_failures = tuple(sorted(failures, key=lambda item: item.value))
        return DevEvaluationResult(
            scenario_id=scenario.scenario_id,
            trajectory_id=trajectory_id,
            task_passed=not ordered_failures,
            failure_categories=ordered_failures,
            episode_status=episode.status,
            final_score=episode.final_session.score,
            step_count=len(episode.steps),
            event_count=len(episode.events),
            final_revision=episode.final_session.revision,
            replay_consistent=replay_consistent,
            rejected_steps=rejected_steps,
            repaired_steps=repaired_steps,
            fallback_steps=fallback_steps,
            usage_measured=usage_measured,
        )
