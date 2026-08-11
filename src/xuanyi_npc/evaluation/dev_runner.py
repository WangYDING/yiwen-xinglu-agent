"""One-command deterministic runner for all three M2b-P0 dev scenarios."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from xuanyi_npc.agents import DoctorAgent, ScriptedFakeLLM
from xuanyi_npc.application.v0_runner import V0EpisodeConfig, V0EpisodeRunner
from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import CaseDefinition, CaseSessionState

from .dev_contracts import (
    DevScriptedOutput,
    DevSuiteDefinition,
    DevSuiteRunResult,
    DevTrajectoryRunResult,
    ScriptedActionOutput,
)
from .dev_evaluator import DevEpisodeEvaluator


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DEV_SUITE_PATH = REPOSITORY_ROOT / "data" / "evaluation" / "dev_scenarios.json"
DEFAULT_CASE_PATH = REPOSITORY_ROOT / "data" / "cases" / "old_paper_umbrella.json"


class DeterministicDevClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 8, 4, 10, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        self._current += timedelta(minutes=1)
        return self._current


def load_dev_suite(path: Path | str = DEFAULT_DEV_SUITE_PATH) -> DevSuiteDefinition:
    return DevSuiteDefinition.model_validate_json(Path(path).read_text(encoding="utf-8"))


def run_dev_suite(
    suite_path: Path | str = DEFAULT_DEV_SUITE_PATH,
    case_path: Path | str = DEFAULT_CASE_PATH,
) -> DevSuiteRunResult:
    suite = load_dev_suite(suite_path)
    case = CaseDefinition.model_validate_json(Path(case_path).read_text(encoding="utf-8"))
    player = build_demo_player()
    evaluator = DevEpisodeEvaluator()
    results: list[DevTrajectoryRunResult] = []

    for scenario in suite.scenarios:
        if scenario.ground_truth.case_id != case.case_id:
            raise ValueError("dev scenario case_id does not match the loaded case")
        declared_failures = {
            condition.category for condition in scenario.failure_conditions
        }
        for trajectory in scenario.trajectories:
            script = suite.scripts[trajectory.script_id]
            fake_llm = ScriptedFakeLLM(
                _provider_responses(suite, script.outputs)
            )
            initial_session = CaseSessionState(
                session_id=f"{scenario.scenario_id}_{trajectory.trajectory_id}",
                case_id=case.case_id,
                player_id=player.player_id,
            )
            episode = V0EpisodeRunner(
                DoctorAgent(fake_llm),
                clock=DeterministicDevClock(),
                config=V0EpisodeConfig(max_steps=scenario.max_steps),
                _preserve_historical_trace_semantics=True,
            ).run(
                episode_id=f"{scenario.scenario_id}_{trajectory.trajectory_id}",
                case=case,
                player=player,
                initial_session=initial_session,
                initial_user_message=scenario.initial_user_message,
            )
            evaluation = evaluator.evaluate(
                scenario,
                trajectory.trajectory_id,
                episode,
            )
            prompt_text = "\n".join(
                message.content
                for request in fake_llm.requests
                for message in request.messages
            )
            leaked_fragments = tuple(
                fragment
                for fragment in scenario.forbidden_prompt_fragments
                if fragment in prompt_text
            )
            expected = trajectory.expectation
            actual_failures = set(evaluation.failure_categories)
            expectation_matched = bool(
                evaluation.task_passed is expected.task_passed
                and expected.required_failure_categories.issubset(actual_failures)
                and not expected.forbidden_failure_categories.intersection(
                    actual_failures
                )
                and actual_failures.issubset(declared_failures)
                and not leaked_fragments
            )
            results.append(
                DevTrajectoryRunResult(
                    scenario_id=scenario.scenario_id,
                    trajectory_id=trajectory.trajectory_id,
                    role=trajectory.role,
                    expectation_matched=expectation_matched,
                    context_safe=not leaked_fragments,
                    leaked_prompt_fragments=leaked_fragments,
                    evaluation=evaluation,
                )
            )

    return DevSuiteRunResult(
        suite_id=suite.suite_id,
        scenario_count=len(suite.scenarios),
        trajectory_count=len(results),
        all_expectations_matched=all(
            result.expectation_matched for result in results
        ),
        results=tuple(results),
    )


def _provider_responses(
    suite: DevSuiteDefinition,
    outputs: tuple[DevScriptedOutput, ...],
) -> tuple[str, ...]:
    return tuple(
        suite.actions[output.action_ref].model_dump_json()
        if isinstance(output, ScriptedActionOutput)
        else output.content
        for output in outputs
    )


def main() -> int:
    result = run_dev_suite()
    print(result.model_dump_json(indent=2))
    return 0 if result.all_expectations_matched else 1


if __name__ == "__main__":
    raise SystemExit(main())
