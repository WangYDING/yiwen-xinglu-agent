import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.evaluation import (
    DevFailureCategory,
    DevScenario,
    DevSuiteDefinition,
    DevTrajectoryRole,
)
from xuanyi_npc.evaluation.dev_runner import (
    DEFAULT_DEV_SUITE_PATH,
    load_dev_suite,
    run_dev_suite,
)


@pytest.fixture(scope="module")
def suite() -> DevSuiteDefinition:
    return load_dev_suite()


@pytest.fixture(scope="module")
def run_result():
    return run_dev_suite()


def result_for(run_result, scenario_id: str, trajectory_id: str):
    return next(
        result
        for result in run_result.results
        if result.scenario_id == scenario_id
        and result.trajectory_id == trajectory_id
    )


def test_dev_suite_has_exact_scenarios_and_reference_error_pairs(
    suite: DevSuiteDefinition,
) -> None:
    assert tuple(scenario.scenario_id for scenario in suite.scenarios) == (
        "dev_case_correct_001",
        "dev_case_wrong_hypothesis_001",
        "dev_recovery_001",
    )
    for scenario in suite.scenarios:
        roles = tuple(trajectory.role for trajectory in scenario.trajectories)
        assert roles.count(DevTrajectoryRole.REFERENCE) == 1
        assert roles.count(DevTrajectoryRole.EXPLICIT_ERROR) >= 1


@pytest.mark.parametrize("level", ["suite", "scenario"])
def test_dev_schema_rejects_unknown_fields(level: str) -> None:
    payload = json.loads(Path(DEFAULT_DEV_SUITE_PATH).read_text(encoding="utf-8"))
    if level == "suite":
        payload["unknown_field"] = "not allowed"
        validator = DevSuiteDefinition
    else:
        payload = payload["scenarios"][0]
        payload["unknown_field"] = "not allowed"
        validator = DevScenario

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        validator.model_validate(payload)


def test_all_trajectories_match_declared_expectations_without_prompt_leaks(
    run_result,
) -> None:
    assert run_result.scenario_count == 3
    assert run_result.trajectory_count == 6
    assert run_result.all_expectations_matched is True
    assert run_result.execution_mode == "fake_llm_deterministic"
    assert run_result.measurement_status == "not_measured"
    assert all(result.expectation_matched for result in run_result.results)
    assert all(result.context_safe for result in run_result.results)
    assert all(not result.leaked_prompt_fragments for result in run_result.results)
    assert all(
        result.evaluation.usage_measured is False for result in run_result.results
    )


def test_correct_reference_completes_with_deterministic_score_and_replay(
    run_result,
) -> None:
    result = result_for(
        run_result,
        "dev_case_correct_001",
        "reference_correct",
    ).evaluation

    assert result.task_passed is True
    assert result.failure_categories == ()
    assert result.episode_status.value == "completed"
    assert result.final_score == 100
    assert result.step_count == 8
    assert result.event_count == 8
    assert result.final_revision == 8
    assert result.replay_consistent is True


def test_unknown_diagnosis_is_rejected_without_event_or_revision_change(
    run_result,
) -> None:
    result = result_for(
        run_result,
        "dev_case_correct_001",
        "error_unknown_diagnosis",
    ).evaluation

    assert result.task_passed is False
    assert DevFailureCategory.RULE_REJECTION in result.failure_categories
    assert DevFailureCategory.WRONG_HYPOTHESIS not in result.failure_categories
    assert result.rejected_steps == 2
    assert result.event_count == 6
    assert result.final_revision == 6
    assert result.replay_consistent is True


def test_known_wrong_hypothesis_is_accepted_and_classified_semantically(
    run_result,
) -> None:
    result = result_for(
        run_result,
        "dev_case_wrong_hypothesis_001",
        "error_wrong_hypothesis",
    ).evaluation

    assert result.task_passed is False
    assert set(result.failure_categories) == {
        DevFailureCategory.WRONG_HYPOTHESIS,
        DevFailureCategory.SCORE_MISMATCH,
    }
    assert result.episode_status.value == "completed"
    assert result.final_score == 70
    assert result.rejected_steps == 0
    assert result.event_count == 8
    assert result.replay_consistent is True


def test_single_format_repair_recovers_within_the_same_step(run_result) -> None:
    result = result_for(
        run_result,
        "dev_recovery_001",
        "reference_recovered",
    ).evaluation

    assert result.task_passed is True
    assert result.repaired_steps == 1
    assert result.fallback_steps == 0
    assert result.step_count == 8
    assert result.event_count == 8
    assert result.replay_consistent is True


def test_exhausted_format_repair_degrades_and_stops_at_max_steps(run_result) -> None:
    result = result_for(
        run_result,
        "dev_recovery_001",
        "error_recovery_exhausted",
    ).evaluation

    assert result.task_passed is False
    assert DevFailureCategory.REQUIRED_RECOVERY_MISSING in result.failure_categories
    assert DevFailureCategory.FORMAT_RECOVERY_FAILED in result.failure_categories
    assert result.episode_status.value == "max_steps_reached"
    assert result.step_count == 8
    assert result.fallback_steps == 8
    assert result.event_count == 0
    assert result.final_revision == 0
    assert result.replay_consistent is True
