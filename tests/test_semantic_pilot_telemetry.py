from __future__ import annotations

import ctypes
import sys
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from xuanyi_npc.evaluation import semantic_memory_runner
from xuanyi_npc.evaluation.semantic_memory_contracts import (
    SemanticRawRunResultV2,
    SemanticRunResourceMetrics,
)


class _FakeWindowsFunction:
    def __init__(self, implementation: Callable[..., Any]) -> None:
        self._implementation = implementation
        self.argtypes: tuple[type[object], ...] | None = None
        self.restype: type[object] | None = None
        self.calls: list[tuple[object, ...]] = []

    def __call__(self, *args: object) -> object:
        self.calls.append(args)
        return self._implementation(*args)


def _fake_windll(
    *,
    process_handle: int = 0x1_0000_0001,
    peak_working_set: int = 123_456_789,
    succeeds: bool = True,
) -> tuple[SimpleNamespace, _FakeWindowsFunction, _FakeWindowsFunction]:
    get_current_process = _FakeWindowsFunction(lambda: process_handle)

    def read_memory_info(
        received_handle: object,
        counters_pointer: object,
        size: object,
    ) -> int:
        assert received_handle == process_handle
        assert size == ctypes.sizeof(semantic_memory_runner._ProcessMemoryCounters)
        counters = ctypes.cast(
            counters_pointer,
            ctypes.POINTER(semantic_memory_runner._ProcessMemoryCounters),
        )
        counters.contents.PeakWorkingSetSize = peak_working_set
        return int(succeeds)

    get_process_memory_info = _FakeWindowsFunction(read_memory_info)
    windll = SimpleNamespace(
        kernel32=SimpleNamespace(GetCurrentProcess=get_current_process),
        psapi=SimpleNamespace(GetProcessMemoryInfo=get_process_memory_info),
    )
    return windll, get_current_process, get_process_memory_info


def test_peak_working_set_accepts_64_bit_windows_process_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windll, get_current_process, get_process_memory_info = _fake_windll()
    monkeypatch.setattr(semantic_memory_runner.ctypes, "windll", windll)

    assert semantic_memory_runner._peak_working_set_bytes() == 123_456_789
    assert get_current_process.restype is ctypes.c_void_p
    assert get_process_memory_info.calls[0][0] == 0x1_0000_0001


def test_peak_working_set_declares_windows_api_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windll, _, get_process_memory_info = _fake_windll()
    monkeypatch.setattr(semantic_memory_runner.ctypes, "windll", windll)

    semantic_memory_runner._peak_working_set_bytes()

    assert get_process_memory_info.argtypes == (
        ctypes.c_void_p,
        ctypes.POINTER(semantic_memory_runner._ProcessMemoryCounters),
        ctypes.c_ulong,
    )
    assert get_process_memory_info.restype is ctypes.c_int


def test_peak_working_set_reports_windows_api_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windll, _, _ = _fake_windll(succeeds=False)
    monkeypatch.setattr(semantic_memory_runner.ctypes, "windll", windll)

    with pytest.raises(RuntimeError, match="unable to read process peak memory"):
        semantic_memory_runner._peak_working_set_bytes()


@pytest.mark.skipif(sys.platform != "win32", reason="requires Windows process APIs")
def test_peak_working_set_reads_current_windows_process() -> None:
    assert semantic_memory_runner._peak_working_set_bytes() > 0


def test_semantic_run_resource_schema_is_unchanged() -> None:
    assert tuple(SemanticRunResourceMetrics.model_fields) == (
        "model_load_count",
        "local_embedding_batch_count",
        "local_embedding_text_count",
        "cold_load_ms",
        "first_batch_ms",
        "warm_batch_ms",
        "total_embedding_ms",
        "peak_process_working_set_bytes",
        "peak_cuda_allocated_bytes",
        "peak_cuda_reserved_bytes",
        "network_attempt_count",
        "api_request_count",
        "cost_cny",
    )
    assert SemanticRawRunResultV2.model_fields["resources"].annotation is (
        SemanticRunResourceMetrics
    )
