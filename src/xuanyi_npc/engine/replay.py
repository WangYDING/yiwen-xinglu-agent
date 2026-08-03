"""Rebuild case-session state from an initial snapshot and domain events."""

from collections.abc import Iterable

from pydantic import ValidationError

from xuanyi_npc.domain.cases import (
    ActionRecord,
    CaseSessionState,
    CaseSessionStatus,
)
from xuanyi_npc.domain.events import (
    CaseEvent,
    DiagnosisSubmittedEvent,
    InvestigationCompletedEvent,
    TreatmentExecutedEvent,
)


class EventReplayError(ValueError):
    """Raised when an event stream cannot validly continue the initial state."""


class CaseEventReplayer:
    def replay(
        self,
        initial: CaseSessionState,
        events: Iterable[CaseEvent],
    ) -> CaseSessionState:
        current = initial.model_copy(deep=True)

        for event in events:
            if current.status is CaseSessionStatus.COMPLETED:
                raise EventReplayError("events cannot be applied after case completion")
            expected_sequence = len(current.action_history) + 1
            if event.sequence != expected_sequence:
                raise EventReplayError(
                    f"expected event sequence {expected_sequence}, got {event.sequence}"
                )
            if event.session_id != current.session_id:
                raise EventReplayError("event session_id does not match initial state")

            if isinstance(event, InvestigationCompletedEvent):
                current = self._apply_investigation(current, event)
            elif isinstance(event, DiagnosisSubmittedEvent):
                current = self._apply_diagnosis(current, event)
            elif isinstance(event, TreatmentExecutedEvent):
                current = self._apply_treatment(current, event)
            else:
                raise EventReplayError("unsupported case event type")

        return current

    def _apply_investigation(
        self,
        current: CaseSessionState,
        event: InvestigationCompletedEvent,
    ) -> CaseSessionState:
        duplicate_clues = event.newly_discovered_clue_ids.intersection(
            current.discovered_clue_ids
        )
        if duplicate_clues:
            raise EventReplayError("an event cannot rediscover an existing clue as new")
        record = ActionRecord(
            sequence=event.sequence,
            action_type=event.action_type,
            reference_id=event.investigation_id,
            target_id=event.target_id,
            revealed_clue_ids=event.newly_discovered_clue_ids,
            occurred_at=event.occurred_at,
        )
        return self._updated_session(
            current,
            discovered_clue_ids=(
                current.discovered_clue_ids | event.newly_discovered_clue_ids
            ),
            action_history=(*current.action_history, record),
            revision=current.revision + 1,
        )

    def _apply_diagnosis(
        self,
        current: CaseSessionState,
        event: DiagnosisSubmittedEvent,
    ) -> CaseSessionState:
        unavailable = event.evidence_clue_ids.difference(current.discovered_clue_ids)
        if unavailable:
            raise EventReplayError("diagnosis event cites unavailable evidence")
        record = ActionRecord(
            sequence=event.sequence,
            action_type="submit_diagnosis",
            reference_id=event.diagnosis_id,
            target_id=event.diagnosis_id,
            evidence_clue_ids=event.evidence_clue_ids,
            occurred_at=event.occurred_at,
        )
        return self._updated_session(
            current,
            submitted_diagnosis_id=event.diagnosis_id,
            action_history=(*current.action_history, record),
            revision=current.revision + 1,
        )

    def _apply_treatment(
        self,
        current: CaseSessionState,
        event: TreatmentExecutedEvent,
    ) -> CaseSessionState:
        if current.submitted_diagnosis_id is None:
            raise EventReplayError("treatment event requires a submitted diagnosis")
        record = ActionRecord(
            sequence=event.sequence,
            action_type="execute_treatment",
            reference_id=event.treatment_id,
            target_id=event.treatment_id,
            occurred_at=event.occurred_at,
        )
        return self._updated_session(
            current,
            status=CaseSessionStatus.COMPLETED,
            selected_treatment_id=event.treatment_id,
            outcome=event.outcome,
            score=event.score,
            action_history=(*current.action_history, record),
            revision=current.revision + 1,
        )

    @staticmethod
    def _updated_session(
        session: CaseSessionState,
        **changes: object,
    ) -> CaseSessionState:
        data = session.model_dump(mode="python")
        data.update(changes)
        try:
            return CaseSessionState.model_validate(data)
        except ValidationError as exc:
            raise EventReplayError("event stream produced an invalid session state") from exc
