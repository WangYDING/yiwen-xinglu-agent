from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.memory import (
    BGE_M3_ADAPTER_VERSION,
    BGE_M3_DIMENSION,
    BGE_M3_REPOSITORY_ID,
    BGE_M3_REVISION,
    BgeM3LocalEmbeddingAdapter,
    BgeM3LocalEmbeddingConfig,
    DeterministicFakeEmbedding,
    EmbeddingRequest,
    EmbeddingRequestItem,
    EmbeddingVectorError,
    FAKE_EMBEDDING_SPACE_ID,
    LocalEmbeddingConfigurationError,
    LocalEmbeddingInferenceError,
    LocalEmbeddingModelError,
    bge_m3_embedding_space_id,
    sha256_hex,
    vector_l2_norm,
)
from xuanyi_npc.memory.local_bge import BGE_M3_REQUIRED_FILES


class RecordingBackend:
    def __init__(self, vectors: list[list[float]]) -> None:
        self.vectors = vectors
        self.calls: list[tuple[tuple[str, ...], int]] = []

    def encode(self, texts: tuple[str, ...], *, batch_size: int) -> list[list[float]]:
        self.calls.append((texts, batch_size))
        return self.vectors


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * BGE_M3_DIMENSION
    vector[index] = 2.0
    return vector


def _model_fixture(tmp_path: Path) -> tuple[Path, Path, str]:
    model_directory = tmp_path / "model"
    contents: dict[str, bytes] = {
        path: f"fixture:{path}".encode("utf-8") for path in BGE_M3_REQUIRED_FILES
    }
    contents["modules.json"] = json.dumps(
        [
            {
                "idx": 0,
                "name": "0",
                "path": "",
                "type": "sentence_transformers.models.Transformer",
            },
            {
                "idx": 1,
                "name": "1",
                "path": "1_Pooling",
                "type": "sentence_transformers.models.Pooling",
            },
            {
                "idx": 2,
                "name": "2",
                "path": "2_Normalize",
                "type": "sentence_transformers.models.Normalize",
            },
        ],
        separators=(",", ":"),
    ).encode("utf-8")
    files: list[dict[str, object]] = []
    for relative in BGE_M3_REQUIRED_FILES:
        path = model_directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents[relative])
        files.append(
            {
                "path": relative,
                "size_bytes": len(contents[relative]),
                "sha256": hashlib.sha256(contents[relative]).hexdigest(),
            }
        )
    payload = {
        "manifest_version": "bge_m3_verified_manifest_v1",
        "repository_id": BGE_M3_REPOSITORY_ID,
        "revision": BGE_M3_REVISION,
        "mode": "dense_only",
        "precision": "fp32",
        "dimension": BGE_M3_DIMENSION,
        "trust_remote_code": False,
        "total_bytes": sum(item["size_bytes"] for item in files),
        "files": files,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return model_directory, manifest_path, sha256_hex(payload)


def _config(tmp_path: Path, **updates: object) -> BgeM3LocalEmbeddingConfig:
    model_directory, manifest_path, manifest_sha256 = _model_fixture(tmp_path)
    values: dict[str, object] = {
        "model_directory": model_directory,
        "manifest_path": manifest_path,
        "manifest_sha256": manifest_sha256,
        "device": "cuda",
        "max_input_length": 512,
        "batch_size": 2,
        "embedding_space_id": bge_m3_embedding_space_id(
            device="cuda", max_input_length=512
        ),
    }
    values.update(updates)
    return BgeM3LocalEmbeddingConfig(**values)


def _request(config: BgeM3LocalEmbeddingConfig) -> EmbeddingRequest:
    return EmbeddingRequest(
        embedding_space_id=config.embedding_space_id,
        dimension=BGE_M3_DIMENSION,
        items=(
            EmbeddingRequestItem(item_id="item_one", text="道医 记忆"),
            EmbeddingRequestItem(item_id="item_two", text="wooden token"),
        ),
    )


def test_local_config_is_strict_and_freezes_model_identity(tmp_path: Path) -> None:
    config = _config(tmp_path)

    assert config.repository_id == BGE_M3_REPOSITORY_ID
    assert config.revision == BGE_M3_REVISION
    assert config.adapter_version == BGE_M3_ADAPTER_VERSION
    assert config.dimension == BGE_M3_DIMENSION
    assert config.precision == "fp32"
    assert config.dense_only is True
    assert config.local_files_only is True
    assert config.trust_remote_code is False
    with pytest.raises(ValidationError):
        _config(tmp_path / "bad_extra", unknown="forbidden")
    with pytest.raises(ValidationError):
        _config(tmp_path / "bad_revision", revision="main")
    with pytest.raises(ValidationError):
        _config(tmp_path / "bad_remote", trust_remote_code=True)
    with pytest.raises(ValidationError):
        _config(tmp_path / "bad_space", embedding_space_id="wrong_space")


def test_adapter_is_lazy_and_preserves_count_order_dimension_and_norm(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    backend = RecordingBackend([_unit_vector(0), _unit_vector(1)])
    factories: list[BgeM3LocalEmbeddingConfig] = []

    def factory(received: BgeM3LocalEmbeddingConfig) -> RecordingBackend:
        factories.append(received)
        return backend

    adapter = BgeM3LocalEmbeddingAdapter(config=config, backend_factory=factory)
    assert not adapter.is_loaded
    assert factories == []
    with pytest.raises(LocalEmbeddingModelError):
        adapter.embed(_request(config))

    adapter.load()
    adapter.load()
    result = adapter.embed(_request(config))

    assert adapter.is_loaded
    assert factories == [config]
    assert backend.calls == [(('道医 记忆', 'wooden token'), 2)]
    assert tuple(item.item_id for item in result.items) == ("item_one", "item_two")
    assert all(len(item.vector) == BGE_M3_DIMENSION for item in result.items)
    assert all(vector_l2_norm(item.vector) == pytest.approx(1.0) for item in result.items)
    assert result.items[0].vector[0] == 1.0
    assert result.items[1].vector[1] == 1.0
    assert "usage" not in result.model_dump(mode="json")


@pytest.mark.parametrize(
    "vectors,error_type",
    [
        ([[_unit_vector(0)[0]]], EmbeddingVectorError),
        ([[0.0] * BGE_M3_DIMENSION, [0.0] * BGE_M3_DIMENSION], EmbeddingVectorError),
        ([[math.nan] + [0.0] * (BGE_M3_DIMENSION - 1), _unit_vector(1)], EmbeddingVectorError),
        ([[_unit_vector(0)[0]] * BGE_M3_DIMENSION], LocalEmbeddingInferenceError),
    ],
)
def test_adapter_rejects_invalid_backend_results(
    tmp_path: Path,
    vectors: list[list[float]],
    error_type: type[Exception],
) -> None:
    config = _config(tmp_path)
    adapter = BgeM3LocalEmbeddingAdapter(
        config=config,
        backend_factory=lambda _: RecordingBackend(vectors),
    )
    adapter.load()
    with pytest.raises(error_type):
        adapter.embed(_request(config))


def test_manifest_hash_inventory_and_model_hash_mismatches_are_rejected(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    backend = RecordingBackend([_unit_vector(0), _unit_vector(1)])

    wrong_manifest = config.model_copy(update={"manifest_sha256": "0" * 64})
    with pytest.raises(LocalEmbeddingConfigurationError):
        BgeM3LocalEmbeddingAdapter(
            config=wrong_manifest, backend_factory=lambda _: backend
        ).load()

    extra_file = config.model_directory / "pytorch_model.bin"
    extra_file.write_bytes(b"forbidden")
    with pytest.raises(LocalEmbeddingModelError):
        BgeM3LocalEmbeddingAdapter(
            config=config, backend_factory=lambda _: backend
        ).load()
    extra_file.unlink()

    (config.model_directory / "model.safetensors").write_bytes(b"changed")
    with pytest.raises(LocalEmbeddingModelError):
        BgeM3LocalEmbeddingAdapter(
            config=config, backend_factory=lambda _: backend
        ).load()


def test_unapproved_sentence_transformer_module_is_rejected(tmp_path: Path) -> None:
    config = _config(tmp_path)
    modules_path = config.model_directory / "modules.json"
    payload = json.loads(modules_path.read_text(encoding="utf-8"))
    payload[0]["type"] = "remote.CustomModel"
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    modules_path.write_bytes(encoded)
    manifest = json.loads(config.manifest_path.read_text(encoding="utf-8"))
    module_record = next(item for item in manifest["files"] if item["path"] == "modules.json")
    module_record["size_bytes"] = len(encoded)
    module_record["sha256"] = hashlib.sha256(encoded).hexdigest()
    manifest["total_bytes"] = sum(item["size_bytes"] for item in manifest["files"])
    config.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    config = config.model_copy(update={"manifest_sha256": sha256_hex(manifest)})

    with pytest.raises(LocalEmbeddingModelError):
        BgeM3LocalEmbeddingAdapter(
            config=config,
            backend_factory=lambda _: RecordingBackend([_unit_vector(0)]),
        ).load()


def test_backend_load_failure_is_mapped_to_safe_local_error(tmp_path: Path) -> None:
    config = _config(tmp_path)

    def failing_factory(_: BgeM3LocalEmbeddingConfig) -> RecordingBackend:
        raise RuntimeError("private backend detail")

    with pytest.raises(LocalEmbeddingModelError) as captured:
        BgeM3LocalEmbeddingAdapter(
            config=config,
            backend_factory=failing_factory,
        ).load()

    assert "private backend detail" not in str(captured.value)


def test_fake_embedding_space_is_unchanged() -> None:
    assert DeterministicFakeEmbedding.embedding_space_id == FAKE_EMBEDDING_SPACE_ID
    assert FAKE_EMBEDDING_SPACE_ID == "fake_sha256_token_buckets_v1_d64"
    assert bge_m3_embedding_space_id(
        device="cuda", max_input_length=512
    ) != FAKE_EMBEDDING_SPACE_ID


def test_local_module_import_has_no_model_env_file_or_network_side_effect(
    tmp_path: Path,
) -> None:
    script = """
import os
import socket
import sys
from pathlib import Path

def forbidden(*args, **kwargs):
    raise AssertionError("forbidden import side effect")

socket.create_connection = forbidden
socket.socket.connect = forbidden
before_files = tuple(Path.cwd().iterdir())
before_env = dict(os.environ)
import xuanyi_npc.memory.local_bge
after_files = tuple(Path.cwd().iterdir())
assert "torch" not in sys.modules
assert "sentence_transformers" not in sys.modules
assert before_files == after_files == ()
assert before_env == dict(os.environ)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert tuple(tmp_path.iterdir()) == ()
