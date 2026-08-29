from __future__ import annotations

from datetime import datetime, timezone
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from xuanyi_npc.domain.cases import CaseSessionStatus, TreatmentOutcome
from xuanyi_npc.domain.cooperation import AuthorityMode
from xuanyi_npc.evaluation.agent_task_benchmark import (
    PublicStateConditionalScript,
    ProductionEquivalentEpisodeExecutor,
    REAL_ARTIFACT_KIND,
    TEST_ARTIFACT_KIND,
    TaskBenchmarkAggregate,
    TaskBenchmarkRunArtifact,
    TaskBenchmarkRunner,
    TaskFailureReason,
    aggregate_run_artifacts,
    load_frozen_manifest,
    load_run_artifacts,
    recompute_aggregate,
    resolve_manifest,
    score_terminal_outcome,
)


NOW = datetime(2026, 8, 26, tzinfo=timezone.utc)


def _terminal(*, diagnosis="correct", outcome=TreatmentOutcome.RESOLVED):
    return SimpleNamespace(
        status=CaseSessionStatus.COMPLETED,
        submitted_diagnosis_id=diagnosis,
        outcome=outcome,
    )


def _case():
    return SimpleNamespace(valid_diagnosis_ids=frozenset({"correct"}))


def _run(
    *, case_id="case_a", repeat=1, success=True, failure=None,
    diagnosis=True, treatment=True, terminal=True, violations=0,
    artifact_kind=TEST_ARTIFACT_KIND, initial="same",
):
    return TaskBenchmarkRunArtifact(
        artifact_kind=artifact_kind,
        benchmark_version="agent_task_benchmark_v1",
        manifest_hash="a" * 64,
        configuration_hash="b" * 64,
        run_id=f"run_{case_id}_{repeat}",
        case_id=case_id,
        repeat_index=repeat,
        model="test-model",
        temperature=0,
        max_output_tokens=2048,
        memory_mode="semantic",
        reflection_mode="enabled",
        initial_public_fingerprint=initial,
        started_at=NOW,
        finished_at=NOW,
        duration_ms=1,
        turn_count=4,
        terminal_status="completed" if terminal else "active",
        terminal_completed=terminal,
        diagnosis_correct=diagnosis,
        treatment_correct=treatment,
        success=success,
        failure_reason=failure,
        goal_completion_count=1 if terminal else 0,
        executed_authority_violation_count=violations,
        input_tokens=10,
        output_tokens=5,
    )


def test_completed_correct_case_is_success() -> None:
    assert score_terminal_outcome(
        session=_terminal(), case=_case(), prior_failure=None
    ) == (True, True, True, True, None)


def test_safe_but_max_turn_incomplete_is_failure() -> None:
    session = SimpleNamespace(
        status=CaseSessionStatus.ACTIVE,
        submitted_diagnosis_id=None,
        outcome=None,
    )
    result = score_terminal_outcome(
        session=session, case=_case(), prior_failure=TaskFailureReason.MAX_TURNS_EXCEEDED
    )
    assert result == (False, False, False, False, TaskFailureReason.MAX_TURNS_EXCEEDED)


def test_wrong_terminal_outcome_is_failure() -> None:
    result = score_terminal_outcome(
        session=_terminal(diagnosis="wrong", outcome=TreatmentOutcome.WORSENED),
        case=_case(),
        prior_failure=None,
    )
    assert result == (True, False, False, False, TaskFailureReason.WRONG_TERMINAL_OUTCOME)


def test_provider_abort_is_preserved_in_aggregate() -> None:
    aggregate = aggregate_run_artifacts((
        _run(success=False, terminal=False, diagnosis=False, treatment=False, failure=TaskFailureReason.PROVIDER_ABORT),
    ))
    assert aggregate.provider_abort_count == 1
    assert aggregate.failure_distribution == {"provider_abort": 1}


def test_executed_violation_is_counted_separately_from_task_success() -> None:
    aggregate = aggregate_run_artifacts((_run(violations=1),))
    assert aggregate.success_count == 1
    assert aggregate.executed_safety_violation_count == 1
    assert aggregate.executed_safety_violation_rate == 1.0


def test_repeat_initial_state_isolation_is_auditable() -> None:
    runs = (_run(repeat=1, initial="clean-template"), _run(repeat=2, initial="clean-template"))
    assert len({run.run_id for run in runs}) == 2
    assert {run.initial_public_fingerprint for run in runs} == {"clean-template"}
    assert all(run.memory_selected_count == 0 for run in runs)


def test_run_one_memory_cannot_enter_run_two_artifact() -> None:
    first = _run(repeat=1).model_copy(update={"memory_selected_count": 1})
    second = _run(repeat=2)
    assert first.memory_selected_count == 1
    assert second.memory_candidate_count == second.memory_selected_count == 0


def test_manifest_hash_is_stable_for_unchanged_runtime(tmp_path: Path) -> None:
    frozen = load_frozen_manifest()
    for target in frozen.runtime_hash_targets:
        path = tmp_path / target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(target, encoding="utf-8")
    first = resolve_manifest(frozen, repeats=1, repository_root=tmp_path)
    second = resolve_manifest(frozen, repeats=1, repository_root=tmp_path)
    assert first[0].configuration_hash == second[0].configuration_hash
    assert first[1] == second[1]


def test_aggregate_is_purely_recomputed_from_run_artifacts(tmp_path: Path) -> None:
    root = tmp_path / "v1"
    run_root = root / "runs" / "case_a"
    run_root.mkdir(parents=True)
    (run_root / "repeat_01.json").write_text(_run().model_dump_json(indent=2), encoding="utf-8")
    expected = aggregate_run_artifacts(load_run_artifacts(root))
    assert recompute_aggregate(root) == expected


def test_fixed_script_reads_only_public_observation() -> None:
    class PublicObservation:
        submitted_diagnosis_id = None
        can_submit_diagnosis = False
        available_investigations = (object(),)

        @property
        def hidden_truth(self):
            raise AssertionError("hidden truth was accessed")

    branch, request = PublicStateConditionalScript().next_input(
        player_id="player", case_id="case", session_id="session", turn_index=1,
        observation=PublicObservation(), pending=None,
    )
    assert branch == PublicStateConditionalScript.INVESTIGATE
    assert request.contribution_type.value == "suggestion"


def test_confirmation_policy_uses_owned_current_pending_contract() -> None:
    pending = SimpleNamespace(
        authority_mode=AuthorityMode.CONFIRMATION_REQUIRED,
        decision_id="decision_1",
        confirmation_id="confirmation_1",
    )
    branch, request = PublicStateConditionalScript().next_input(
        player_id="player", case_id="case", session_id="session", turn_index=2,
        observation=SimpleNamespace(), pending=pending,
    )
    assert branch == PublicStateConditionalScript.APPROVE_TREATMENT
    assert request.responds_to_decision_id == "decision_1"
    assert request.pending_confirmation_id == "confirmation_1"


def test_production_executor_enters_only_through_cooperative_clinic_runtime() -> None:
    source = inspect.getsource(ProductionEquivalentEpisodeExecutor.execute)
    assert "clinic.submit_player_contribution(contribution)" in source
    assert ".submit_case_action(" not in source
    assert "CaseEngine(" not in source
    assert "CaseToolExecutor(" not in source


def test_fake_artifact_cannot_enter_real_benchmark_directory(tmp_path: Path) -> None:
    class FakeExecutor:
        artifact_kind = TEST_ARTIFACT_KIND

    frozen = load_frozen_manifest()
    repository_root = Path(__file__).resolve().parents[1]
    resolved, manifest_hash = resolve_manifest(frozen, repeats=1, repository_root=repository_root)
    with pytest.raises(ValueError, match="test executors"):
        TaskBenchmarkRunner(executor=FakeExecutor(), output_root=tmp_path).run(resolved, manifest_hash)


def test_longest_official_case_produces_valid_run_identifier() -> None:
    case_id = "lantern_alley_conflicting_testimony"
    run_id = f"task_{case_id}_r01"

    assert len(run_id) <= 64
    assert _run(case_id=case_id).case_id == case_id


def test_executor_does_not_put_case_id_in_bounded_player_display_name() -> None:
    source = inspect.getsource(ProductionEquivalentEpisodeExecutor.execute)

    assert 'clinic.create_player(f"Benchmark r{repeat_index:02d}")' in source
