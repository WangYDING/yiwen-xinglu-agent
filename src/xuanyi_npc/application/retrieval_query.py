"""Public-only, versioned query text for V1 semantic retrieval."""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

from pydantic import ConfigDict, StrictStr, model_validator

from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.memory.representations import (
    MAX_RETRIEVAL_QUERY_V2_LENGTH,
    RETRIEVAL_QUERY_V2,
    SemanticRepresentationError,
    normalize_semantic_text_v2,
)

from .views import CaseObservation


_WHITESPACE = re.compile(r"\s+", flags=re.UNICODE)


class RetrievalQueryV2(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    version: Literal["retrieval_query_v2"] = RETRIEVAL_QUERY_V2
    text: StrictStr

    @model_validator(mode="after")
    def require_canonical_text(self) -> "RetrievalQueryV2":
        if self.text != normalize_semantic_text_v2(
            self.text,
            max_length=MAX_RETRIEVAL_QUERY_V2_LENGTH,
        ):
            raise ValueError("retrieval query v2 text must be canonical")
        return self


class RetrievalQueryV2Builder:
    """Embed only explicit intent and discovered public clue descriptions.

    The public case title is deliberately omitted because titles are often decorative
    and repeated. The full safe observation and fixed lesson remain in the Agent input.
    """

    version = RETRIEVAL_QUERY_V2

    def build(
        self,
        *,
        current_user_message: str,
        case_observation: CaseObservation,
        fixed_lesson: str,
    ) -> RetrievalQueryV2:
        if not isinstance(case_observation, CaseObservation):
            raise SemanticRepresentationError(
                "case observation must be a filtered public view"
            )
        if not isinstance(fixed_lesson, str):
            raise SemanticRepresentationError("fixed lesson must be a string")
        fields: list[str] = []
        intent = self._optional(current_user_message)
        if intent:
            fields.append(intent)
        clues = tuple(
            normalized
            for clue in case_observation.discovered_clues
            if (normalized := self._optional(clue.description))
        )
        if clues:
            fields.append("已发现线索：" + "；".join(clues))
        if not fields:
            raise SemanticRepresentationError(
                "retrieval query v2 requires public intent or discovered clues"
            )
        return RetrievalQueryV2(
            text=normalize_semantic_text_v2(
                "\n".join(fields),
                max_length=MAX_RETRIEVAL_QUERY_V2_LENGTH,
            )
        )

    @staticmethod
    def _optional(value: object) -> str:
        if not isinstance(value, str):
            raise SemanticRepresentationError(
                "semantic representation fields must be strings"
            )
        normalized = unicodedata.normalize("NFKC", value).casefold()
        return _WHITESPACE.sub(" ", normalized).strip()
