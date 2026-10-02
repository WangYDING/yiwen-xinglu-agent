"""Versioned public-only retrieval text representations for M4.5-P2c."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Literal

from pydantic import ConfigDict, StrictStr, model_validator

from xuanyi_npc.domain.base import DomainModel

from .contracts import (
    AuthoritativeMemoryRecord,
    CorrectionPublicPayload,
    DiagnosisPublicPayload,
    InvestigationPublicPayload,
    TreatmentPublicPayload,
    VerifiedMemorySource,
)


RETRIEVAL_QUERY_V2 = "retrieval_query_v2"
EMBEDDING_DOCUMENT_V1 = "embedding_document_v1"
EMBEDDING_DOCUMENT_V2 = "embedding_document_v2"
SEMANTIC_NORMALIZATION_V2 = "nfkc_casefold_ws_v2"
SEMANTIC_TRUNCATION_V2 = "unicode_codepoint_prefix_v2"
MAX_RETRIEVAL_QUERY_V2_LENGTH = 2048
MAX_EMBEDDING_DOCUMENT_V2_LENGTH = 4096
_WHITESPACE = re.compile(r"\s+", flags=re.UNICODE)


class SemanticRepresentationError(ValueError):
    """A public representation could not be built safely."""


def normalize_semantic_text_v2(value: object, *, max_length: int) -> str:
    """Freeze NFKC, casefold, whitespace and code-point prefix truncation."""

    if not isinstance(value, str):
        raise SemanticRepresentationError("semantic representation fields must be strings")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _WHITESPACE.sub(" ", normalized).strip()
    if not normalized:
        raise SemanticRepresentationError("semantic representation text must not be empty")
    if len(normalized) > max_length:
        normalized = normalized[:max_length].rstrip()
    if not normalized:
        raise SemanticRepresentationError("semantic representation truncation was empty")
    return normalized


class EmbeddingDocument(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    version: Literal["embedding_document_v1", "embedding_document_v2"]
    text: StrictStr
    text_sha256: StrictStr

    @model_validator(mode="after")
    def require_hash(self) -> "EmbeddingDocument":
        expected = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.text_sha256 != expected:
            raise ValueError("embedding document text hash does not match")
        return self


class EmbeddingDocumentV1Builder:
    version = EMBEDDING_DOCUMENT_V1
    requires_source = False

    def build(
        self,
        *,
        memory: AuthoritativeMemoryRecord,
        source: VerifiedMemorySource | None = None,
    ) -> EmbeddingDocument:
        del source
        text = normalize_semantic_text_v2(
            memory.content,
            max_length=MAX_EMBEDDING_DOCUMENT_V2_LENGTH,
        )
        return EmbeddingDocument(
            version=self.version,
            text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )


class EmbeddingDocumentV2Builder:
    """Derive discriminative text from a verified public receipt, never authority IDs."""

    version = EMBEDDING_DOCUMENT_V2
    requires_source = True

    def build(
        self,
        *,
        memory: AuthoritativeMemoryRecord,
        source: VerifiedMemorySource | None,
    ) -> EmbeddingDocument:
        if source is None:
            raise SemanticRepresentationError(
                "embedding document v2 requires a verified public source"
            )
        if (
            source.player_id != memory.player_id
            or source.source_event_id != memory.source_event_id
            or source.source_session_id != memory.source_session_id
            or source.public_payload_hash != memory.public_payload_hash
        ):
            raise SemanticRepresentationError(
                "embedding document source does not match authority"
            )
        payload = source.public_payload
        if isinstance(payload, InvestigationPublicPayload):
            parts = [payload.public_action_description]
            if payload.newly_discovered_clues:
                parts.extend(
                    (
                        "发现",
                        "；".join(
                            self._fragment(item.description)
                            for item in payload.newly_discovered_clues
                        ),
                    )
                )
        elif isinstance(payload, DiagnosisPublicPayload):
            parts = [
                "玩家曾提交假设",
                payload.public_hypothesis_description,
            ]
            if payload.cited_evidence:
                parts.extend(
                    (
                        "引用证据",
                        "；".join(
                            self._fragment(item.description)
                            for item in payload.cited_evidence
                        ),
                    )
                )
        elif isinstance(payload, TreatmentPublicPayload):
            parts = [
                payload.public_action_description,
                "可观察结果",
                payload.public_result,
            ]
        elif isinstance(payload, CorrectionPublicPayload):
            if memory.content != payload.replacement_public_content:
                raise SemanticRepresentationError(
                    "active correction content does not match its public receipt"
                )
            parts = [payload.replacement_public_content]
        else:  # pragma: no cover - discriminated union is closed by Pydantic
            raise SemanticRepresentationError("unsupported public memory source")
        text = normalize_semantic_text_v2(
            "。".join(self._fragment(part) for part in parts),
            max_length=MAX_EMBEDDING_DOCUMENT_V2_LENGTH,
        )
        return EmbeddingDocument(
            version=self.version,
            text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )

    @staticmethod
    def _fragment(value: str) -> str:
        return value.strip().rstrip("。.!?！？；;：:，,")
