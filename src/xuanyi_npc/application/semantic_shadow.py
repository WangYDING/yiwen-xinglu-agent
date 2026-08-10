"""Record-only semantic shadow observer with no Agent or state write path."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import ConfigDict, Field, StrictBool, StrictFloat

from xuanyi_npc.domain import CaseEvent
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText

from .multicase import MultiCaseServiceResult


class ShadowRetrievalStatus(str, Enum):
    READY = "ready"
    EMPTY = "empty"
    UNAVAILABLE = "shadow_unavailable"
    SAFETY_ERROR = "shadow_safety_error"


class ShadowQuery(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    player_id: Identifier
    source_session_id: Identifier
    case_id: Identifier
    case_title: NonEmptyText
    discovered_clue_descriptions: tuple[NonEmptyText, ...] = ()
    committed_event_types: tuple[NonEmptyText, ...] = ()


class ShadowCandidate(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    player_id: Identifier
    source_session_id: Identifier
    memory_id: Identifier
    similarity: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)]


class ShadowSearchResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ShadowRetrievalStatus
    embedding_space_id: NonEmptyText
    candidates: tuple[ShadowCandidate, ...] = ()
    error_code: Identifier | None = None


class ShadowSearchPort(Protocol):
    def search(self, query: ShadowQuery) -> ShadowSearchResult:
        """Return internal candidates for observation only."""


class SemanticShadowRecord(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    player_ref_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source_session_id: Identifier
    memory_id: Identifier | None = None
    similarity: Annotated[StrictFloat, Field(ge=-1.0, le=1.0)] | None = None
    retrieval_status: ShadowRetrievalStatus
    embedding_space_id: NonEmptyText
    current_episode_excluded: StrictBool = False
    shadow_error: Identifier | None = None
    injected_into_prompt: Literal[False] = False
    affected_action: Literal[False] = False
    affected_state: Literal[False] = False


class ShadowObservationResult(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ShadowRetrievalStatus
    records_written: Annotated[int, Field(ge=0)]
    eligible_candidate_count: Annotated[int, Field(ge=0)]
    shadow_error: Identifier | None = None


class SemanticShadowObserver(Protocol):
    def observe(
        self,
        public_result: MultiCaseServiceResult,
        committed_events: tuple[CaseEvent, ...],
    ) -> ShadowObservationResult:
        """Observe committed public state without changing official execution."""


class EmptyMockShadowSearch:
    """Deterministic offline P4a shadow backend; it is not semantic quality evidence."""

    calls = 0

    def search(self, query: ShadowQuery) -> ShadowSearchResult:
        del query
        self.calls += 1
        return ShadowSearchResult(
            status=ShadowRetrievalStatus.EMPTY,
            embedding_space_id="shadow_mock_v1",
        )


class RecordingSemanticShadowObserver:
    """Append sanitized JSONL records and always discard retrieval output."""

    def __init__(self, search: ShadowSearchPort, output_path: Path | str) -> None:
        self.search = search
        self.output_path = Path(output_path)

    def observe(
        self,
        public_result: MultiCaseServiceResult,
        committed_events: tuple[CaseEvent, ...],
    ) -> ShadowObservationResult:
        if not committed_events:
            return ShadowObservationResult(
                status=ShadowRetrievalStatus.EMPTY,
                records_written=0,
                eligible_candidate_count=0,
            )
        if (
            not public_result.ok
            or public_result.player_id is None
            or public_result.session_id is None
            or public_result.case_id is None
            or public_result.observation is None
        ):
            return self._safe_failure("shadow_context_unavailable")
        query = ShadowQuery(
            player_id=public_result.player_id,
            source_session_id=public_result.session_id,
            case_id=public_result.case_id,
            case_title=public_result.observation.title,
            discovered_clue_descriptions=tuple(
                clue.description
                for clue in public_result.observation.discovered_clues
            ),
            committed_event_types=tuple(
                event.event_type for event in committed_events
            ),
        )
        try:
            search_result = self.search.search(query)
        except Exception:
            return self._safe_failure("shadow_backend_unavailable", query=query)

        safe_candidates: list[ShadowCandidate] = []
        current_episode_excluded = False
        safety_error: str | None = None
        for candidate in search_result.candidates:
            if candidate.player_id != query.player_id:
                safety_error = "shadow_cross_player_candidate"
                continue
            if candidate.source_session_id == query.source_session_id:
                current_episode_excluded = True
                continue
            safe_candidates.append(candidate)

        if safety_error is not None:
            status = ShadowRetrievalStatus.SAFETY_ERROR
        elif safe_candidates:
            status = search_result.status
        elif search_result.status is ShadowRetrievalStatus.READY:
            status = ShadowRetrievalStatus.EMPTY
        else:
            status = search_result.status
        records = [
            self._record(
                query,
                search_result.embedding_space_id,
                status,
                candidate=candidate,
                current_episode_excluded=current_episode_excluded,
                error=safety_error or search_result.error_code,
            )
            for candidate in safe_candidates
        ]
        if not records:
            records = [
                self._record(
                    query,
                    search_result.embedding_space_id,
                    status,
                    current_episode_excluded=current_episode_excluded,
                    error=safety_error or search_result.error_code,
                )
            ]
        try:
            self._append(records)
        except OSError:
            return ShadowObservationResult(
                status=ShadowRetrievalStatus.UNAVAILABLE,
                records_written=0,
                eligible_candidate_count=0,
                shadow_error="shadow_record_unavailable",
            )
        return ShadowObservationResult(
            status=status,
            records_written=len(records),
            eligible_candidate_count=len(safe_candidates),
            shadow_error=safety_error or search_result.error_code,
        )

    def _safe_failure(
        self,
        error: str,
        *,
        query: ShadowQuery | None = None,
    ) -> ShadowObservationResult:
        records_written = 0
        if query is not None:
            record = self._record(
                query,
                "shadow_unavailable",
                ShadowRetrievalStatus.UNAVAILABLE,
                error=error,
            )
            try:
                self._append([record])
            except OSError:
                pass
            else:
                records_written = 1
        return ShadowObservationResult(
            status=ShadowRetrievalStatus.UNAVAILABLE,
            records_written=records_written,
            eligible_candidate_count=0,
            shadow_error=error,
        )

    @staticmethod
    def _record(
        query: ShadowQuery,
        space: str,
        status: ShadowRetrievalStatus,
        *,
        candidate: ShadowCandidate | None = None,
        current_episode_excluded: bool = False,
        error: str | None = None,
    ) -> SemanticShadowRecord:
        return SemanticShadowRecord(
            player_ref_sha256=hashlib.sha256(
                query.player_id.encode("utf-8")
            ).hexdigest(),
            source_session_id=query.source_session_id,
            memory_id=candidate.memory_id if candidate is not None else None,
            similarity=candidate.similarity if candidate is not None else None,
            retrieval_status=status,
            embedding_space_id=space,
            current_episode_excluded=current_episode_excluded,
            shadow_error=error,
        )

    def _append(self, records: list[SemanticShadowRecord]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("a", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(
                    json.dumps(
                        record.model_dump(mode="json"),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                handle.write("\n")
