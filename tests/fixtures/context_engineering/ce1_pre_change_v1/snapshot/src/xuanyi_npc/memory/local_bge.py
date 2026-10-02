"""Lazy, offline-only BGE-M3 dense adapter for the frozen M4.5-P1 model."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Annotated, Literal, Protocol

from pydantic import Field, StrictInt, StringConstraints, field_validator, model_validator

from xuanyi_npc.domain.base import Identifier

from .canonical import sha256_hex
from .contracts import Sha256Hex, StrictMemoryModel
from .embeddings import (
    EmbeddingBatchResult,
    EmbeddedItem,
    EmbeddingRequest,
    validate_embedding_batch,
    validate_vector,
    vector_l2_norm,
)
from .errors import (
    EmbeddingContractError,
    EmbeddingSpaceMismatchError,
    EmbeddingVectorError,
    LocalEmbeddingConfigurationError,
    LocalEmbeddingInferenceError,
    LocalEmbeddingModelError,
)


BGE_M3_REPOSITORY_ID = "BAAI/bge-m3"
BGE_M3_REVISION = "142964af7e05de16511657561de8e8750fc153a0"
BGE_M3_ADAPTER_VERSION = "bge_m3_sentence_transformers_v1"
BGE_M3_DIMENSION = 1024
BGE_M3_VERIFIED_MANIFEST_SHA256 = (
    "d4ee3716bb6c6c5dd850ea0cf1d64f0218aed9cfbbc52a6e8061f439a05965a4"
)
BGE_M3_REQUIRED_FILES = (
    "1_Pooling/config.json",
    "README.md",
    "config.json",
    "config_sentence_transformers.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
BGE_M3_ALLOWED_MODULE_TYPES = (
    "sentence_transformers.models.Normalize",
    "sentence_transformers.models.Pooling",
    "sentence_transformers.models.Transformer",
)

ManifestPath = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=200),
]


def bge_m3_embedding_space_id(
    *,
    device: str,
    max_input_length: int,
    representation_version: str = "legacy_v1",
) -> str:
    if device not in {"cpu", "cuda"}:
        raise ValueError("BGE-M3 device identity is unsupported")
    if max_input_length < 1 or max_input_length > 8192:
        raise ValueError("BGE-M3 maximum input length is outside the supported range")
    if representation_version == "legacy_v1":
        return (
            "bge_m3_142964af7e05_dense_fp32_"
            f"d{BGE_M3_DIMENSION}_{device}_l{max_input_length}_v1"
        )
    if representation_version == "retrieval_v2":
        return (
            "bge_m3_142964af_dense_fp32_"
            f"d{BGE_M3_DIMENSION}_{device}_l{max_input_length}_rq2_doc2_v1"
        )
    raise ValueError("BGE-M3 representation identity is unsupported")


class BgeM3VerifiedFile(StrictMemoryModel):
    path: ManifestPath
    size_bytes: Annotated[StrictInt, Field(ge=1)]
    sha256: Sha256Hex

    @field_validator("path")
    @classmethod
    def require_safe_relative_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("manifest path must be a safe POSIX relative path")
        return value


class BgeM3VerifiedManifest(StrictMemoryModel):
    manifest_version: Literal["bge_m3_verified_manifest_v1"]
    repository_id: Literal["BAAI/bge-m3"]
    revision: Literal["142964af7e05de16511657561de8e8750fc153a0"]
    mode: Literal["dense_only"]
    precision: Literal["fp32"]
    dimension: Literal[1024]
    trust_remote_code: Literal[False]
    total_bytes: Annotated[StrictInt, Field(ge=1)]
    files: tuple[BgeM3VerifiedFile, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_frozen_inventory(self) -> "BgeM3VerifiedManifest":
        paths = tuple(item.path for item in self.files)
        if paths != BGE_M3_REQUIRED_FILES:
            raise ValueError("verified manifest file inventory is not the frozen whitelist")
        if sum(item.size_bytes for item in self.files) != self.total_bytes:
            raise ValueError("verified manifest byte total is inconsistent")
        return self


class BgeM3LocalEmbeddingConfig(StrictMemoryModel):
    model_directory: Path
    manifest_path: Path
    manifest_sha256: Sha256Hex
    repository_id: Literal["BAAI/bge-m3"] = BGE_M3_REPOSITORY_ID
    revision: Literal["142964af7e05de16511657561de8e8750fc153a0"] = BGE_M3_REVISION
    device: Literal["cuda", "cpu"]
    precision: Literal["fp32"] = "fp32"
    dimension: Literal[1024] = BGE_M3_DIMENSION
    max_input_length: Annotated[StrictInt, Field(ge=1, le=8192)]
    batch_size: Annotated[StrictInt, Field(ge=1, le=64)]
    adapter_version: Literal["bge_m3_sentence_transformers_v1"] = (
        BGE_M3_ADAPTER_VERSION
    )
    representation_version: Literal["legacy_v1", "retrieval_v2"] = "legacy_v1"
    embedding_space_id: Identifier
    dense_only: Literal[True] = True
    local_files_only: Literal[True] = True
    trust_remote_code: Literal[False] = False

    @model_validator(mode="after")
    def require_space_identity(self) -> "BgeM3LocalEmbeddingConfig":
        expected = bge_m3_embedding_space_id(
            device=self.device,
            max_input_length=self.max_input_length,
            representation_version=self.representation_version,
        )
        if self.embedding_space_id != expected:
            raise ValueError("embedding space ID does not match the local model identity")
        return self


class DenseEmbeddingBackend(Protocol):
    def encode(
        self,
        texts: tuple[str, ...],
        *,
        batch_size: int,
    ) -> Sequence[Sequence[float]]: ...


BackendFactory = Callable[[BgeM3LocalEmbeddingConfig], DenseEmbeddingBackend]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bge_m3_model_files(
    config: BgeM3LocalEmbeddingConfig,
) -> BgeM3VerifiedManifest:
    """Verify the committed manifest and every local model file before loading."""

    manifest_path = config.manifest_path.resolve()
    model_directory = config.model_directory.resolve()
    if not manifest_path.is_file():
        raise LocalEmbeddingConfigurationError("verified model manifest is unavailable")
    try:
        manifest = BgeM3VerifiedManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise LocalEmbeddingConfigurationError(
            "verified model manifest is invalid"
        ) from exc
    if sha256_hex(manifest) != config.manifest_sha256:
        raise LocalEmbeddingConfigurationError("verified model manifest hash does not match")
    if (
        manifest.repository_id != config.repository_id
        or manifest.revision != config.revision
        or manifest.dimension != config.dimension
        or manifest.precision != config.precision
        or manifest.trust_remote_code is not config.trust_remote_code
    ):
        raise LocalEmbeddingConfigurationError(
            "verified model manifest does not match adapter configuration"
        )
    if not model_directory.is_dir():
        raise LocalEmbeddingModelError("local model directory is unavailable")
    try:
        actual_paths = tuple(
            sorted(
                path.relative_to(model_directory).as_posix()
                for path in model_directory.rglob("*")
                if path.is_file()
            )
        )
    except OSError as exc:
        raise LocalEmbeddingModelError("local model inventory cannot be read") from exc
    if actual_paths != BGE_M3_REQUIRED_FILES:
        raise LocalEmbeddingModelError("local model inventory is not the frozen whitelist")
    for item in manifest.files:
        path = model_directory / Path(item.path)
        try:
            matches = path.stat().st_size == item.size_bytes and _sha256_file(path) == item.sha256
        except OSError as exc:
            raise LocalEmbeddingModelError("local model file cannot be read") from exc
        if not matches:
            raise LocalEmbeddingModelError("local model file verification failed")
    _verify_safe_sentence_transformer_modules(model_directory / "modules.json")
    return manifest


def _verify_safe_sentence_transformer_modules(path: Path) -> None:
    try:
        modules = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise LocalEmbeddingModelError("local model module definition is invalid") from exc
    if not isinstance(modules, list) or not modules:
        raise LocalEmbeddingModelError("local model module definition is invalid")
    module_types = tuple(sorted(item.get("type") for item in modules if isinstance(item, dict)))
    if module_types != BGE_M3_ALLOWED_MODULE_TYPES:
        raise LocalEmbeddingModelError("local model requests an unapproved module type")


class _SentenceTransformerBackend:
    def __init__(self, model: object) -> None:
        self._model = model

    def encode(
        self,
        texts: tuple[str, ...],
        *,
        batch_size: int,
    ) -> Sequence[Sequence[float]]:
        return self._model.encode(  # type: ignore[no-any-return, union-attr]
            list(texts),
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
            precision="float32",
        )


def _load_sentence_transformer_backend(
    config: BgeM3LocalEmbeddingConfig,
) -> DenseEmbeddingBackend:
    """Import large ML dependencies only at the explicit load boundary."""

    previous_hf_offline = os.environ.get("HF_HUB_OFFLINE")
    previous_transformers_offline = os.environ.get("TRANSFORMERS_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        import torch
        from sentence_transformers import SentenceTransformer

        if config.device == "cuda" and not torch.cuda.is_available():
            raise LocalEmbeddingModelError("configured CUDA device is unavailable")
        model = SentenceTransformer(
            str(config.model_directory.resolve()),
            device=config.device,
            trust_remote_code=False,
            local_files_only=True,
            model_kwargs={"dtype": torch.float32},
            backend="torch",
        )
        model.max_seq_length = config.max_input_length
        return _SentenceTransformerBackend(model)
    except LocalEmbeddingModelError:
        raise
    except Exception as exc:
        raise LocalEmbeddingModelError("local embedding model failed to load") from exc
    finally:
        if previous_hf_offline is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previous_hf_offline
        if previous_transformers_offline is None:
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
        else:
            os.environ["TRANSFORMERS_OFFLINE"] = previous_transformers_offline


class BgeM3LocalEmbeddingAdapter:
    """Explicitly loaded, dense-only local adapter with no silent fallback."""

    def __init__(
        self,
        *,
        config: BgeM3LocalEmbeddingConfig,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.config = config
        self._backend_factory = backend_factory or _load_sentence_transformer_backend
        self._backend: DenseEmbeddingBackend | None = None

    @property
    def algorithm_version(self) -> str:
        return self.config.adapter_version

    @property
    def embedding_space_id(self) -> str:
        return self.config.embedding_space_id

    @property
    def dimension(self) -> int:
        return self.config.dimension

    @property
    def is_loaded(self) -> bool:
        return self._backend is not None

    def load(self) -> None:
        if self._backend is not None:
            return
        verify_bge_m3_model_files(self.config)
        try:
            backend = self._backend_factory(self.config)
        except LocalEmbeddingModelError:
            raise
        except Exception as exc:
            raise LocalEmbeddingModelError("local embedding model failed to load") from exc
        if backend is None or not callable(getattr(backend, "encode", None)):
            raise LocalEmbeddingModelError("local embedding backend is invalid")
        self._backend = backend

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        if self._backend is None:
            raise LocalEmbeddingModelError("local embedding model is not loaded")
        if request.embedding_space_id != self.embedding_space_id:
            raise EmbeddingSpaceMismatchError("local adapter space does not match request")
        if request.dimension != self.dimension:
            raise EmbeddingContractError("local adapter dimension does not match request")
        try:
            raw_vectors = self._backend.encode(
                tuple(item.text for item in request.items),
                batch_size=self.config.batch_size,
            )
            vectors = tuple(_normalize_backend_vector(vector) for vector in raw_vectors)
        except (EmbeddingVectorError, LocalEmbeddingInferenceError):
            raise
        except Exception as exc:
            raise LocalEmbeddingInferenceError("local embedding inference failed") from exc
        if len(vectors) != len(request.items):
            raise LocalEmbeddingInferenceError(
                "local embedding result count does not match request"
            )
        result = EmbeddingBatchResult(
            embedding_space_id=self.embedding_space_id,
            dimension=self.dimension,
            items=tuple(
                EmbeddedItem(item_id=item.item_id, vector=vector)
                for item, vector in zip(request.items, vectors, strict=True)
            ),
        )
        validate_embedding_batch(request, result)
        return result


def _normalize_backend_vector(vector: Sequence[float]) -> tuple[float, ...]:
    try:
        values = tuple(float(value) for value in vector)
    except (TypeError, ValueError) as exc:
        raise LocalEmbeddingInferenceError(
            "local embedding backend returned a non-numeric vector"
        ) from exc
    validate_vector(values, dimension=BGE_M3_DIMENSION)
    norm = vector_l2_norm(values)
    normalized = tuple(value / norm for value in values)
    if any(not math.isfinite(value) for value in normalized):
        raise EmbeddingVectorError("local embedding normalization produced invalid values")
    validate_vector(normalized, dimension=BGE_M3_DIMENSION)
    return normalized
