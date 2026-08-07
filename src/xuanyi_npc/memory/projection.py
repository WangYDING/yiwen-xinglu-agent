"""Deterministic projection from committed public case facts to memory."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

from pydantic import Field, StrictInt, model_validator

from xuanyi_npc.domain.base import Identifier, NonEmptyText
from xuanyi_npc.domain.cases import (
    INVESTIGATION_ACTIONS,
    ActionRecord,
    CaseActionType,
    CaseDefinition,
    CaseSessionState,
    TreatmentOutcome,
)
from xuanyi_npc.domain.events import (
    DiagnosisSubmittedEvent,
    InvestigationCompletedEvent,
    TreatmentExecutedEvent,
)
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.domain.player import PlayerState

from .canonical import sha256_hex, stable_memory_id, stable_source_event_id
from .contracts import (
    AuthoritativeMemoryRecord,
    DiagnosisPublicPayload,
    InvestigationPublicPayload,
    MemorySourceEventType,
    MemoryWriteReason,
    PublicClueFact,
    StrictMemoryModel,
    TreatmentPublicPayload,
    UtcDateTime,
    VerifiedMemorySource,
    authoritative_content_payload,
)
from .errors import InvalidCommittedSourceError, UnsupportedMemorySourceError

if TYPE_CHECKING:
    from xuanyi_npc.application.views import AgentContextFilter


DEFAULT_PROJECTION_VERSION = "memory_projection_v1"

PUBLIC_TREATMENT_RESULTS = {
    TreatmentOutcome.RESOLVED: "处置后病例已经解决。",
    TreatmentOutcome.SUPPRESSED: "处置后症状暂时减弱，但病例尚未解决。",
    TreatmentOutcome.WORSENED: "处置后异常进一步加重。",
}


class CommittedActionPublicView(StrictMemoryModel):
    """Allowlisted view built before the projector sees any content."""

    player_id: Identifier
    source_session_id: Identifier
    source_event_type: MemorySourceEventType
    source_sequence: Annotated[StrictInt, Field(ge=1)]
    source_revision: Annotated[StrictInt, Field(ge=1)]
    occurred_at: UtcDateTime
    case_id: Identifier
    case_title: NonEmptyText
    action_type: CaseActionType
    action_id: Identifier
    public_action_description: NonEmptyText
    public_clues: tuple[PublicClueFact, ...] = Field(default_factory=tuple)
    public_result: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_public_shape(self) -> "CommittedActionPublicView":
        clue_ids = [item.clue_id for item in self.public_clues]
        if clue_ids != sorted(clue_ids) or len(clue_ids) != len(set(clue_ids)):
            raise ValueError("public clues must be unique and sorted")
        if self.source_event_type is MemorySourceEventType.TREATMENT_EXECUTED:
            if self.public_result is None:
                raise ValueError("treatment projection requires a public result")
        elif self.public_result is not None:
            raise ValueError("only treatment projection can include a public result")
        return self


class CommittedActionPublicViewBuilder:
    """Filter committed state into the only input accepted by the projector."""

    def __init__(self, context_filter: AgentContextFilter | None = None) -> None:
        if context_filter is None:
            from xuanyi_npc.application.views import AgentContextFilter

            context_filter = AgentContextFilter()
        self.context_filter: Any = context_filter

    def build(
        self,
        *,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
        source_sequence: int,
        source_revision: int,
    ) -> CommittedActionPublicView:
        try:
            self.context_filter.case_observation(case, player, session)
        except ValueError as exc:
            raise InvalidCommittedSourceError("committed context is invalid") from exc

        record = self._record_at(session, source_sequence)
        if record.action_type in INVESTIGATION_ACTIONS:
            source_type = MemorySourceEventType.INVESTIGATION_COMPLETED
            investigation = next(
                (
                    item
                    for item in case.investigations
                    if item.investigation_id == record.reference_id
                    and item.action_type == record.action_type
                    and item.target_id == record.target_id
                ),
                None,
            )
            if investigation is None:
                raise InvalidCommittedSourceError(
                    "committed investigation has no public definition"
                )
            public_description = investigation.public_description
            clue_ids = record.revealed_clue_ids
            public_result = None
        elif record.action_type is CaseActionType.SUBMIT_DIAGNOSIS:
            source_type = MemorySourceEventType.DIAGNOSIS_SUBMITTED
            candidate = case.diagnosis_candidates.get(record.reference_id)
            if candidate is None or record.target_id != record.reference_id:
                raise InvalidCommittedSourceError(
                    "committed diagnosis has no public candidate"
                )
            public_description = candidate.public_description
            clue_ids = record.evidence_clue_ids
            public_result = None
        elif record.action_type is CaseActionType.EXECUTE_TREATMENT:
            source_type = MemorySourceEventType.TREATMENT_EXECUTED
            treatment = case.treatments.get(record.reference_id)
            if treatment is None or record.target_id != record.reference_id:
                raise InvalidCommittedSourceError(
                    "committed treatment has no public definition"
                )
            if (
                session.selected_treatment_id != record.reference_id
                or session.outcome is None
            ):
                raise InvalidCommittedSourceError(
                    "committed treatment has no observable final result"
                )
            public_description = treatment.public_description
            clue_ids = frozenset()
            public_result = PUBLIC_TREATMENT_RESULTS[session.outcome]
        else:
            raise UnsupportedMemorySourceError("action type is not allowlisted")

        if not clue_ids.issubset(session.discovered_clue_ids):
            raise InvalidCommittedSourceError(
                "committed action references clues outside public session state"
            )
        try:
            clues = tuple(
                PublicClueFact(
                    clue_id=clue_id,
                    description=case.clues[clue_id].description,
                )
                for clue_id in sorted(clue_ids)
            )
        except KeyError as exc:
            raise InvalidCommittedSourceError(
                "committed action references an unknown public clue"
            ) from exc

        return CommittedActionPublicView(
            player_id=player.player_id,
            source_session_id=session.session_id,
            source_event_type=source_type,
            source_sequence=record.sequence,
            source_revision=source_revision,
            occurred_at=record.occurred_at,
            case_id=case.case_id,
            case_title=case.title,
            action_type=record.action_type,
            action_id=record.reference_id,
            public_action_description=public_description,
            public_clues=clues,
            public_result=public_result,
        )

    @staticmethod
    def _record_at(session: CaseSessionState, sequence: int) -> ActionRecord:
        if sequence < 1 or sequence > len(session.action_history):
            raise InvalidCommittedSourceError("source sequence is not committed")
        record = session.action_history[sequence - 1]
        if record.sequence != sequence:
            raise InvalidCommittedSourceError("committed action sequence is invalid")
        return record


class DeterministicMemoryProjector:
    """Project only strict public views; never serialize raw domain events."""

    def __init__(
        self,
        *,
        projection_version: str = DEFAULT_PROJECTION_VERSION,
        projection_ordinal: int = 0,
        view_builder: CommittedActionPublicViewBuilder | None = None,
    ) -> None:
        self.projection_version = projection_version
        self.projection_ordinal = projection_ordinal
        self.view_builder = view_builder or CommittedActionPublicViewBuilder()

    def project_committed_event(
        self,
        *,
        event: object,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
        source_revision: int,
    ) -> tuple[VerifiedMemorySource, AuthoritativeMemoryRecord]:
        if not isinstance(
            event,
            (
                InvestigationCompletedEvent,
                DiagnosisSubmittedEvent,
                TreatmentExecutedEvent,
            ),
        ):
            raise UnsupportedMemorySourceError("event type is not allowlisted")
        if event.session_id != session.session_id:
            raise InvalidCommittedSourceError("event session is not committed here")
        view = self.view_builder.build(
            case=case,
            player=player,
            session=session,
            source_sequence=event.sequence,
            source_revision=source_revision,
        )
        record = session.action_history[event.sequence - 1]
        if event.occurred_at != record.occurred_at:
            raise InvalidCommittedSourceError("event timestamp does not match committed action")

        if isinstance(event, InvestigationCompletedEvent):
            if (
                view.source_event_type
                is not MemorySourceEventType.INVESTIGATION_COMPLETED
                or event.investigation_id != record.reference_id
                or event.action_type != record.action_type
                or event.target_id != record.target_id
                or event.newly_discovered_clue_ids != record.revealed_clue_ids
            ):
                raise InvalidCommittedSourceError(
                    "investigation event does not match committed public action"
                )
        elif isinstance(event, DiagnosisSubmittedEvent):
            if (
                view.source_event_type is not MemorySourceEventType.DIAGNOSIS_SUBMITTED
                or event.diagnosis_id != record.reference_id
                or event.evidence_clue_ids != record.evidence_clue_ids
            ):
                raise InvalidCommittedSourceError(
                    "diagnosis event does not match committed public action"
                )
        else:
            # Deliberately validate only the public treatment identity. The raw event's
            # diagnosis_correct, score and outcome are never serialized or hashed.
            if (
                view.source_event_type is not MemorySourceEventType.TREATMENT_EXECUTED
                or event.treatment_id != record.reference_id
            ):
                raise InvalidCommittedSourceError(
                    "treatment event does not match committed public action"
                )
        return self.project_public_view(view)

    def project_committed_action(
        self,
        *,
        case: CaseDefinition,
        player: PlayerState,
        session: CaseSessionState,
        source_sequence: int,
        source_revision: int,
    ) -> tuple[VerifiedMemorySource, AuthoritativeMemoryRecord]:
        view = self.view_builder.build(
            case=case,
            player=player,
            session=session,
            source_sequence=source_sequence,
            source_revision=source_revision,
        )
        return self.project_public_view(view)

    def project_public_view(
        self,
        view: CommittedActionPublicView,
    ) -> tuple[VerifiedMemorySource, AuthoritativeMemoryRecord]:
        if view.source_event_type is MemorySourceEventType.INVESTIGATION_COMPLETED:
            payload = InvestigationPublicPayload(
                case_id=view.case_id,
                case_title=view.case_title,
                investigation_id=view.action_id,
                action_type=view.action_type,
                public_action_description=view.public_action_description,
                newly_discovered_clues=view.public_clues,
            )
        elif view.source_event_type is MemorySourceEventType.DIAGNOSIS_SUBMITTED:
            payload = DiagnosisPublicPayload(
                case_id=view.case_id,
                case_title=view.case_title,
                diagnosis_id=view.action_id,
                public_hypothesis_description=view.public_action_description,
                cited_evidence=view.public_clues,
            )
        elif view.source_event_type is MemorySourceEventType.TREATMENT_EXECUTED:
            if view.public_result is None:
                raise InvalidCommittedSourceError("public treatment result is missing")
            payload = TreatmentPublicPayload(
                case_id=view.case_id,
                case_title=view.case_title,
                treatment_id=view.action_id,
                public_action_description=view.public_action_description,
                public_result=view.public_result,
            )
        else:
            raise UnsupportedMemorySourceError("public source type is not allowlisted")

        source_event_id = stable_source_event_id(
            view.source_event_type.value,
            view.source_session_id,
            view.source_sequence,
        )
        payload_hash = sha256_hex(payload)
        source = VerifiedMemorySource(
            source_event_id=source_event_id,
            player_id=view.player_id,
            source_session_id=view.source_session_id,
            source_event_type=view.source_event_type,
            source_sequence=view.source_sequence,
            source_revision=view.source_revision,
            projection_version=self.projection_version,
            projection_ordinal=self.projection_ordinal,
            occurred_at=view.occurred_at,
            public_payload=payload,
            public_payload_hash=payload_hash,
        )
        return source, self.memory_from_verified_source(source)

    def memory_from_verified_source(
        self,
        source: VerifiedMemorySource,
    ) -> AuthoritativeMemoryRecord:
        """Recompute the only valid authoritative record from a public receipt."""

        payload = source.public_payload
        if isinstance(payload, InvestigationPublicPayload):
            memory_type = MemoryType.EPISODIC
            importance = 2
            write_reason = MemoryWriteReason.VERIFIED_CASE_INVESTIGATION
            clue_text = self._clue_text(
                payload.newly_discovered_clues,
                empty="未发现新线索",
            )
            content = (
                f"在病例“{payload.case_title}”中，玩家完成公开调查"
                f"“{payload.public_action_description}”（{payload.action_type.value}），"
                f"新发现：{clue_text}。"
            )
            action_id = payload.investigation_id
            public_clues = payload.newly_discovered_clues
            related_case_id = payload.case_id
        elif isinstance(payload, DiagnosisPublicPayload):
            memory_type = MemoryType.EPISODIC
            importance = 3
            write_reason = MemoryWriteReason.VERIFIED_DIAGNOSIS_SUBMISSION
            evidence_text = self._clue_text(payload.cited_evidence, empty="未引用证据")
            content = (
                f"在病例“{payload.case_title}”中，玩家提交过公开假设"
                f"“{payload.public_hypothesis_description}”，引用已发现证据："
                f"{evidence_text}。"
            )
            action_id = payload.diagnosis_id
            public_clues = payload.cited_evidence
            related_case_id = payload.case_id
        elif isinstance(payload, TreatmentPublicPayload):
            memory_type = MemoryType.LEARNING
            importance = 4
            write_reason = MemoryWriteReason.VERIFIED_TREATMENT_OBSERVATION
            content = (
                f"在病例“{payload.case_title}”中，玩家执行公开处置"
                f"“{payload.public_action_description}”。{payload.public_result}"
            )
            action_id = payload.treatment_id
            public_clues = ()
            related_case_id = payload.case_id
        else:
            raise UnsupportedMemorySourceError(
                "trusted correction sources are not automatic projections"
            )

        related_entities = frozenset(
            {action_id, *(item.clue_id for item in public_clues)}
        )
        content_hash = sha256_hex(
            authoritative_content_payload(
                memory_type=memory_type,
                content=content,
                importance=importance,
                related_case_id=related_case_id,
                related_entity_ids=related_entities,
            )
        )
        return AuthoritativeMemoryRecord(
            memory_id=stable_memory_id(
                source.player_id,
                source.source_event_id,
                source.projection_version,
                source.projection_ordinal,
            ),
            player_id=source.player_id,
            memory_type=memory_type,
            content=content,
            importance=importance,
            related_case_id=related_case_id,
            related_entity_ids=related_entities,
            relationship_impacts=(),
            occurred_at=source.occurred_at,
            source_event_id=source.source_event_id,
            source_session_id=source.source_session_id,
            source_event_type=source.source_event_type,
            source_sequence=source.source_sequence,
            source_revision=source.source_revision,
            projection_version=source.projection_version,
            projection_ordinal=source.projection_ordinal,
            write_reason=write_reason,
            public_payload_hash=source.public_payload_hash,
            content_hash=content_hash,
        )

    @staticmethod
    def _clue_text(clues: tuple[PublicClueFact, ...], *, empty: str) -> str:
        if not clues:
            return empty
        return "；".join(item.description for item in clues)
