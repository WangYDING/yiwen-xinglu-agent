from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from xuanyi_npc.evaluation.memory_contracts import (
    REQUIRED_MEMORY_GOLD_SCENARIOS,
    MemoryEvaluationFailureCategory,
    MemoryEvaluationReport,
)
from xuanyi_npc.evaluation.memory_runner import (
    _safe_failure_result,
    load_memory_gold,
    run_memory_gold_suite,
)
from xuanyi_npc.memory.embeddings import (
    FAKE_EMBEDDING_ALGORITHM_VERSION,
    FAKE_EMBEDDING_DIMENSION,
    FAKE_EMBEDDING_SPACE_ID,
)
from xuanyi_npc.storage import MEMORY_SCHEMA_VERSION


@pytest.fixture(scope="module")
def memory_report() -> MemoryEvaluationReport:
    return run_memory_gold_suite()


def result_by_id(report: MemoryEvaluationReport, scenario_id: str):
    return next(item for item in report.scenarios if item.scenario_id == scenario_id)


def test_all_fourteen_gold_scenarios_pass_twice_with_stable_hash(
    memory_report: MemoryEvaluationReport,
) -> None:
    assert tuple(item.scenario_id for item in memory_report.scenarios) == (
        REQUIRED_MEMORY_GOLD_SCENARIOS
    )
    assert memory_report.all_scenarios_passed is True
    assert memory_report.reproducible is True
    assert memory_report.deterministic_run_hashes[0] == (
        memory_report.deterministic_run_hashes[1]
    )
    assert all(item.passed for item in memory_report.scenarios)
    assert all(item.safe_reason_code is None for item in memory_report.scenarios)
    assert all(len(item.logical_snapshot_sha256) == 64 for item in memory_report.scenarios)


def test_aggregate_metrics_use_explicit_denominators_and_zero_rules(
    memory_report: MemoryEvaluationReport,
) -> None:
    aggregate = memory_report.aggregate_metrics
    assert aggregate.macro_precision == 1.0
    assert aggregate.macro_recall == 1.0
    assert aggregate.macro_f1 == 1.0
    assert aggregate.macro_precision_scenarios == 11
    assert aggregate.macro_recall_scenarios == 11
    assert aggregate.macro_f1_scenarios == 11
    assert aggregate.micro_true_positive == 13
    assert aggregate.micro_false_positive == 0
    assert aggregate.micro_false_negative == 0
    assert aggregate.micro_precision == 1.0
    assert aggregate.micro_recall == 1.0
    assert aggregate.micro_f1 == 1.0
    assert aggregate.false_memory_numerator == 0
    assert aggregate.false_memory_denominator == 13
    assert aggregate.false_memory_rate == 0.0
    assert aggregate.empty_correct_scenarios == 3

    empty = result_by_id(memory_report, "memory_empty_001").metrics
    assert empty.precision is None
    assert empty.recall is None
    assert empty.f1 is None
    assert empty.false_memory_rate is None
    assert empty.false_memory_denominator == 0
    assert empty.empty_correct is True
    assert result_by_id(memory_report, "memory_empty_001").index_status == (
        "no_active_memory"
    )
    assert result_by_id(
        memory_report, "memory_irrelevant_exclusion_001"
    ).index_status == "complete"


def test_all_memory_safety_hard_gates_are_zero(
    memory_report: MemoryEvaluationReport,
) -> None:
    assert memory_report.safety_totals.total == 0
    assert all(result.safety_counts.total == 0 for result in memory_report.scenarios)


def test_current_episode_player_lifecycle_and_stable_order_gold(
    memory_report: MemoryEvaluationReport,
) -> None:
    relevant = result_by_id(memory_report, "memory_relevant_recall_001")
    isolation = result_by_id(memory_report, "memory_player_isolation_001")
    lifecycle = result_by_id(memory_report, "memory_invalidation_deletion_001")
    tie = result_by_id(memory_report, "memory_stable_tie_001")

    assert relevant.metrics.ordered_recalled_memory_ids == (
        "mem_721175891fee519f93569e6a4dd8844c",
    )
    assert isolation.metrics.ordered_recalled_memory_ids == (
        "mem_721175891fee519f93569e6a4dd8844c",
    )
    assert lifecycle.metrics.ordered_recalled_memory_ids == (
        "mem_b80e86f97e405db5b525aff5f4faa5db",
    )
    assert lifecycle.observed_control_errors == (
        MemoryEvaluationFailureCategory.PROJECTION_NOT_ALLOWED,
    )
    assert tie.metrics.ordered_recalled_memory_ids == tuple(
        sorted(tie.metrics.ordered_recalled_memory_ids)
    )


def test_control_rejections_are_not_counted_as_safety_violations(
    memory_report: MemoryEvaluationReport,
) -> None:
    idempotent = result_by_id(
        memory_report, "memory_projection_idempotency_001"
    )
    conflict = result_by_id(memory_report, "memory_projection_conflict_001")
    readonly = result_by_id(memory_report, "memory_v1_readonly_001")
    recovery = result_by_id(memory_report, "memory_commit_window_recovery_001")

    assert idempotent.projection_counts.created_count == 1
    assert idempotent.projection_counts.idempotent_count == 1
    assert idempotent.projection_counts.source_receipt_count == 1
    assert idempotent.projection_counts.authoritative_memory_count == 1
    assert conflict.observed_control_errors == (
        MemoryEvaluationFailureCategory.PROJECTION_CONFLICT,
    )
    assert conflict.projection_counts.conflict_count == 1
    assert readonly.observed_control_errors == (
        MemoryEvaluationFailureCategory.ILLEGAL_PERMANENT_WRITE,
    )
    assert readonly.safety_counts.illegal_permanent_write == 0
    assert readonly.projection_counts.authoritative_memory_count == 1
    assert readonly.projection_counts.indexed_memory_count == 1
    assert recovery.projection_counts.created_count == 1
    assert recovery.projection_counts.idempotent_count == 1
    assert recovery.lifecycle_statuses[:3] == (
        "memory_projection_pending",
        "complete",
        "complete",
    )
    assert recovery.lifecycle_statuses[3] == "missing_state_rejected"


def test_v0_isolation_prompt_injection_and_rebuild_boundaries(
    memory_report: MemoryEvaluationReport,
) -> None:
    v0 = result_by_id(memory_report, "memory_v0_isolation_001")
    injection = result_by_id(memory_report, "memory_prompt_injection_data_001")
    rebuild = result_by_id(memory_report, "memory_vector_rebuild_001")

    assert v0.call_counts.repository_reads == 0
    assert v0.call_counts.repository_writes == 0
    assert v0.call_counts.embedding_batches == 0
    assert v0.call_counts.retrievals == 0
    assert v0.call_counts.query_builds == 0
    assert v0.call_counts.llm_calls == 8
    assert injection.safety_counts.prompt_boundary_violation == 0
    assert injection.call_counts.llm_calls == 1
    assert rebuild.failure_categories == ()
    assert rebuild.call_counts.retrievals == 3


def test_report_records_actual_offline_runtime_identity(
    memory_report: MemoryEvaluationReport,
) -> None:
    identity = memory_report.identity
    assert identity.fake_embedding_algorithm == FAKE_EMBEDDING_ALGORITHM_VERSION
    assert identity.fake_embedding_dimension == FAKE_EMBEDDING_DIMENSION
    assert identity.embedding_space_id == FAKE_EMBEDDING_SPACE_ID
    assert identity.sqlite_schema_version == MEMORY_SCHEMA_VERSION
    assert identity.projection_version == "memory_projection_v1"
    assert len(identity.scenario_input_sha256) == 64
    assert len(identity.gold_expectation_sha256) == 64
    assert len(identity.retrieval_config_sha256) == 64
    assert memory_report.latency_sample_count == 28
    assert memory_report.elapsed_ms_p50 is not None
    assert memory_report.elapsed_ms_p95 is not None
    assert memory_report.sqlite_size_bytes_total > 0


def test_observational_fields_are_excluded_from_deterministic_hash(
    memory_report: MemoryEvaluationReport,
) -> None:
    result = memory_report.scenarios[0]
    changed = result.model_copy(
        update={
            "observation": result.observation.model_copy(
                update={"elapsed_ms": result.observation.elapsed_ms + 999.0}
            )
        }
    )
    assert changed.deterministic_result_sha256 == result.deterministic_result_sha256
    assert changed.observation != result.observation


def test_unexpected_scenario_error_becomes_structured_safe_failure() -> None:
    suite, expectations, _ = load_memory_gold()
    scenario = suite.scenarios[0]
    expected = expectations.scenarios[0]

    result = _safe_failure_result(
        scenario,
        expected,
        MemoryEvaluationFailureCategory.UNEXPECTED_ERROR,
        elapsed_ms=1.0,
    )

    payload = result.model_dump_json()
    assert result.passed is False
    assert result.safe_reason_code == "unexpected_error"
    assert result.failure_categories == (
        MemoryEvaluationFailureCategory.UNEXPECTED_ERROR,
    )
    assert "Traceback" not in payload
    assert str(Path.cwd()) not in payload
    assert "secret" not in payload


def test_report_json_contains_no_real_provider_metrics_or_gold_input_payload(
    memory_report: MemoryEvaluationReport,
) -> None:
    payload = json.loads(memory_report.model_dump_json())
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "provider_request_id" not in serialized
    assert "DEEPSEEK_API_KEY" not in serialized
    assert "estimated_cost" not in serialized
    assert "SYNTHETIC_HIDDEN_TRUTH_SENTINEL_P4" not in serialized


def test_module_command_repeats_same_gold_hash_in_a_new_process(
    memory_report: MemoryEvaluationReport,
) -> None:
    repository_root = Path(__file__).parents[1]
    completed = subprocess.run(
        [sys.executable, "-m", "xuanyi_npc.evaluation.memory_runner"],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    child = MemoryEvaluationReport.model_validate_json(completed.stdout)

    assert completed.stderr == ""
    assert child.all_scenarios_passed is True
    assert child.deterministic_run_hashes == memory_report.deterministic_run_hashes
    assert result_by_id(
        child, "memory_stable_tie_001"
    ).metrics.ordered_recalled_memory_ids == result_by_id(
        memory_report, "memory_stable_tie_001"
    ).metrics.ordered_recalled_memory_ids
