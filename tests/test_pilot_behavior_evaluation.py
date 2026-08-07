from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.agents import DoctorAgent, ScriptedFakeLLM
from xuanyi_npc.application.v0_runner import V0EpisodeConfig, V0EpisodeRunner
from xuanyi_npc.config import AgentVariant
from xuanyi_npc.demo_case import build_demo_player
from xuanyi_npc.domain import CaseDefinition, CaseSessionState
from xuanyi_npc.evaluation import (
    EpisodeResult,
    EpisodeStatus,
    PilotBehaviorEvaluator,
    PilotFailureCategory,
    PilotFormatOutcome,
    PilotProbeSuite,
    PilotTaskOutcome,
)
from xuanyi_npc.evaluation.dev_contracts import ScriptedActionOutput
from xuanyi_npc.evaluation.dev_runner import (
    DEFAULT_CASE_PATH,
    DeterministicDevClock,
    load_dev_suite,
)
from xuanyi_npc.evaluation.pilot_runner import (
    DEFAULT_PILOT_PROBE_PATH,
    DEFAULT_SANITIZED_TRACE_PATH,
    load_pilot_probe_suite,
    load_sanitized_pilot_traces,
    run_sanitized_pilot_trace_evaluation,
)


def _correct_reference_episode():
    probe = load_pilot_probe_suite().probes[0]
    dev = load_dev_suite()
    script = dev.scripts["correct_case"]
    responses = tuple(
        dev.actions[output.action_ref].model_dump_json()
        for output in script.outputs
        if isinstance(output, ScriptedActionOutput)
    )
    case = CaseDefinition.model_validate_json(
        Path(DEFAULT_CASE_PATH).read_text(encoding="utf-8")
    )
    player = build_demo_player()
    fake = ScriptedFakeLLM(responses)
    initial = CaseSessionState(
        session_id="pilot_positive_reference",
        case_id=case.case_id,
        player_id=player.player_id,
    )
    episode = V0EpisodeRunner(
        DoctorAgent(fake),
        clock=DeterministicDevClock(),
        config=V0EpisodeConfig(max_steps=8),
    ).run(
        episode_id="pilot_positive_reference",
        case=case,
        player=player,
        initial_session=initial,
        initial_user_message=probe.initial_user_message,
    )
    return probe, episode, fake


def test_real_pilot_probe_schema_is_strict_and_separate_from_fake_contract() -> None:
    suite = load_pilot_probe_suite()
    payload = suite.model_dump(mode="python")
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        PilotProbeSuite.model_validate(payload)

    serialized = Path(DEFAULT_PILOT_PROBE_PATH).read_text(encoding="utf-8")
    assert "trajectories" not in serialized
    assert "script_id" not in serialized
    assert "minimum_repaired_steps" not in serialized
    assert tuple(probe.max_steps for probe in suite.probes) == (8, 8, 8)
    assert len({probe.ground_truth.case_id for probe in suite.probes}) == 1


def test_first_pass_valid_format_is_a_protocol_success_without_repair() -> None:
    probe, episode, _ = _correct_reference_episode()

    result = PilotBehaviorEvaluator().evaluate(probe, episode)

    assert result.task_passed is True
    assert result.format_outcome is PilotFormatOutcome.FIRST_PASS
    assert result.first_pass_structured_steps == 8
    assert result.repaired_steps == 0
    assert result.failure_categories == ()


def test_zero_step_timeout_is_inconclusive_and_format_is_not_observed() -> None:
    probe = load_pilot_probe_suite().probes[0]
    player = build_demo_player()
    session = CaseSessionState(
        session_id="pilot_zero_step_timeout",
        case_id=probe.ground_truth.case_id,
        player_id=player.player_id,
    )
    episode = EpisodeResult(
        episode_id="pilot_zero_step_timeout",
        variant=AgentVariant.V0,
        status=EpisodeStatus.FAILED,
        max_steps=8,
        initial_session=session,
        final_session=session,
        failure_code="deepseek_timeout_error",
        failure_latency_ms=180_000.0,
    )

    result = PilotBehaviorEvaluator().evaluate(probe, episode)

    assert result.task_outcome is PilotTaskOutcome.INCONCLUSIVE
    assert result.task_passed is None
    assert result.format_outcome is PilotFormatOutcome.NOT_OBSERVED
    assert result.failure_categories == ()
    assert result.diagnosis_tool_called is False
    assert result.diagnosis_correct is None
    assert result.treatment_tool_called is False
    assert result.treatment_resolving is None
    assert result.premature_actions == 0
    assert result.progressless_responds == 0
    assert EpisodeResult.model_validate_json(episode.model_dump_json()) == episode


def test_real_probe_truth_and_hidden_fields_never_enter_prompt() -> None:
    probe, _, fake = _correct_reference_episode()
    prompt = "\n".join(
        message.content
        for request in fake.requests
        for message in request.messages
    )

    for fragment in probe.forbidden_prompt_fragments:
        assert fragment not in prompt
    assert probe.ground_truth.model_dump_json() not in prompt


def test_sanitized_trace_bundle_contains_no_provider_identifiers() -> None:
    bundle = load_sanitized_pilot_traces()
    serialized = Path(DEFAULT_SANITIZED_TRACE_PATH).read_text(encoding="utf-8")

    assert len(bundle.traces) == 3
    assert "provider_request_id" not in serialized
    assert "system_fingerprint" not in serialized
    assert "request_id" not in serialized


def test_first_pilot_sanitized_actions_are_reclassified_offline() -> None:
    result = run_sanitized_pilot_trace_evaluation()
    by_trace = {record.trace_id: record.evaluation for record in result.results}

    standard = by_trace["pilot_trace_standard_001"]
    assert standard.format_outcome is PilotFormatOutcome.FIRST_PASS
    assert standard.diagnosis_correct is True
    assert standard.treatment_tool_called is False
    assert PilotFailureCategory.TREATMENT_MISSING in standard.failure_categories
    assert standard.event_count == 5

    resistance = by_trace["pilot_trace_wrong_induction_001"]
    assert resistance.diagnosis_correct is True
    assert resistance.treatment_resolving is False
    assert resistance.final_score == 50
    assert resistance.rejected_steps == 1
    assert PilotFailureCategory.RULE_REJECTION in resistance.failure_categories
    assert PilotFailureCategory.WRONG_TREATMENT in resistance.failure_categories
    assert resistance.event_count == 5

    safety = by_trace["pilot_trace_premature_safety_001"]
    assert safety.diagnosis_tool_called is False
    assert safety.treatment_tool_called is False
    assert safety.premature_actions == 0
    assert PilotFailureCategory.DIAGNOSIS_NOT_SUBMITTED in safety.failure_categories
    assert PilotFailureCategory.RESPOND_WITH_PROGRESS_AVAILABLE in safety.failure_categories
    assert safety.event_count == 4

    assert result.all_events_contiguous is True
    assert result.all_replays_consistent is True


def test_respond_dialogue_is_not_treated_as_submitted_diagnosis() -> None:
    result = run_sanitized_pilot_trace_evaluation()
    safety = next(
        record.evaluation
        for record in result.results
        if record.trace_id == "pilot_trace_premature_safety_001"
    )

    assert safety.diagnosis_tool_called is False
    assert safety.diagnosis_correct is None
    assert PilotFailureCategory.DIAGNOSIS_NOT_SUBMITTED in safety.failure_categories
