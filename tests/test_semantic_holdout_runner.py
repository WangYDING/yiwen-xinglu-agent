from __future__ import annotations

import hashlib
import json
import math
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

from xuanyi_npc.evaluation.semantic_holdout_contracts import (
    HoldoutCandidateSetup,
    HoldoutScenarioExpectation,
    HoldoutSplit,
    HoldoutSuiteExpectation,
)
from xuanyi_npc.evaluation.semantic_holdout_runner import (
    DEFAULT_GOLD,
    GOLD_FREEZE_COMMIT,
    HoldoutGoldGate,
    HoldoutRunnerError,
    RecordingCachingAdapter,
    _blocked_network,
    _canonical_model_manifest_sha256,
    _prepare_scenario,
    _public_view,
    _query_text,
    _search,
    _temporary_run_root,
    compare_holdout_runs,
    execute_holdout,
    load_frozen_holdout,
    main,
)
from xuanyi_npc.memory.embeddings import (
    EmbeddingBatchResult,
    EmbeddedItem,
    EmbeddingRequest,
    normalize_embedding_text,
)
from xuanyi_npc.memory.errors import MemoryIndexIncompleteError
from xuanyi_npc.memory.projection import DeterministicMemoryProjector
from xuanyi_npc.memory.representations import EmbeddingDocumentV2Builder


class FrozenScoreAdapter:
    algorithm_version = "holdout_fixed_scores_v1"

    def __init__(self, *, vectors: dict[str, tuple[float, ...]], space_id: str) -> None:
        self.vectors = vectors
        self.embedding_space_id = space_id
        self.dimension = len(next(iter(vectors.values())))
        self.calls = 0

    def embed(self, request: EmbeddingRequest) -> EmbeddingBatchResult:
        self.calls += 1
        return EmbeddingBatchResult(
            embedding_space_id=self.embedding_space_id,
            dimension=self.dimension,
            items=tuple(
                EmbeddedItem(
                    item_id=item.item_id,
                    vector=self.vectors[normalize_embedding_text(item.text)],
                )
                for item in request.items
            ),
        )


def _normalized_document(candidate) -> str:
    if candidate.setup is HoldoutCandidateSetup.CORRECTED_ACTIVE:
        assert candidate.replacement_public_content is not None
        return normalize_embedding_text(candidate.replacement_public_content)
    source, memory = DeterministicMemoryProjector().project_public_view(
        _public_view(candidate)
    )
    return normalize_embedding_text(
        EmbeddingDocumentV2Builder().build(memory=memory, source=source).text
    )


def _perfect_delegate():
    suite, config, manifest = load_frozen_holdout()
    gold = HoldoutSuiteExpectation.model_validate_json(
        DEFAULT_GOLD.read_text(encoding="utf-8")
    )
    gold_by_id = {item.scenario_id: item for item in gold.scenarios}
    dimension = len(suite.scenarios) + 1
    vectors: dict[str, tuple[float, ...]] = {}
    for index, scenario in enumerate(suite.scenarios):
        query = [0.0] * dimension
        query[index] = 1.0
        vectors[normalize_embedding_text(_query_text(scenario))] = tuple(query)
        expectation = gold_by_id[scenario.scenario_id]
        relevant = set(expectation.relevant_candidate_ids)
        for candidate in scenario.candidates:
            if candidate.setup not in {
                HoldoutCandidateSetup.ACTIVE,
                HoldoutCandidateSetup.CORRECTED_ACTIVE,
            }:
                continue
            if candidate.source.player_id != scenario.player_id:
                continue
            if candidate.source.source_session_id == scenario.current_session_id:
                continue
            similarity = 0.95 if candidate.candidate_id in relevant else 0.2
            vector = [0.0] * dimension
            vector[index] = similarity
            vector[-1] = math.sqrt(1.0 - similarity * similarity)
            text = _normalized_document(candidate)
            assert text not in vectors
            vectors[text] = tuple(vector)
    return suite, config, manifest, FrozenScoreAdapter(
        vectors=vectors, space_id=config.embedding_space_id
    )


def _gate(manifest, suite) -> HoldoutGoldGate:
    return HoldoutGoldGate(
        path=DEFAULT_GOLD,
        expected_sha256=manifest.expectation_sha256,
        suite_id=suite.suite_id,
    )


def test_missing_confirmation_stops_before_torch_or_runner(monkeypatch, tmp_path: Path) -> None:
    called = False

    def forbidden(**kwargs):
        nonlocal called
        called = True
        raise AssertionError(kwargs)

    monkeypatch.setattr(
        "xuanyi_npc.evaluation.semantic_holdout_runner.run_local_bge", forbidden
    )
    torch_before = sys.modules.get("torch")
    with pytest.raises(SystemExit):
        main(
            (
                "--run-id",
                "missing_confirm",
                "--freeze-commit",
                "0" * 40,
                "--output",
                str(tmp_path / "out.json"),
            )
        )
    assert called is False
    assert sys.modules.get("torch") is torch_before


def test_gold_gate_hides_final_until_policy_lock() -> None:
    suite, config, manifest = load_frozen_holdout()
    gate = _gate(manifest, suite)
    calibration = gate.calibration(config.calibration_scenario_ids)
    assert tuple(item.scenario_id for item in calibration.scenarios) == config.calibration_scenario_ids
    with pytest.raises(HoldoutRunnerError, match="before calibration"):
        gate.final_test(config.final_test_scenario_ids)


def test_full_holdout_uses_product_paths_and_calibration_only_selection(tmp_path: Path) -> None:
    suite, config, manifest, delegate = _perfect_delegate()
    recording = RecordingCachingAdapter(delegate)
    gate = _gate(manifest, suite)
    result = execute_holdout(
        run_id="offline_holdout",
        execution_commit="1" * 40,
        suite=suite,
        config=config,
        manifest=manifest,
        gold_gate=gate,
        adapter=recording,
        temporary_root=tmp_path,
    )

    assert result.status == "completed"
    assert len(result.scenarios) == 36
    assert sum(item.split is HoldoutSplit.CALIBRATION for item in result.scenarios) == 12
    assert sum(item.split is HoldoutSplit.FINAL_TEST for item in result.scenarios) == 24
    assert result.selected_policy is not None
    assert len(result.calibration_policy_outcomes) == 36
    # This intentionally exercises the frozen selector as written. Its conservative
    # tie-break selects one result with a margin after the hard calibration gates.
    assert result.selected_policy.parameter.max_results == 1
    assert result.selected_policy.parameter.minimum_margin == 0.06
    assert result.final_test_evaluation_count == 1
    assert gate.final_access_count == 1
    assert result.final_test_metrics is not None
    assert result.final_test_metrics.recall_at_1 == 0.95
    assert result.final_test_metrics.recall_at_3 == 1.0
    assert result.final_test_metrics.micro_false_positive == 0
    assert result.final_test_metrics.micro_false_negative == 4
    assert result.final_test_metrics.empty_accuracy == 1.0
    assert result.safety_counts.total == 0
    assert result.admission is not None and result.admission.single_run_quality_passed
    assert delegate.calls == len(recording.call_latencies_ms)
    assert any(path.name == "memory.sqlite3" for path in tmp_path.rglob("*"))


def test_fail_calibration_never_opens_or_evaluates_final(tmp_path: Path) -> None:
    suite, config, manifest, delegate = _perfect_delegate()
    dimension = delegate.dimension
    same = tuple(1.0 / math.sqrt(dimension) for _ in range(dimension))
    delegate.vectors = {key: same for key in delegate.vectors}
    gate = _gate(manifest, suite)
    result = execute_holdout(
        run_id="offline_fail_calibration",
        execution_commit="2" * 40,
        suite=suite,
        config=config,
        manifest=manifest,
        gold_gate=gate,
        adapter=RecordingCachingAdapter(delegate),
        temporary_root=tmp_path,
    )
    assert result.status == "fail_calibration"
    assert result.final_test_metrics is None
    assert result.final_test_evaluation_count == 0
    assert gate.final_access_count == 0


def test_lifecycle_filters_all_five_safety_reasons_before_ranking(tmp_path: Path) -> None:
    suite, config, manifest, delegate = _perfect_delegate()
    result = execute_holdout(
        run_id="offline_lifecycle",
        execution_commit="3" * 40,
        suite=suite,
        config=config,
        manifest=manifest,
        gold_gate=_gate(manifest, suite),
        adapter=RecordingCachingAdapter(delegate),
        temporary_root=tmp_path,
    )
    observed = {
        reason.value
        for scenario in result.scenarios
        for _, reason in scenario.safety_excluded
    }
    assert observed == {
        "cross_player",
        "current_episode",
        "superseded",
        "invalidated",
        "hard_deleted",
    }
    assert all(
        not ({candidate for candidate, _ in scenario.safety_excluded} & set(scenario.ranked_candidate_ids))
        for scenario in result.scenarios
    )


def test_repeat_comparator_checks_policy_order_metrics_and_vectors(tmp_path: Path) -> None:
    suite, config, manifest, delegate = _perfect_delegate()
    first = execute_holdout(
        run_id="offline_repeat_1",
        execution_commit="4" * 40,
        suite=suite,
        config=config,
        manifest=manifest,
        gold_gate=_gate(manifest, suite),
        adapter=RecordingCachingAdapter(delegate),
        temporary_root=tmp_path / "one",
    )
    _, _, _, delegate_two = _perfect_delegate()
    second = execute_holdout(
        run_id="offline_repeat_2",
        execution_commit="4" * 40,
        suite=suite,
        config=config,
        manifest=manifest,
        gold_gate=_gate(manifest, suite),
        adapter=RecordingCachingAdapter(delegate_two),
        temporary_root=tmp_path / "two",
    )
    comparison = compare_holdout_runs(first, second)
    assert comparison.passed_repeatability_gate
    assert comparison.max_vector_abs_difference == 0.0


def test_network_block_records_and_rejects_socket_attempt() -> None:
    with _blocked_network() as attempts:
        with pytest.raises(HoldoutRunnerError, match="network"):
            socket = __import__("socket")
            socket.create_connection(("example.invalid", 443))
    assert attempts == ["socket"]


def test_temporary_sqlite_and_state_root_is_removed() -> None:
    held: Path | None = None
    with _temporary_run_root("cleanup_contract") as root:
        held = root
        (root / "probe" / "state").mkdir(parents=True)
        (root / "probe" / "memory.sqlite3").write_bytes(b"temporary")
        assert root.exists()
    assert held is not None and not held.exists()


def test_incomplete_index_is_an_error_not_an_empty_result(tmp_path: Path) -> None:
    suite, config, _, delegate = _perfect_delegate()
    scenario = suite.scenarios[0]
    recording = RecordingCachingAdapter(delegate)
    prepared = _prepare_scenario(
        scenario=scenario,
        adapter=recording,
        database_path=tmp_path / "memory.sqlite3",
    )
    prepared.repository.delete_embeddings(
        player_id=scenario.player_id,
        embedding_space_id=config.embedding_space_id,
    )
    with pytest.raises(MemoryIndexIncompleteError):
        _search(prepared, recording, config.parameter_grid[0])


def test_cuda_unavailable_stops_without_loading_bge(monkeypatch, tmp_path: Path) -> None:
    suite, config, manifest = load_frozen_holdout()
    monkeypatch.setattr(
        "xuanyi_npc.evaluation.semantic_holdout_runner._validate_execution_identity",
        lambda freeze_commit, output_path: (suite, config, manifest),
    )
    fake_torch = SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: False,
            reset_peak_memory_stats=lambda: None,
        )
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    from xuanyi_npc.evaluation.semantic_holdout_runner import run_local_bge

    with pytest.raises(HoldoutRunnerError, match="CUDA"):
        run_local_bge(
            run_id="cpu_fallback_forbidden",
            freeze_commit="5" * 40,
            output_path=tmp_path / "out.json",
        )


def test_runner_is_independent_of_observed_15_case_entry_and_frozen_files_unchanged() -> None:
    source = Path(
        "src/xuanyi_npc/evaluation/semantic_holdout_runner.py"
    ).read_text(encoding="utf-8")
    assert "semantic_memory_runner" not in source
    assert "semantic_memory_diagnostics" not in source
    assert "m45_semantic_gold_inputs.json" not in source
    assert GOLD_FREEZE_COMMIT == "98d08eef52bfb164f454bd50c08c0d3feab1bb26"
    _, _, manifest = load_frozen_holdout()
    assert hashlib.sha256(DEFAULT_GOLD.read_bytes()).hexdigest() == manifest.expectation_sha256
    assert _canonical_model_manifest_sha256(
        Path("config/model_manifests/bge_m3_142964af7e05_dense_fp32_verified.json")
    ) == "d4ee3716bb6c6c5dd850ea0cf1d64f0218aed9cfbbc52a6e8061f439a05965a4"


def test_result_schema_keeps_undefined_denominators_and_strict_fields() -> None:
    empty = HoldoutScenarioExpectation(
        scenario_id="empty_contract",
        relevant_candidate_ids=(),
        semantic_negative_candidate_ids=(
            "empty_candidate_1",
            "empty_candidate_2",
            "empty_candidate_3",
            "empty_candidate_4",
        ),
        expected_empty=True,
    )
    assert empty.expected_empty
    raw = json.loads(empty.model_dump_json())
    raw["unknown"] = 1
    with pytest.raises(ValueError):
        HoldoutScenarioExpectation.model_validate(raw)
