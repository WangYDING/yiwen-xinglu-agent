from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.memory import (
    DeterministicFakeEmbedding,
    EmbeddedItem,
    EmbeddingBatchResult,
    EmbeddingContractError,
    EmbeddingRequest,
    EmbeddingRequestItem,
    EmbeddingSpaceMismatchError,
    EmbeddingVectorError,
    FAKE_EMBEDDING_DIMENSION,
    FAKE_EMBEDDING_SPACE_ID,
    MemoryRetrievalConfig,
    decode_float32_le,
    encode_float32_le,
    normalize_embedding_text,
    tokenize_embedding_text,
    validate_embedding_batch,
    vector_l2_norm,
)


def request_for(*texts: str) -> EmbeddingRequest:
    return EmbeddingRequest(
        embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
        dimension=FAKE_EMBEDDING_DIMENSION,
        items=tuple(
            EmbeddingRequestItem(item_id=f"item_{index}", text=text)
            for index, text in enumerate(texts)
        ),
    )


def test_embedding_contracts_forbid_unknown_fields_and_invalid_text() -> None:
    with pytest.raises(ValidationError):
        EmbeddingRequestItem(item_id="item_1", text="valid", hidden="no")
    with pytest.raises(ValidationError):
        EmbeddingRequestItem(item_id="item_1", text="  \n\t ")
    with pytest.raises(ValidationError):
        EmbeddingRequestItem(item_id="item_1", text="x" * 4097)
    with pytest.raises(ValidationError):
        EmbeddingRequest(
            embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
            dimension=FAKE_EMBEDDING_DIMENSION,
            items=(EmbeddingRequestItem(item_id="same", text="one"),
                   EmbeddingRequestItem(item_id="same", text="two")),
        )


def test_normalization_and_tokenization_are_fixed_for_chinese_words_and_punctuation() -> None:
    normalized = normalize_embedding_text("  ＡBC\t道医，  Dao-YI! \n")

    assert normalized == "abc 道医, dao-yi!"
    assert tokenize_embedding_text(normalized) == (
        "abc",
        "道",
        "医",
        ",",
        "dao",
        "-",
        "yi",
        "!",
    )


def test_fake_embedding_is_normalized_stable_and_has_no_usage_metrics() -> None:
    adapter = DeterministicFakeEmbedding()
    result = adapter.embed(request_for("木牌 承诺 木牌"))

    assert len(result.items[0].vector) == FAKE_EMBEDDING_DIMENSION
    assert vector_l2_norm(result.items[0].vector) == pytest.approx(1.0)
    assert result == adapter.embed(request_for("木牌 承诺 木牌"))
    payload = result.model_dump(mode="json")
    assert "usage" not in payload
    assert set(payload) == {
        "result_version",
        "embedding_space_id",
        "dimension",
        "items",
    }
    assert all("usage" not in item for item in payload["items"])


def test_fake_embedding_batch_order_does_not_change_each_text_vector() -> None:
    adapter = DeterministicFakeEmbedding()
    first = adapter.embed(request_for("道医问诊", "wooden token"))
    reversed_request = EmbeddingRequest(
        embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
        dimension=FAKE_EMBEDDING_DIMENSION,
        items=(
            EmbeddingRequestItem(item_id="item_1", text="wooden token"),
            EmbeddingRequestItem(item_id="item_0", text="道医问诊"),
        ),
    )
    reversed_result = adapter.embed(reversed_request)
    vectors = {item.item_id: item.vector for item in reversed_result.items}

    assert first.items[0].vector == vectors["item_0"]
    assert first.items[1].vector == vectors["item_1"]
    assert first.items[0].vector == adapter.embed(request_for("道医问诊")).items[0].vector


def test_fake_embedding_is_identical_in_a_fresh_process() -> None:
    local = DeterministicFakeEmbedding().embed(request_for("道医, memory!"))
    code = (
        "import json; "
        "from xuanyi_npc.memory import (DeterministicFakeEmbedding, "
        "EmbeddingRequest, EmbeddingRequestItem, FAKE_EMBEDDING_DIMENSION, "
        "FAKE_EMBEDDING_SPACE_ID); "
        "r=EmbeddingRequest(embedding_space_id=FAKE_EMBEDDING_SPACE_ID, "
        "dimension=FAKE_EMBEDDING_DIMENSION, items=(EmbeddingRequestItem("
        "item_id='item_0', text='道医, memory!'),)); "
        "print(json.dumps(DeterministicFakeEmbedding().embed(r).items[0].vector))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert tuple(json.loads(completed.stdout)) == local.items[0].vector


def test_validate_batch_rejects_count_order_dimension_space_and_bad_vectors() -> None:
    request = request_for("one", "two")
    adapter = DeterministicFakeEmbedding()
    valid = adapter.embed(request)

    wrong_space = valid.model_copy(update={"embedding_space_id": "other_space"})
    with pytest.raises(EmbeddingSpaceMismatchError):
        validate_embedding_batch(request, wrong_space)
    wrong_version = valid.model_copy(update={"result_version": "future_result"})
    with pytest.raises(EmbeddingContractError):
        validate_embedding_batch(request, wrong_version)
    wrong_dimension = valid.model_copy(update={"dimension": 63})
    with pytest.raises(EmbeddingContractError):
        validate_embedding_batch(request, wrong_dimension)
    wrong_order = valid.model_copy(update={"items": tuple(reversed(valid.items))})
    with pytest.raises(EmbeddingContractError):
        validate_embedding_batch(request, wrong_order)
    missing = valid.model_copy(update={"items": valid.items[:1]})
    with pytest.raises(EmbeddingContractError):
        validate_embedding_batch(request, missing)

    for bad in (
        (math.nan,) + valid.items[0].vector[1:],
        (math.inf,) + valid.items[0].vector[1:],
        (-math.inf,) + valid.items[0].vector[1:],
        (0.0,) * FAKE_EMBEDDING_DIMENSION,
    ):
        malformed = EmbeddingBatchResult.model_construct(
            embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
            dimension=FAKE_EMBEDDING_DIMENSION,
            items=(EmbeddedItem.model_construct(item_id="item_0", vector=bad),),
            result_version="embedding_result_v1",
        )
        with pytest.raises((EmbeddingContractError, EmbeddingVectorError)):
            validate_embedding_batch(request_for("one"), malformed)


def test_little_endian_float32_round_trip_and_validation() -> None:
    vector = (1.0, -0.5, 0.25)
    blob = encode_float32_le(vector)

    assert blob == struct.pack("<3f", *vector)
    assert decode_float32_le(blob, dimension=3) == vector
    with pytest.raises(EmbeddingVectorError):
        decode_float32_le(blob[:-1], dimension=3)
    with pytest.raises(EmbeddingVectorError):
        decode_float32_le(struct.pack("<2f", math.nan, 1.0), dimension=2)
    with pytest.raises(EmbeddingVectorError):
        decode_float32_le(struct.pack("<2f", 0.0, 0.0), dimension=2)


def test_fake_adapter_rejects_a_different_space_or_dimension() -> None:
    adapter = DeterministicFakeEmbedding()
    with pytest.raises(EmbeddingSpaceMismatchError):
        adapter.embed(request_for("valid").model_copy(update={"embedding_space_id": "x"}))
    with pytest.raises(EmbeddingContractError):
        adapter.embed(request_for("valid").model_copy(update={"dimension": 32}))


@pytest.mark.parametrize("top_k", [0, 21])
def test_retrieval_config_is_strict_and_bounded(top_k: int) -> None:
    with pytest.raises(ValidationError):
        MemoryRetrievalConfig(
            top_k=top_k,
            min_similarity=0.0,
            embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
            query_template_version="memory_query_v1",
        )
    with pytest.raises(ValidationError):
        MemoryRetrievalConfig(
            top_k=1,
            min_similarity=0.0,
            embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
            query_template_version="memory_query_v1",
            unknown="forbidden",
        )
    for minimum in (-1.01, 1.01, math.nan, math.inf):
        with pytest.raises(ValidationError):
            MemoryRetrievalConfig(
                top_k=1,
                min_similarity=minimum,
                embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
                query_template_version="memory_query_v1",
            )
    with pytest.raises(ValidationError):
        MemoryRetrievalConfig(
            top_k=1,
            min_similarity=-1.0,
            embedding_space_id=FAKE_EMBEDDING_SPACE_ID,
            query_template_version="future_query_template",
        )


def test_p2_module_import_has_no_file_env_or_network_side_effect(tmp_path: Path) -> None:
    script = """
import socket
from pathlib import Path
import dotenv

def forbidden(*args, **kwargs):
    raise AssertionError("forbidden import side effect")

socket.create_connection = forbidden
socket.socket.connect = forbidden
dotenv.load_dotenv = forbidden
before = tuple(Path.cwd().iterdir())
import xuanyi_npc.memory.embeddings
import xuanyi_npc.application.memory_retrieval
after = tuple(Path.cwd().iterdir())
assert before == after == ()
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert tuple(tmp_path.iterdir()) == ()
