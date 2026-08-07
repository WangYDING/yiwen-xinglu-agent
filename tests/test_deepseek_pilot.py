from collections import deque
from decimal import Decimal

import pytest

from xuanyi_npc.agents import (
    DeepSeekAdapterConfig,
    DeepSeekChatAdapter,
    DeepSeekModelDiscovery,
    DeepSeekRequestBudgetGuard,
    DeepSeekRequestReservation,
    DeepSeekTimeoutError,
    DeepSeekUsageUnavailableError,
    LLMRequest,
    LLMResponse,
)
from xuanyi_npc.agents.deepseek_cli import paid_pilot_main
from xuanyi_npc.application.deepseek_pilot import (
    FROZEN_PILOT_PROBE_IDS,
    SAFETY_PILOT_PROBE_IDS,
    DeepSeekPilotRunResult,
    DeepSeekPilotRunner,
    PilotRunMode,
    PilotRunStatus,
)
from xuanyi_npc.evaluation import (
    ModelUsage,
    PilotFormatOutcome,
    PilotTaskOutcome,
    load_deepseek_pilot_pricing,
)
from xuanyi_npc.evaluation.dev_contracts import ScriptedActionOutput
from xuanyi_npc.evaluation.dev_runner import load_dev_suite
from xuanyi_npc.evaluation.pilot_runner import load_pilot_probe_suite


class CostedScriptAdapter:
    def __init__(
        self,
        responses: list[str],
        *,
        budget: str = "0.001",
        model_available: bool = True,
        request_reservation_cost: str = "0.000125",
        usage_available: bool = True,
    ) -> None:
        self.config = DeepSeekAdapterConfig(
            api_key="unit-test-placeholder",
            base_url="https://api.deepseek.test",
            pilot_max_cost_cny=Decimal(budget),
        )
        self._responses = deque(responses)
        self._model_available = model_available
        self._request_reservation_cost = Decimal(request_reservation_cost)
        self._usage_available = usage_available
        self.chat_calls = 0
        self.discovery_calls = 0
        self.requests: list[LLMRequest] = []
        self.request_budget = DeepSeekRequestBudgetGuard(
            self.config.pilot_max_cost_cny
        )

    def discover_models(self) -> DeepSeekModelDiscovery:
        self.discovery_calls += 1
        available = (
            ("deepseek-v4-flash",)
            if self._model_available
            else ("deepseek-v4-pro",)
        )
        return DeepSeekModelDiscovery(
            configured_model=self.config.model,
            available_models=available,
            configured_model_available=self._model_available,
        )

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        self.request_budget.reserve(
            DeepSeekRequestReservation(
                input_token_upper_bound=100,
                output_token_upper_bound=20,
                maximum_cost_cny=self._request_reservation_cost,
            )
        )
        self.chat_calls += 1
        usage = ModelUsage(
            provider_model="deepseek-v4-flash",
            input_tokens=100,
            output_tokens=20,
            cache_hit_input_tokens=0,
            cache_miss_input_tokens=100,
            reasoning_tokens=0,
            latency_ms=10.0,
            estimated_cost=Decimal("0.000125"),
            cost_currency="CNY",
            provider_request_id=f"request_{self.chat_calls:03d}",
            system_fingerprint="fp_test",
        )
        if not self._usage_available:
            self.request_budget.halt_unknown_usage()
            raise DeepSeekUsageUnavailableError()
        self.request_budget.settle(usage)
        return LLMResponse(content=self._responses.popleft(), usage=usage)


class TimeoutOnceAdapter(CostedScriptAdapter):
    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        self.request_budget.reserve(
            DeepSeekRequestReservation(
                input_token_upper_bound=100,
                output_token_upper_bound=20,
                maximum_cost_cny=self._request_reservation_cost,
            )
        )
        self.chat_calls += 1
        self.request_budget.halt_unknown_usage()
        raise DeepSeekTimeoutError(
            "offline timeout",
            abort_episode=True,
            latency_ms=180_000.0,
        )


def correct_episode_responses() -> list[str]:
    suite = load_dev_suite()
    script = suite.scripts["correct_case"]
    return [
        suite.actions[output.action_ref].model_dump_json()
        for output in script.outputs
        if isinstance(output, ScriptedActionOutput)
    ]


def probe_initial_message(probe_id: str) -> str:
    suite = load_pilot_probe_suite()
    return next(
        probe.initial_user_message
        for probe in suite.probes
        if probe.probe_id == probe_id
    )


def adapter_saw_message(adapter: CostedScriptAdapter, message: str) -> bool:
    return any(
        chat_message.content == message
        for request in adapter.requests
        for chat_message in request.messages
    )


def test_pilot_budget_stop_preserves_completed_episode_checkpoint(tmp_path) -> None:
    adapter = CostedScriptAdapter(correct_episode_responses())
    checkpoint = tmp_path / "pilot_result.json"

    result = DeepSeekPilotRunner(adapter).run(checkpoint)

    assert result.status is PilotRunStatus.BUDGET_EXHAUSTED
    assert result.execution_config.provider == "deepseek"
    assert result.execution_config.prompt_version == "v0.2.1"
    assert result.execution_config.pricing_snapshot_id == (
        "deepseek_v4_flash_pilot_policy_2026_08_07"
    )
    assert "api_key" not in result.execution_config.model_dump()
    assert result.estimated_cost == Decimal("0.001000")
    assert result.maximum_committed_cost == Decimal("0.001000")
    assert len(result.completed_episodes) == 1
    assert result.completed_episodes[0].probe_id == "pilot_standard_completion_001"
    assert result.completed_episodes[0].episode.max_steps == 8
    assert result.completed_episodes[0].episode.usage is not None
    assert result.completed_episodes[0].episode.usage.cost_currency == "CNY"
    assert result.completed_episodes[0].evaluation.task_passed is True
    assert result.completed_episodes[0].evaluation.format_outcome.value == "first_pass"
    assert result.completed_episodes[0].evaluation.failure_categories == ()
    assert tuple(
        step.provider_usages[0].provider_request_id
        for step in result.completed_episodes[0].episode.steps
    ) == tuple(f"request_{index:03d}" for index in range(1, 9))
    assert result.unstarted_probe_ids == FROZEN_PILOT_PROBE_IDS[1:]
    assert adapter.chat_calls == 8
    assert adapter.discovery_calls == 1
    restored = DeepSeekPilotRunResult.model_validate_json(
        checkpoint.read_text(encoding="utf-8")
    )
    assert restored == result


def test_standard_only_mode_runs_one_probe_then_exits(tmp_path) -> None:
    adapter = CostedScriptAdapter(
        correct_episode_responses(),
        budget="0.03",
    )

    result = DeepSeekPilotRunner(
        adapter,
        run_mode=PilotRunMode.STANDARD_ONLY,
    ).run(tmp_path / "standard_only.json")

    assert result.status is PilotRunStatus.COMPLETED
    assert result.execution_config.run_mode is PilotRunMode.STANDARD_ONLY
    assert tuple(record.probe_id for record in result.completed_episodes) == (
        "pilot_standard_completion_001",
    )
    assert result.unstarted_probe_ids == ()
    assert adapter.discovery_calls == 1
    assert adapter.chat_calls == 8


def test_standard_only_timeout_stops_without_other_probes(tmp_path) -> None:
    adapter = TimeoutOnceAdapter(
        correct_episode_responses(),
        budget="0.03",
    )

    result = DeepSeekPilotRunner(
        adapter,
        run_mode=PilotRunMode.STANDARD_ONLY,
    ).run(tmp_path / "standard_only_timeout.json")

    assert result.status is PilotRunStatus.USAGE_UNAVAILABLE
    assert len(result.completed_episodes) == 1
    record = result.completed_episodes[0]
    assert record.probe_id == "pilot_standard_completion_001"
    assert record.episode.steps == ()
    assert record.episode.events == ()
    assert record.episode.final_session == record.episode.initial_session
    assert record.episode.failure_code == DeepSeekTimeoutError.code
    assert record.episode.failure_latency_ms == 180_000.0
    assert record.evaluation.task_outcome is PilotTaskOutcome.INCONCLUSIVE
    assert record.evaluation.task_passed is None
    assert record.evaluation.format_outcome is PilotFormatOutcome.NOT_OBSERVED
    assert record.evaluation.failure_categories == ()
    assert result.unstarted_probe_ids == ()
    assert adapter.discovery_calls == 1
    assert adapter.chat_calls == 1
    assert adapter.request_budget.halted is True


def test_safety_only_runs_exactly_two_probes_in_fixed_order_and_checkpoints_mode(
    tmp_path,
) -> None:
    adapter = CostedScriptAdapter(
        correct_episode_responses() * 2,
        budget="0.05",
    )
    checkpoint = tmp_path / "safety_only.json"

    result = DeepSeekPilotRunner(
        adapter,
        run_mode=PilotRunMode.SAFETY_ONLY,
    ).run(checkpoint)

    assert result.status is PilotRunStatus.COMPLETED
    assert result.execution_config.run_mode is PilotRunMode.SAFETY_ONLY
    assert (
        tuple(record.probe_id for record in result.completed_episodes)
        == SAFETY_PILOT_PROBE_IDS
    )
    assert result.unstarted_probe_ids == ()
    assert adapter.discovery_calls == 1
    assert adapter.chat_calls == 16
    assert not adapter_saw_message(
        adapter,
        probe_initial_message("pilot_standard_completion_001"),
    )
    assert adapter_saw_message(
        adapter,
        probe_initial_message("pilot_wrong_induction_resistance_001"),
    )
    assert adapter_saw_message(
        adapter,
        probe_initial_message("pilot_premature_action_safety_001"),
    )
    restored = DeepSeekPilotRunResult.model_validate_json(
        checkpoint.read_text(encoding="utf-8")
    )
    assert restored == result
    assert restored.execution_config.run_mode is PilotRunMode.SAFETY_ONLY


def test_safety_only_first_probe_stop_does_not_start_second(tmp_path) -> None:
    adapter = TimeoutOnceAdapter(
        correct_episode_responses() * 2,
        budget="0.05",
    )

    result = DeepSeekPilotRunner(
        adapter,
        run_mode=PilotRunMode.SAFETY_ONLY,
    ).run(tmp_path / "safety_only_timeout.json")

    assert result.status is PilotRunStatus.USAGE_UNAVAILABLE
    assert tuple(record.probe_id for record in result.completed_episodes) == (
        "pilot_wrong_induction_resistance_001",
    )
    assert result.unstarted_probe_ids == (
        "pilot_premature_action_safety_001",
    )
    assert adapter.discovery_calls == 1
    assert adapter.chat_calls == 1
    assert adapter_saw_message(
        adapter,
        probe_initial_message("pilot_wrong_induction_resistance_001"),
    )
    assert not adapter_saw_message(
        adapter,
        probe_initial_message("pilot_premature_action_safety_001"),
    )
    assert not adapter_saw_message(
        adapter,
        probe_initial_message("pilot_standard_completion_001"),
    )


def test_pilot_model_unavailable_stops_before_any_chat_request(tmp_path) -> None:
    adapter = CostedScriptAdapter([], model_available=False)

    result = DeepSeekPilotRunner(adapter).run(tmp_path / "unavailable.json")

    assert result.status is PilotRunStatus.MODEL_UNAVAILABLE
    assert result.available_models == ("deepseek-v4-pro",)
    assert result.completed_episodes == ()
    assert result.unstarted_probe_ids == FROZEN_PILOT_PROBE_IDS
    assert adapter.discovery_calls == 1
    assert adapter.chat_calls == 0


def test_request_budget_rejects_before_network_or_state_change(tmp_path) -> None:
    adapter = CostedScriptAdapter(
        correct_episode_responses(),
        budget="0.000124",
    )

    result = DeepSeekPilotRunner(adapter).run(tmp_path / "budget_blocked.json")

    assert result.status is PilotRunStatus.BUDGET_EXHAUSTED
    assert result.estimated_cost == Decimal("0")
    assert result.maximum_committed_cost == Decimal("0")
    assert result.completed_episodes == ()
    assert result.unstarted_probe_ids == FROZEN_PILOT_PROBE_IDS
    assert adapter.discovery_calls == 1
    assert adapter.chat_calls == 0


def test_missing_usage_stops_after_one_request_without_events(tmp_path) -> None:
    adapter = CostedScriptAdapter(
        correct_episode_responses(),
        usage_available=False,
    )

    result = DeepSeekPilotRunner(adapter).run(tmp_path / "usage_missing.json")

    assert result.status is PilotRunStatus.USAGE_UNAVAILABLE
    assert result.estimated_cost == Decimal("0")
    assert result.maximum_committed_cost == Decimal("0.000125")
    assert len(result.completed_episodes) == 1
    episode = result.completed_episodes[0].episode
    assert episode.status.value == "failed"
    assert episode.failure_code == "deepseek_usage_unavailable"
    assert episode.steps == ()
    assert episode.events == ()
    assert episode.final_session == episode.initial_session
    assert result.unstarted_probe_ids == FROZEN_PILOT_PROBE_IDS[1:]
    assert adapter.discovery_calls == 1
    assert adapter.chat_calls == 1


def test_budget_blocked_format_repair_preserves_first_call_usage(tmp_path) -> None:
    adapter = CostedScriptAdapter(
        ["not-json"],
        budget="0.000125",
    )

    result = DeepSeekPilotRunner(adapter).run(tmp_path / "repair_blocked.json")

    assert result.status is PilotRunStatus.BUDGET_EXHAUSTED
    assert result.estimated_cost == Decimal("0.000125")
    assert result.maximum_committed_cost == Decimal("0.000125")
    assert len(result.completed_episodes) == 1
    episode = result.completed_episodes[0].episode
    assert episode.status.value == "failed"
    assert episode.failure_code == "deepseek_budget_exhausted"
    assert episode.steps == ()
    assert episode.events == ()
    assert episode.final_session == episode.initial_session
    assert episode.usage is not None
    assert episode.usage.estimated_cost == Decimal("0.000125")
    assert episode.usage.measurement_complete is False
    assert result.unstarted_probe_ids == FROZEN_PILOT_PROBE_IDS[1:]
    assert adapter.discovery_calls == 1
    assert adapter.chat_calls == 1


def test_pilot_pricing_freezes_three_behavior_probes_and_limits() -> None:
    pricing = load_deepseek_pilot_pricing()

    assert pricing.allowed_probe_ids == FROZEN_PILOT_PROBE_IDS
    assert pricing.runs_per_probe == 1
    assert pricing.max_steps_per_episode == 8
    assert pricing.max_format_repair_attempts_per_step == 1


def test_paid_pilot_command_refuses_without_explicit_confirmation(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    exit_code = paid_pilot_main([])

    assert exit_code == 2
    assert "Refusing to start" in capsys.readouterr().err


def test_safety_only_command_refuses_without_paid_confirmation_before_network(
    monkeypatch,
    capsys,
) -> None:
    adapter_opened = False

    def fail_if_opened(cls):
        nonlocal adapter_opened
        adapter_opened = True
        raise AssertionError("adapter must not be opened")

    monkeypatch.setattr(
        DeepSeekChatAdapter,
        "from_env",
        classmethod(fail_if_opened),
    )

    exit_code = paid_pilot_main(["--safety-only"])

    assert exit_code == 2
    assert "Refusing to start" in capsys.readouterr().err
    assert adapter_opened is False


def test_paid_pilot_run_modes_are_mutually_exclusive_before_network(
    monkeypatch,
    capsys,
) -> None:
    adapter_opened = False

    def fail_if_opened(cls):
        nonlocal adapter_opened
        adapter_opened = True
        raise AssertionError("adapter must not be opened")

    monkeypatch.setattr(
        DeepSeekChatAdapter,
        "from_env",
        classmethod(fail_if_opened),
    )

    with pytest.raises(SystemExit) as exc_info:
        paid_pilot_main(
            [
                "--confirm-paid-pilot",
                "--standard-only",
                "--safety-only",
            ]
        )

    assert exc_info.value.code == 2
    assert "not allowed with argument" in capsys.readouterr().err
    assert adapter_opened is False
