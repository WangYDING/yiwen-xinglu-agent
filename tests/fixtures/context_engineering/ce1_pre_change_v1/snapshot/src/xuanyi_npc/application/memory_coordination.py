"""Explicit V1 commit and reconciliation boundary for M4-P1 memory."""

from __future__ import annotations

from typing import Protocol

from xuanyi_npc.domain.cases import CaseDefinition, CaseSessionState
from xuanyi_npc.domain.events import (
    DiagnosisSubmittedEvent,
    InvestigationCompletedEvent,
    TreatmentExecutedEvent,
)
from xuanyi_npc.domain.player import PlayerState
from xuanyi_npc.engine.results import EngineResult
from xuanyi_npc.memory.canonical import stable_source_event_id
from xuanyi_npc.memory.contracts import (
    AuthoritativeMemoryRecord,
    MemoryCommitResult,
    MemoryCommitStatus,
    MemorySourceEventType,
    ProjectionWriteResult,
    VerifiedMemorySource,
)
from xuanyi_npc.memory.errors import MemoryError
from xuanyi_npc.memory.projection import DeterministicMemoryProjector
from xuanyi_npc.storage.json_store import JsonStateStore


class MemoryProjectionRepository(Protocol):
    def write_projection(
        self,
        source: VerifiedMemorySource,
        memory: AuthoritativeMemoryRecord,
    ) -> ProjectionWriteResult:
        """Persist one public source and its authoritative memory atomically."""


class V1MemoryCoordinator:
    """Enable memory only through explicit V1 composition, never shared V0 paths."""

    def __init__(
        self,
        *,
        state_store: JsonStateStore,
        memory_repository: MemoryProjectionRepository,
        projector: DeterministicMemoryProjector | None = None,
    ) -> None:
        self.state_store = state_store
        self.memory_repository = memory_repository
        self.projector = projector or DeterministicMemoryProjector()

    def commit_engine_result(
        self,
        *,
        case: CaseDefinition,
        player: PlayerState,
        previous_session: CaseSessionState,
        result: EngineResult,
    ) -> MemoryCommitResult:
        """Save JSON first, then project; a projection failure remains pending."""

        self._validate_transition(case, player, previous_session, result)
        # Intentionally first. If this raises, the memory repository is untouched.
        self.state_store.save_case_session(result.session)

        projections: list[ProjectionWriteResult] = []
        for index, event in enumerate(result.events):
            source_revision = previous_session.revision + index + 1
            try:
                source, memory = self.projector.project_committed_event(
                    event=event,
                    case=case,
                    player=player,
                    session=result.session,
                    source_revision=source_revision,
                )
                projections.append(
                    self.memory_repository.write_projection(source, memory)
                )
            except MemoryError as exc:
                return MemoryCommitResult(
                    status=MemoryCommitStatus.MEMORY_PROJECTION_PENDING,
                    session_id=result.session.session_id,
                    projections=tuple(projections),
                    pending_source_event_ids=tuple(
                        self._event_source_id(item)
                        for item in result.events[index:]
                    ),
                    error_code=exc.code,
                )
        return MemoryCommitResult(
            status=MemoryCommitStatus.COMPLETE,
            session_id=result.session.session_id,
            projections=tuple(projections),
        )

    def reconcile_committed_session(
        self,
        *,
        case: CaseDefinition,
        player_id: str,
        session_id: str,
    ) -> MemoryCommitResult:
        """Rebuild missing projections only from already committed JSON state."""

        player = self.state_store.load_player(player_id)
        session = self.state_store.load_case_session(session_id)
        if player.player_id != player_id or session.player_id != player_id:
            raise ValueError("committed player context does not match")
        if session.case_id != case.case_id:
            raise ValueError("committed case context does not match")
        base_revision = session.revision - len(session.action_history)
        if base_revision < 0:
            raise ValueError("committed revision cannot identify source revisions")

        projections: list[ProjectionWriteResult] = []
        for index, record in enumerate(session.action_history):
            try:
                source, memory = self.projector.project_committed_action(
                    case=case,
                    player=player,
                    session=session,
                    source_sequence=record.sequence,
                    source_revision=base_revision + record.sequence,
                )
                projections.append(
                    self.memory_repository.write_projection(source, memory)
                )
            except MemoryError as exc:
                return MemoryCommitResult(
                    status=MemoryCommitStatus.MEMORY_PROJECTION_PENDING,
                    session_id=session.session_id,
                    projections=tuple(projections),
                    pending_source_event_ids=tuple(
                        stable_source_event_id(
                            self._record_source_type(item).value,
                            session.session_id,
                            item.sequence,
                        )
                        for item in session.action_history[index:]
                    ),
                    error_code=exc.code,
                )
        return MemoryCommitResult(
            status=MemoryCommitStatus.COMPLETE,
            session_id=session.session_id,
            projections=tuple(projections),
        )

    @staticmethod
    def _validate_transition(
        case: CaseDefinition,
        player: PlayerState,
        previous: CaseSessionState,
        result: EngineResult,
    ) -> None:
        if previous.case_id != case.case_id or result.session.case_id != case.case_id:
            raise ValueError("case transition context does not match")
        if previous.player_id != player.player_id or result.session.player_id != player.player_id:
            raise ValueError("player transition context does not match")
        if previous.session_id != result.session.session_id:
            raise ValueError("session transition context does not match")
        if result.session.revision != previous.revision + len(result.events):
            raise ValueError("result revision does not match committed events")
        if len(result.session.action_history) != len(previous.action_history) + len(
            result.events
        ):
            raise ValueError("result action history does not match committed events")
        previous_count = len(previous.action_history)
        if result.session.action_history[:previous_count] != previous.action_history:
            raise ValueError("committed action history prefix was modified")
        appended = result.session.action_history[previous_count:]
        if tuple(event.sequence for event in result.events) != tuple(
            record.sequence for record in appended
        ):
            raise ValueError("committed events do not match appended action records")

    @classmethod
    def _event_source_id(cls, event: object) -> str:
        if isinstance(event, InvestigationCompletedEvent):
            event_type = MemorySourceEventType.INVESTIGATION_COMPLETED
        elif isinstance(event, DiagnosisSubmittedEvent):
            event_type = MemorySourceEventType.DIAGNOSIS_SUBMITTED
        elif isinstance(event, TreatmentExecutedEvent):
            event_type = MemorySourceEventType.TREATMENT_EXECUTED
        else:
            raise ValueError("event type is not allowlisted")
        return stable_source_event_id(
            event_type.value,
            event.session_id,
            event.sequence,
        )

    @staticmethod
    def _record_source_type(record: object) -> MemorySourceEventType:
        action_type = record.action_type
        if action_type.value in {
            "observe_patient",
            "question_patient",
            "inspect_object",
            "observe_qi",
            "investigate_location",
        }:
            return MemorySourceEventType.INVESTIGATION_COMPLETED
        if action_type.value == "submit_diagnosis":
            return MemorySourceEventType.DIAGNOSIS_SUBMITTED
        if action_type.value == "execute_treatment":
            return MemorySourceEventType.TREATMENT_EXECUTED
        raise ValueError("committed action type is not allowlisted")
