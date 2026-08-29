"""Run one network-blocked BGE-M3 smoke check without persisting vectors."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import socket
import time
from pathlib import Path
from typing import Any

from xuanyi_npc.memory import (
    BGE_M3_DIMENSION,
    BGE_M3_VERIFIED_MANIFEST_SHA256,
    BgeM3LocalEmbeddingAdapter,
    BgeM3LocalEmbeddingConfig,
    EmbeddingRequest,
    EmbeddingRequestItem,
    bge_m3_embedding_space_id,
    vector_l2_norm,
)


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _peak_working_set_bytes() -> int:
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    get_current_process = ctypes.windll.kernel32.GetCurrentProcess
    get_current_process.restype = ctypes.c_void_p
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    )
    get_process_memory_info.restype = ctypes.c_int
    process = get_current_process()
    ok = get_process_memory_info(
        process, ctypes.byref(counters), counters.cb
    )
    if not ok:
        raise RuntimeError("unable to read process peak memory")
    return int(counters.PeakWorkingSetSize)


def _vector_digest(vectors: tuple[tuple[float, ...], ...]) -> str:
    payload = json.dumps(vectors, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run(*, model_directory: Path, manifest_path: Path) -> dict[str, Any]:
    import torch

    if not torch.cuda.is_available():
        raise RuntimeError("configured CUDA device is unavailable")
    space_id = bge_m3_embedding_space_id(device="cuda", max_input_length=512)
    config = BgeM3LocalEmbeddingConfig(
        model_directory=model_directory.resolve(strict=True),
        manifest_path=manifest_path.resolve(strict=True),
        manifest_sha256=BGE_M3_VERIFIED_MANIFEST_SHA256,
        device="cuda",
        max_input_length=512,
        batch_size=3,
        embedding_space_id=space_id,
    )
    request = EmbeddingRequest(
        embedding_space_id=space_id,
        dimension=BGE_M3_DIMENSION,
        items=(
            EmbeddingRequestItem(
                item_id="smoke_zh", text="玩家曾在雨夜检查过旧纸伞。"
            ),
            EmbeddingRequestItem(
                item_id="smoke_en", text="The investigator returned the wooden token."
            ),
            EmbeddingRequestItem(
                item_id="smoke_mixed", text="道医 memory：遵守已验证的历史边界。"
            ),
        ),
    )
    attempts: list[str] = []
    original_create_connection = socket.create_connection
    original_connect = socket.socket.connect

    def blocked_create_connection(*args: object, **kwargs: object) -> None:
        attempts.append("create_connection")
        raise AssertionError("network is forbidden during offline model load")

    def blocked_connect(*args: object, **kwargs: object) -> None:
        attempts.append("socket_connect")
        raise AssertionError("network is forbidden during offline model load")

    socket.create_connection = blocked_create_connection
    socket.socket.connect = blocked_connect
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    torch.cuda.reset_peak_memory_stats()
    try:
        adapter = BgeM3LocalEmbeddingAdapter(config=config)
        load_started = time.perf_counter()
        adapter.load()
        load_ms = (time.perf_counter() - load_started) * 1000
        first_started = time.perf_counter()
        first = adapter.embed(request)
        torch.cuda.synchronize()
        first_ms = (time.perf_counter() - first_started) * 1000
        warm_started = time.perf_counter()
        second = adapter.embed(request)
        torch.cuda.synchronize()
        warm_ms = (time.perf_counter() - warm_started) * 1000
    finally:
        socket.create_connection = original_create_connection
        socket.socket.connect = original_connect
    first_vectors = tuple(item.vector for item in first.items)
    second_vectors = tuple(item.vector for item in second.items)
    max_abs_difference = max(
        abs(left - right)
        for left, right in zip(
            (value for vector in first_vectors for value in vector),
            (value for vector in second_vectors for value in vector),
            strict=True,
        )
    )
    norms = tuple(vector_l2_norm(vector) for vector in first_vectors)
    if attempts:
        raise RuntimeError("offline smoke attempted a network connection")
    if any(len(vector) != BGE_M3_DIMENSION for vector in first_vectors):
        raise RuntimeError("local model returned the wrong dimension")
    if any(not math.isfinite(value) for vector in first_vectors for value in vector):
        raise RuntimeError("local model returned a non-finite value")
    if any(not math.isclose(norm, 1.0, rel_tol=1e-6, abs_tol=1e-6) for norm in norms):
        raise RuntimeError("local model returned a non-normalized vector")
    return {
        "adapter_version": adapter.algorithm_version,
        "embedding_space_id": adapter.embedding_space_id,
        "dimension": adapter.dimension,
        "device": "cuda",
        "precision": "fp32",
        "batch_size": 3,
        "max_input_length": 512,
        "vector_count": len(first_vectors),
        "norms": norms,
        "max_abs_difference": max_abs_difference,
        "first_vector_batch_sha256": _vector_digest(first_vectors),
        "second_vector_batch_sha256": _vector_digest(second_vectors),
        "cold_load_ms": load_ms,
        "first_inference_ms": first_ms,
        "warm_inference_ms": warm_ms,
        "peak_process_working_set_bytes": _peak_working_set_bytes(),
        "peak_cuda_allocated_bytes": int(torch.cuda.max_memory_allocated()),
        "peak_cuda_reserved_bytes": int(torch.cuda.max_memory_reserved()),
        "network_attempt_count": len(attempts),
        "hf_hub_offline": os.environ.get("HF_HUB_OFFLINE"),
        "transformers_offline": os.environ.get("TRANSFORMERS_OFFLINE"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(model_directory=args.model_directory, manifest_path=args.manifest)
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
