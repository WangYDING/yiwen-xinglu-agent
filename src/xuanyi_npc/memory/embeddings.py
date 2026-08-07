"""Provider-neutral embedding contracts and deterministic offline fake vectors."""

from __future__ import annotations

import hashlib
import math
import re
import struct
import unicodedata
from datetime import datetime
from enum import Enum
from typing import Annotated, Protocol, runtime_checkable

from pydantic import AfterValidator, Field, StrictInt, field_validator, model_validator

from xuanyi_npc.domain.base import Identifier
from xuanyi_npc.domain.memory import MemoryType

from .canonical import normalize_utc
from .contracts import Sha256Hex, StrictMemoryModel
from .errors import (
    EmbeddingContractError,
    EmbeddingSpaceMismatchError,
    EmbeddingVectorError,
)


EMBEDDING_REQUEST_VERSION = "embedding_request_v1"
EMBEDDING_RESULT_VERSION = "embedding_result_v1"
MEMORY_RETRIEVAL_CONFIG_VERSION = "memory_retrieval_v1"
MEMORY_QUERY_TEMPLATE_VERSION = "memory_query_v1"
FAKE_EMBEDDING_ALGORITHM_VERSION = "fake_sha256_token_buckets_v1"
FAKE_EMBEDDING_DIMENSION = 64
FAKE_EMBEDDING_SPACE_ID = "fake_sha256_token_buckets_v1_d64"
MAX_EMBEDDING_TEXT_LENGTH = 4096
MAX_EMBEDDING_BATCH_SIZE = 256
MAX_EMBEDDING_DIMENSION = 4096

FiniteStrictFloat = Annotated[float, Field(strict=True)]
UtcDateTime = Annotated[datetime, AfterValidator(normalize_utc)]

_TOKEN_PATTERN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff]|[\w]+|[^\w\s]",
    flags=re.UNICODE,
)
_WHITESPACE_PATTERN = re.compile(r"\s+", flags=re.UNICODE)


def normalize_embedding_text(value: object) -> str:
    """Canonicalize public text before hashing or embedding."""

    if not isinstance(value, str):
        raise TypeError("embedding text must be a string")
    if len(value) > MAX_EMBEDDING_TEXT_LENGTH:
        raise ValueError("embedding text exceeds the maximum length")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized).strip()
    if not normalized:
        raise ValueError("embedding text must not be empty")
    if len(normalized) > MAX_EMBEDDING_TEXT_LENGTH:
        raise ValueError("normalized embedding text exceeds the maximum length")
    return normalized


def tokenize_embedding_text(normalized_text: str) -> tuple[str, ...]:
    """Tokenize already-normalized text with one platform-independent rule."""

    if normalize_embedding_text(normalized_text) != normalized_text:
        raise ValueError("embedding text must be normalized before tokenization")
    tokens = tuple(_TOKEN_PATTERN.findall(normalized_text))
    if not tokens:
        raise ValueError("embedding text produced no tokens")
    return tokens


def vector_l2_norm(vector: tuple[float, ...]) -> float:
    return math.sqrt(math.fsum(value * value for value in vector))


def validate_vector(
    vector: tuple[float, ...],
    *,
    dimension: int,
) -> float:
    if dimension < 1 or dimension > MAX_EMBEDDING_DIMENSION:
        raise EmbeddingVectorError("embedding dimension is outside the allowed range")
    if len(vector) != dimension:
        raise EmbeddingVectorError("embedding vector dimension does not match")
    if any(not math.isfinite(value) for value in vector):
        raise EmbeddingVectorError("embedding vector values must be finite")
    norm = vector_l2_norm(vector)
    if not math.isfinite(norm) or norm <= 0.0:
        raise EmbeddingVectorError("embedding vector must have a finite non-zero norm")
    return norm


def encode_float32_le(vector: tuple[float, ...]) -> bytes:
    """Encode a validated vector as deterministic little-endian float32."""

    validate_vector(vector, dimension=len(vector))
    try:
        encoded = struct.pack(f"<{len(vector)}f", *vector)
    except (OverflowError, struct.error) as exc:
        raise EmbeddingVectorError("embedding vector cannot be encoded as float32") from exc
    decoded = struct.unpack(f"<{len(vector)}f", encoded)
    if any(not math.isfinite(value) for value in decoded):
        raise EmbeddingVectorError("float32 encoding produced a non-finite value")
    return encoded


def decode_float32_le(blob: bytes, *, dimension: int) -> tuple[float, ...]:
    """Decode and validate a little-endian float32 vector."""

    if not isinstance(blob, bytes):
        raise EmbeddingVectorError("embedding BLOB must be bytes")
    if dimension < 1 or dimension > MAX_EMBEDDING_DIMENSION:
        raise EmbeddingVectorError("embedding dimension is outside the allowed range")
    if len(blob) != dimension * 4:
        raise EmbeddingVectorError("embedding BLOB length does not match dimension")
    try:
        vector = tuple(struct.unpack(f"<{dimension}f", blob))
    except struct.error as exc:
        raise EmbeddingVectorError("embedding BLOB is invalid") from exc
    validate_vector(vector, dimension=dimension)
    return vector


class EmbeddingRequestItem(StrictMemoryModel):
    item_id: Identifier
    text: str

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> str:
        return normalize_embedding_text(value)


class EmbeddingRequest(StrictMemoryModel):
    request_version: str = EMBEDDING_REQUEST_VERSION
    embedding_space_id: Identifier
    dimension: Annotated[StrictInt, Field(ge=1, le=MAX_EMBEDDING_DIMENSION)]
    items: tuple[EmbeddingRequestItem, ...] = Field(
        min_length=1,
        max_length=MAX_EMBEDDING_BATCH_SIZE,
    )

    @model_validator(mode="after")
    def require_unique_item_ids(self) -> "EmbeddingRequest":
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("embedding request item IDs must be unique")
        if self.request_version != EMBEDDING_REQUEST_VERSION:
            raise ValueError("embedding request version is unsupported")
        return self


class EmbeddedItem(StrictMemoryModel):
    item_id: Identifier
    vector: tuple[FiniteStrictFloat, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_finite_non_zero_vector(self) -> "EmbeddedItem":
        validate_vector(self.vector, dimension=len(self.vector))
        return self


class EmbeddingBatchResult(StrictMemoryModel):
    result_version: str = EMBEDDING_RESULT_VERSION
    embedding_space_id: Identifier
    dimension: Annotated[StrictInt, Field(ge=1, le=MAX_EMBEDDING_DIMENSION)]
    items: tuple[EmbeddedItem, ...] = Field(
        min_length=1,
        max_length=MAX_EMBEDDING_BATCH_SIZE,
    )

    @model_validator(mode="after")
    def validate_batch_shape(self) -> "EmbeddingBatchResult":
        if self.result_version != EMBEDDING_RESULT_VERSION:
            raise ValueError("embedding result version is unsupported")
        item_ids = [item.item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("embedding result item IDs must be unique")
        for item in self.items:
            validate_vector(item.vector, dimension=self.dimension)
        return self


@runtime_checkable
class EmbeddingAdapter(Protocol):
    @property
    def algorithm_version(self) -> str:
        """Return the immutable algorithm identity."""

    @property
    def embedding_space_id(self) -> str:
        """Return the vector-space identity."""

    @property
    def dimension(self) -> int:
        """Return the fixed vector dimension."""

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        """Embed a validated batch without changing persistent state."""


def validate_embedding_batch(
    request: EmbeddingRequest,
    result: EmbeddingBatchResult,
) -> None:
    if not isinstance(result, EmbeddingBatchResult):
        raise EmbeddingContractError("embedding adapter returned an invalid result type")
    if result.result_version != EMBEDDING_RESULT_VERSION:
        raise EmbeddingContractError("embedding result version is unsupported")
    if result.embedding_space_id != request.embedding_space_id:
        raise EmbeddingSpaceMismatchError("embedding result space does not match request")
    if result.dimension != request.dimension:
        raise EmbeddingContractError("embedding result dimension does not match request")
    requested_ids = tuple(item.item_id for item in request.items)
    returned_ids = tuple(item.item_id for item in result.items)
    if returned_ids != requested_ids:
        raise EmbeddingContractError(
            "embedding result count or item order does not match request"
        )
    for item in result.items:
        validate_vector(item.vector, dimension=result.dimension)


class DerivedEmbeddingRecord(StrictMemoryModel):
    memory_id: Identifier
    player_id: Identifier
    embedding_space_id: Identifier
    content_hash: Sha256Hex
    dimension: Annotated[StrictInt, Field(ge=1, le=MAX_EMBEDDING_DIMENSION)]
    vector: tuple[FiniteStrictFloat, ...] = Field(min_length=1)
    l2_norm: FiniteStrictFloat
    generated_at: UtcDateTime

    @model_validator(mode="after")
    def validate_derived_vector(self) -> "DerivedEmbeddingRecord":
        norm = validate_vector(self.vector, dimension=self.dimension)
        if self.l2_norm <= 0.0 or not math.isclose(
            self.l2_norm,
            norm,
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            raise ValueError("stored L2 norm does not match embedding vector")
        return self


class EmbeddingWriteDisposition(str, Enum):
    CREATED = "created"
    IDEMPOTENT = "idempotent"
    REBUILT = "rebuilt"


class EmbeddingWriteResult(StrictMemoryModel):
    memory_id: Identifier
    embedding_space_id: Identifier
    disposition: EmbeddingWriteDisposition


class MemoryIndexStatus(str, Enum):
    NO_ACTIVE_MEMORY = "no_active_memory"
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class MemoryIndexState(StrictMemoryModel):
    player_id: Identifier
    embedding_space_id: Identifier
    active_memory_count: Annotated[StrictInt, Field(ge=0)]
    valid_embedding_count: Annotated[StrictInt, Field(ge=0)]
    missing_memory_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    stale_memory_ids: tuple[Identifier, ...] = Field(default_factory=tuple)
    status: MemoryIndexStatus

    @model_validator(mode="after")
    def validate_index_state(self) -> "MemoryIndexState":
        if self.missing_memory_ids != tuple(sorted(set(self.missing_memory_ids))):
            raise ValueError("missing memory IDs must be unique and sorted")
        if self.stale_memory_ids != tuple(sorted(set(self.stale_memory_ids))):
            raise ValueError("stale memory IDs must be unique and sorted")
        if set(self.missing_memory_ids) & set(self.stale_memory_ids):
            raise ValueError("a memory cannot be both missing and stale")
        expected_status = (
            MemoryIndexStatus.NO_ACTIVE_MEMORY
            if self.active_memory_count == 0
            else (
                MemoryIndexStatus.COMPLETE
                if not self.missing_memory_ids
                and not self.stale_memory_ids
                and self.valid_embedding_count == self.active_memory_count
                else MemoryIndexStatus.INCOMPLETE
            )
        )
        if self.status is not expected_status:
            raise ValueError("memory index status does not match its counts")
        return self


class MemoryIndexBuildResult(StrictMemoryModel):
    player_id: Identifier
    embedding_space_id: Identifier
    active_memory_count: Annotated[StrictInt, Field(ge=0)]
    write_results: tuple[EmbeddingWriteResult, ...] = Field(default_factory=tuple)
    state: MemoryIndexState


class MemoryRetrievalConfig(StrictMemoryModel):
    config_version: str = MEMORY_RETRIEVAL_CONFIG_VERSION
    top_k: Annotated[StrictInt, Field(ge=1, le=20)]
    min_similarity: Annotated[float, Field(strict=True, ge=-1.0, le=1.0)]
    embedding_space_id: Identifier
    query_template_version: Identifier

    @model_validator(mode="after")
    def validate_config_version(self) -> "MemoryRetrievalConfig":
        if self.config_version != MEMORY_RETRIEVAL_CONFIG_VERSION:
            raise ValueError("memory retrieval config version is unsupported")
        if self.query_template_version != MEMORY_QUERY_TEMPLATE_VERSION:
            raise ValueError("memory query template version is unsupported")
        if not math.isfinite(self.min_similarity):
            raise ValueError("minimum similarity must be finite")
        return self


class InternalMemorySearchHit(StrictMemoryModel):
    memory_id: Identifier
    player_id: Identifier
    memory_type: MemoryType
    content: str
    content_hash: Sha256Hex
    source_session_id: Identifier
    occurred_at: UtcDateTime
    similarity: Annotated[float, Field(strict=True, ge=-1.0, le=1.0)]


class InternalMemorySearchResult(StrictMemoryModel):
    player_id: Identifier
    embedding_space_id: Identifier
    query_template_version: Identifier
    normalized_query: str
    index_state: MemoryIndexState
    hits: tuple[InternalMemorySearchHit, ...] = Field(default_factory=tuple)


class DeterministicFakeEmbedding:
    """Stable engineering fake; it does not claim semantic understanding."""

    algorithm_version = FAKE_EMBEDDING_ALGORITHM_VERSION
    embedding_space_id = FAKE_EMBEDDING_SPACE_ID
    dimension = FAKE_EMBEDDING_DIMENSION

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        if request.embedding_space_id != self.embedding_space_id:
            raise EmbeddingSpaceMismatchError("fake adapter space does not match request")
        if request.dimension != self.dimension:
            raise EmbeddingContractError("fake adapter dimension does not match request")
        items = tuple(
            EmbeddedItem(
                item_id=item.item_id,
                vector=self._embed_normalized(item.text),
            )
            for item in request.items
        )
        result = EmbeddingBatchResult(
            embedding_space_id=self.embedding_space_id,
            dimension=self.dimension,
            items=items,
        )
        validate_embedding_batch(request, result)
        return result

    @classmethod
    def _embed_normalized(cls, normalized_text: str) -> tuple[float, ...]:
        buckets = [0.0] * cls.dimension
        for token in tokenize_embedding_text(normalized_text):
            digest = hashlib.sha256(
                f"{cls.algorithm_version}\0{token}".encode("utf-8")
            ).digest()
            bucket = int.from_bytes(digest[:8], byteorder="big") % cls.dimension
            buckets[bucket] += 1.0
        norm = math.sqrt(math.fsum(value * value for value in buckets))
        if norm <= 0.0:
            raise EmbeddingVectorError("fake embedding produced a zero vector")
        return tuple(value / norm for value in buckets)
