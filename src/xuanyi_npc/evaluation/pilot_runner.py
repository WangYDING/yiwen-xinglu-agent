"""Offline-only re-evaluation of sanitized actions from the first real Pilot."""

from pathlib import Path

from xuanyi_npc.agents import DoctorAgent, ScriptedFakeLLM
from xuanyi_npc.application.v0_runner import V0EpisodeConfig, V0EpisodeRunner
from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import CaseDefinition, CaseSessionState

from .dev_runner import DEFAULT_CASE_PATH, DeterministicDevClock
from .pilot_contracts import (
    PilotProbeSuite,
    PilotTraceEvaluationRecord,
    PilotTraceSuiteResult,
    SanitizedPilotTraceBundle,
)
from .pilot_evaluator import PilotBehaviorEvaluator


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PILOT_PROBE_PATH = (
    REPOSITORY_ROOT / "data" / "evaluation" / "pilot_behavior_probes.json"
)
DEFAULT_SANITIZED_TRACE_PATH = (
    REPOSITORY_ROOT / "data" / "evaluation" / "pilot_run_001_sanitized.json"
)


def load_pilot_probe_suite(
    path: Path | str = DEFAULT_PILOT_PROBE_PATH,
) -> PilotProbeSuite:
    return PilotProbeSuite.model_validate_json(Path(path).read_text(encoding="utf-8"))


def load_sanitized_pilot_traces(
    path: Path | str = DEFAULT_SANITIZED_TRACE_PATH,
) -> SanitizedPilotTraceBundle:
    return SanitizedPilotTraceBundle.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )


def run_sanitized_pilot_trace_evaluation(
    probe_path: Path | str = DEFAULT_PILOT_PROBE_PATH,
    trace_path: Path | str = DEFAULT_SANITIZED_TRACE_PATH,
    case_path: Path | str = DEFAULT_CASE_PATH,
) -> PilotTraceSuiteResult:
    suite = load_pilot_probe_suite(probe_path)
    bundle = load_sanitized_pilot_traces(trace_path)
    case = CaseDefinition.model_validate_json(Path(case_path).read_text(encoding="utf-8"))
    player = build_demo_player()
    probes = {probe.probe_id: probe for probe in suite.probes}
    if set(probes) != {trace.probe_id for trace in bundle.traces}:
        raise ValueError("sanitized traces must match the frozen behavior probes")

    evaluator = PilotBehaviorEvaluator()
    records: list[PilotTraceEvaluationRecord] = []
    for trace in bundle.traces:
        probe = probes[trace.probe_id]
        fake = ScriptedFakeLLM(
            tuple(action.model_dump_json() for action in trace.actions)
        )
        initial_session = CaseSessionState(
            session_id=f"offline_{trace.trace_id}",
            case_id=case.case_id,
            player_id=player.player_id,
        )
        episode = V0EpisodeRunner(
            DoctorAgent(fake),
            clock=DeterministicDevClock(),
            config=V0EpisodeConfig(max_steps=probe.max_steps),
        ).run(
            episode_id=f"offline_{trace.trace_id}",
            case=case,
            player=player,
            initial_session=initial_session,
            initial_user_message=probe.initial_user_message,
        )
        records.append(
            PilotTraceEvaluationRecord(
                trace_id=trace.trace_id,
                evaluation=evaluator.evaluate(probe, episode),
            )
        )

    return PilotTraceSuiteResult(
        suite_id=suite.suite_id,
        all_events_contiguous=all(
            record.evaluation.event_sequences_contiguous for record in records
        ),
        all_replays_consistent=all(
            record.evaluation.replay_consistent for record in records
        ),
        results=tuple(records),
    )


def main() -> int:
    result = run_sanitized_pilot_trace_evaluation()
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
