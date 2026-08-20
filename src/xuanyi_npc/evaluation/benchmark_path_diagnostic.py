"""One-shot sanitized diagnostic through the actual real benchmark path."""

from __future__ import annotations

from pathlib import Path
import tempfile

from pydantic import ConfigDict

from xuanyi_npc.domain.base import DomainModel
from xuanyi_npc.evaluation.agent_benchmark import BenchmarkScenario, BenchmarkVariant
from xuanyi_npc.evaluation.real_agent_benchmark import (
    DeepSeekCooperativePilotExecutor,
    RealAgentBenchmarkReport,
    RealAgentBenchmarkRunner,
    RealBenchmarkConfig,
)
from xuanyi_npc.evaluation.structured_output_diagnostics import (
    PlanningStructuredOutputTelemetry,
    PlanningTelemetryCollector,
)


class BenchmarkPathDiagnosticArtifact(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    telemetry: PlanningStructuredOutputTelemetry
    benchmark_report: RealAgentBenchmarkReport


def main() -> int:
    import argparse
    from xuanyi_npc.agents.deepseek import DeepSeekChatAdapter
    from xuanyi_npc.agents.game_npc import GAME_NPC_PLANNING_MAX_OUTPUT_TOKENS

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    adapter = DeepSeekChatAdapter.from_env()
    collector = PlanningTelemetryCollector(
        request_id="request_m5_7_real_0",
        run_id="real_wrong_player_suggestion_standard_0",
        model=adapter.config.model,
        configured_max_output_tokens=GAME_NPC_PLANNING_MAX_OUTPUT_TOKENS,
    )
    with tempfile.TemporaryDirectory(prefix="xuanyi_m5_7_") as directory:
        try:
            report = RealAgentBenchmarkRunner(executor=DeepSeekCooperativePilotExecutor(
                adapter=adapter,
                artifact_root=Path(directory),
                diagnostic_hook=collector.hook,
            )).run(RealBenchmarkConfig(
                model_name=adapter.config.model,
                scenario_ids=(BenchmarkScenario.WRONG_PLAYER_SUGGESTION,),
                repeats=1,
                variant=BenchmarkVariant.M4_REFLECTION,
            ))
        finally:
            adapter.close()
    artifact = BenchmarkPathDiagnosticArtifact(telemetry=collector.snapshot(), benchmark_report=report)
    Path(args.output).write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    print(artifact.telemetry.model_dump_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
