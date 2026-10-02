from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timezone
import copy
import json
from pathlib import Path

import pytest

import xuanyi_npc.evaluation.ce2a_context_behavior as evaluation
from xuanyi_npc.agents import DeepSeekRequestBudgetGuard, DeepSeekRequestReservation, ModelUsage
from xuanyi_npc.agents.llm import LLMAdapterError, LLMResponse
from xuanyi_npc.evaluation.request_ledger import DurableRequestLedger
from xuanyi_npc.domain import ToolName


@pytest.fixture(scope="module")
def offline_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("ce2a_behavior") / "run"
    evaluation.run_offline(output=root)
    artifacts = evaluation._load_artifacts(root)
    return root, artifacts


def _artifact(artifacts, scenario_id, condition, repeat=1):
    return next(
        item for item in artifacts
        if item["scenario_id"] == scenario_id
        and item["condition"] == condition
        and item["repeat"] == repeat
    )


def test_v2_real_case_scenarios_and_private_answers_never_enter_requests(offline_run):
    _, artifacts = offline_run
    bundle = evaluation.load_bundle()
    assert tuple(item["scenario_id"] for item in bundle.scenarios) == evaluation.EXPECTED_V2_SCENARIO_IDS
    assert len(bundle.scenarios) == 13
    assert next(item for item in bundle.scenarios if item["scenario_id"] == "H04")["history_dependency_eligible"] is False
    assert all(item["preconditions"] for item in bundle.scenarios)
    requests = json.dumps(
        [request for artifact in artifacts for request in artifact["adapter_requests"]],
        ensure_ascii=False,
    )
    for rubric in bundle.private["rubrics"]:
        assert rubric["model_invisible_canary"] not in requests


def test_v1_inputs_remain_the_exact_v2_overlay_sources():
    public_overlay = json.loads((evaluation.FIXTURE_ROOT / "scenarios.json").read_text(encoding="utf-8"))
    private_overlay = json.loads((evaluation.FIXTURE_ROOT / "rubric_private.json").read_text(encoding="utf-8"))
    assert evaluation._sha256(evaluation.V1_FIXTURE_ROOT / "scenarios.json") == public_overlay["base_fixture_sha256"]
    assert evaluation._sha256(evaluation.V1_FIXTURE_ROOT / "rubric_private.json") == private_overlay["base_fixture_sha256"]


def test_ct_starts_are_equivalent_isolated_and_differ_at_final_adapter_boundary(offline_run):
    root, artifacts = offline_run
    differences = json.loads((root / "pair_differences.json").read_text(encoding="utf-8"))
    assert len(differences) == 26
    assert all(item["initial_equivalent"] and item["adapter_boundary_ok"] for item in differences)
    for scenario_id in {item["scenario_id"] for item in artifacts}:
        c = _artifact(artifacts, scenario_id, "C")
        t = _artifact(artifacts, scenario_id, "T")
        assert c["initial_state"]["equivalence_hash"] == t["initial_state"]["equivalence_hash"]
    state_roots = [path for path in (root / "runs").glob("*/state")]
    assert len(state_roots) == 52 and len({path.resolve() for path in state_roots}) == 52


def test_repairs_fallbacks_and_snapshot_reuse_are_counted(offline_run):
    _, artifacts = offline_run
    h02 = _artifact(artifacts, "H02", "T")
    h03 = _artifact(artifacts, "H03", "T")
    assert h02["adapter_call_count"] == 2 and h02["repair_kind"] == "format_repair"
    assert not h02["fallback"]
    assert h03["adapter_call_count"] == 2 and h03["fallback"]
    assert h02["adapter_requests"][1]["messages"][: len(h02["adapter_requests"][0]["messages"])] == h02["adapter_requests"][0]["messages"]
    report = evaluation.build_report(artifacts)
    assert report["runtime"]["adapter_calls"] <= 104
    assert report["runtime"]["repairs"] == 8
    assert report["runtime"]["fallbacks"] == 4


def test_restart_recovers_history_not_pending_and_long_history_is_omitted(offline_run):
    _, artifacts = offline_run
    r01 = _artifact(artifacts, "R01", "T")
    rtext = json.dumps(r01["adapter_requests"][0], ensure_ascii=False)
    assert "fixture_r01_history_1" in rtext
    assert "confirmation_r01_a" not in rtext
    assert r01["initial_state"]["pending_confirmation_ids"] == []

    o01 = _artifact(artifacts, "O01", "T")
    otext = "\n".join(item["content"] for item in o01["adapter_requests"][0]["messages"])
    assert "fixture_o01_history_newest" in otext
    assert "fixture_o01_history_older" not in otext
    assert '"omission"' in otext
    assert "若当前问题依赖被省略内容，请玩家重述必要信息" in otext


def test_pending_object_and_authority_metrics_are_separate(offline_run):
    _, artifacts = offline_run
    p01 = _artifact(artifacts, "P01O", "T")
    text = "\n".join(item["content"] for item in p01["adapter_requests"][0]["messages"])
    assert text.count('"responds_to_current_contribution": true') == 1
    assert "confirm_decision_fixture_p01o_proposal" in text
    assert "exam_exhaustion" in text
    assert p01["world"]["new_actions"] == []
    p01a = _artifact(artifacts, "P01A", "T")
    assert p01a["world"]["new_actions"] == []
    assert p01a["initial_state"]["session"]["submitted_diagnosis_id"] is None


def test_budget_missing_usage_real_guard_and_test_prices_are_conservative():
    price = evaluation.SyntheticPrice(Decimal("1"), Decimal("2"))
    guard = evaluation.BudgetGuard(
        price=price, total_cap=Decimal("0.01"), per_turn_cap=Decimal("0.01")
    )
    reservation = guard.reserve(input_token_upper_bound=1000, output_token_upper_bound=1000)
    assert reservation == Decimal("0.003")
    assert guard.settle(reservation, input_tokens=None, output_tokens=None) == reservation
    with pytest.raises(evaluation.RealRunBlocked, match="token upper bounds"):
        guard.reserve(input_token_upper_bound=None, output_token_upper_bound=1)
    with pytest.raises(evaluation.RealRunBlocked, match="budget is insufficient"):
        guard.reserve(input_token_upper_bound=1_000_000, output_token_upper_bound=1_000_000)
    with pytest.raises(evaluation.RealRunBlocked, match="disabled"):
        evaluation.ensure_real_run_allowed(evaluation.load_bundle().protocol["real_run"])


def test_existing_or_interrupted_output_is_never_overwritten(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "RUNNING.json").write_text('{"status":"interrupted"}', encoding="utf-8")
    with pytest.raises(evaluation.EvaluationError, match="will not be overwritten"):
        evaluation.run_offline(output=output)
    assert json.loads((output / "RUNNING.json").read_text(encoding="utf-8"))["status"] == "interrupted"


def test_blind_export_stays_unscored_and_missing_pairs_are_reported(offline_run):
    root, artifacts = offline_run
    blind = json.loads((root / "blind_review.json").read_text(encoding="utf-8"))
    assert len(blind["items"]) == 52
    assert all(item["score"] is None and "condition" not in item for item in blind["items"])
    report = evaluation.build_report(artifacts[:-1])
    assert report["paired_semantic_result"]["missing"] == 1
    assert report["paired_semantic_result"]["win"] == 0


def _real_bundle(tmp_path, *, total="1.00", per_turn="0.50", enabled=True, authorized=True):
    base = evaluation.load_bundle()
    protocol = copy.deepcopy(base.protocol)
    price = evaluation.PROJECT_ROOT / "src/xuanyi_npc/resources/pilot/deepseek_flash_price_snapshot_2026-09-18.json"
    today = datetime.now(timezone.utc).date().isoformat()
    protocol["real_run"].update({
        "enabled":enabled, "paid_authorized":authorized, "authorization_id":"test_authorization_001",
        "model":"deepseek-flash", "total_budget_cny":total, "per_turn_budget_cny":per_turn,
        "price_snapshot_path":str(price), "price_snapshot_sha256":evaluation._sha256(price),
        "price_verified_on":today, "price_valid_through":today,
        "scenario_ids":["H01"], "repeats":1,
    })
    return evaluation.Bundle(root=base.root, public=base.public, private=base.private, protocol=protocol)


class _FakePaidBase:
    class Config:
        max_output_tokens = 512

    config = Config()

    def __init__(self, scenario, total):
        self.inner = evaluation.ControlledOfflineAdapter(
            scenario=scenario, tool_name=ToolName.OBSERVE_PATIENT, target_id="observe_scholar"
        )
        self.request_budget = DeepSeekRequestBudgetGuard(Decimal(total))
        self.network_calls = 0

    def conservative_request_reservation(self, request):
        return DeepSeekRequestReservation(
            input_token_upper_bound=1000,
            output_token_upper_bound=getattr(request, "max_output_tokens", 512),
            maximum_cost_cny=Decimal("0.01"),
        )

    def complete(self, request):
        reservation = self.conservative_request_reservation(request)
        self.request_budget.reserve(reservation)
        self.network_calls += 1
        raw = self.inner.complete(request)
        usage = ModelUsage(
            provider_model="deepseek-flash", input_tokens=100, output_tokens=20,
            cache_hit_input_tokens=0, cache_miss_input_tokens=100, reasoning_tokens=0,
            latency_ms=1.0, estimated_cost=Decimal("0.001"), cost_currency="CNY",
            provider_request_id=f"fake_{self.network_calls}",
        )
        self.request_budget.settle(usage)
        return raw.model_copy(update={"usage":usage})


def test_real_mode_guards_block_before_adapter_creation(tmp_path):
    calls = 0
    def factory(*args):
        nonlocal calls
        calls += 1
        raise AssertionError("provider factory must not be reached")
    bundle = _real_bundle(tmp_path, enabled=False)
    with pytest.raises(evaluation.RealRunBlocked, match="disabled"):
        evaluation.run_real(output=tmp_path / "disabled", confirm_paid=True, bundle=bundle,
                            adapter_factory=factory, claim_root=tmp_path / "claims")
    bundle = _real_bundle(tmp_path, authorized=False)
    with pytest.raises(evaluation.RealRunBlocked, match="authorization"):
        evaluation.run_real(output=tmp_path / "unauthorized", confirm_paid=False, bundle=bundle,
                            adapter_factory=factory, claim_root=tmp_path / "claims")
    bundle = _real_bundle(tmp_path, total="0.01", per_turn="0.50")
    with pytest.raises(evaluation.RealRunBlocked, match="per-turn"):
        evaluation.run_real(output=tmp_path / "bad_budget", confirm_paid=True, bundle=bundle,
                            adapter_factory=factory, claim_root=tmp_path / "claims")
    assert calls == 0


def test_guarded_real_mode_uses_production_path_without_offline_failure_injection(tmp_path):
    bundle = _real_bundle(tmp_path)
    created = []
    def factory(config, pricing):
        base = _FakePaidBase(next(item for item in bundle.scenarios if item["scenario_id"] == "H01"), config["total_budget_cny"])
        created.append(base)
        return base
    output = tmp_path / "real"
    evaluation.run_real(output=output, confirm_paid=True, bundle=bundle,
                        adapter_factory=factory, claim_root=tmp_path / "claims")
    artifacts = evaluation._load_artifacts(output)
    assert len(artifacts) == 2
    assert all(item["adapter_call_count"] == 1 for item in artifacts)
    assert created[0].network_calls == 2
    assert all(item["semantic_score"] is None for item in artifacts)
    ledger = [json.loads(line) for line in (output / "request_ledger.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [item["status"] for item in ledger] == ["started", "completed", "started", "completed"]
    with pytest.raises(evaluation.EvaluationError, match="already exists"):
        evaluation.run_real(output=output, confirm_paid=True, bundle=bundle,
                            adapter_factory=factory, claim_root=tmp_path / "claims")
    with pytest.raises(evaluation.RealRunBlocked, match="already claimed"):
        evaluation.run_real(output=tmp_path / "other", confirm_paid=True, bundle=bundle,
                            adapter_factory=factory, claim_root=tmp_path / "claims")


def test_paid_adapter_reserves_per_call_and_stops_on_missing_usage(tmp_path):
    scenario = next(item for item in evaluation.load_bundle().scenarios if item["scenario_id"] == "H01")
    base = _FakePaidBase(scenario, "1.00")
    request = evaluation.ControlledOfflineAdapter(
        scenario=scenario, tool_name=ToolName.OBSERVE_PATIENT, target_id="observe_scholar"
    )
    # Obtain a real production-shaped request without sending it anywhere.
    artifact = evaluation._execute_one(tmp_path / "shape", scenario, "C", 1)
    from xuanyi_npc.agents.context import GameNPCPlanningRequest
    shaped = GameNPCPlanningRequest.model_validate(artifact["adapter_requests"][0])
    ledger = DurableRequestLedger(tmp_path / "ledger.jsonl")
    wrapper = evaluation.PaidEvidenceAdapter(
        base, ledger, per_turn_cap=Decimal("0.005"), identity={"scenario_id":"H01"}
    )
    with pytest.raises(LLMAdapterError, match="per-turn"):
        wrapper.complete(shaped)
    assert base.network_calls == 0

    class MissingUsageBase(_FakePaidBase):
        def complete(self, request):
            self.network_calls += 1
            return LLMResponse(content=self.inner._valid_content(), usage=None)
    missing = MissingUsageBase(scenario, "1.00")
    missing_wrapper = evaluation.PaidEvidenceAdapter(
        missing, DurableRequestLedger(tmp_path / "missing.jsonl"),
        per_turn_cap=Decimal("0.50"), identity={"scenario_id":"H01"},
    )
    with pytest.raises(LLMAdapterError, match="usage is missing"):
        missing_wrapper.complete(shaped)
    assert missing.network_calls == 1 and missing_wrapper.uncertain
    assert missing.request_budget.halted


def test_paid_adapter_records_timeout_as_uncertain_and_never_retries(tmp_path):
    scenario = next(item for item in evaluation.load_bundle().scenarios if item["scenario_id"] == "H01")
    artifact = evaluation._execute_one(tmp_path / "shape", scenario, "C", 1)
    from xuanyi_npc.agents.context import GameNPCPlanningRequest
    shaped = GameNPCPlanningRequest.model_validate(artifact["adapter_requests"][0])
    base = _FakePaidBase(scenario, "1.00")
    def timeout(request):
        base.network_calls += 1
        base.request_budget.halt_unknown_usage()
        raise LLMAdapterError("timeout", abort_episode=True)
    base.complete = timeout
    path = tmp_path / "timeout.jsonl"
    wrapper = evaluation.PaidEvidenceAdapter(
        base, DurableRequestLedger(path), per_turn_cap=Decimal("0.50"), identity={"scenario_id":"H01"}
    )
    with pytest.raises(LLMAdapterError, match="timeout"):
        wrapper.complete(shaped)
    assert base.network_calls == 1 and wrapper.uncertain
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [item["status"] for item in records] == ["started", "error"]

@pytest.mark.parametrize("status,expected_calls", [("started", 0), ("completed", 1), ("error", 1)])
def test_ledger_failure_stops_batch_before_tools(tmp_path, monkeypatch, status, expected_calls):
    bundle = _real_bundle(tmp_path)
    scenario = next(s for s in bundle.scenarios if s["scenario_id"] == "H01")
    base = _FakePaidBase(scenario, "1.00")
    original_error = LLMAdapterError("injected timeout", abort_episode=True)
    if status == "error":
        def fail_provider(request):
            base.network_calls += 1
            base.request_budget.halt_unknown_usage()
            raise original_error
        base.complete = fail_provider
    original_append = DurableRequestLedger.append
    def append(ledger, record):
        if record["status"] == status:
            raise OSError("injected disk failure")
        original_append(ledger, record)
    monkeypatch.setattr(DurableRequestLedger, "append", append)
    output = tmp_path / "run"
    with pytest.raises(Exception):
        evaluation.run_real(output=output, confirm_paid=True, bundle=bundle,
                            adapter_factory=lambda *args: base, claim_root=tmp_path / "claims")
    assert base.network_calls == expected_calls
    assert not (output / "COMPLETE.json").exists()
    assert json.loads((output / "RUNNING.json").read_text())["status"] == "interrupted"
    assert len(list((output / "runs").iterdir())) == 1
    artifact = evaluation._load_artifacts(output)[0]
    assert artifact["status"] == "failed" and not artifact["fallback"]
    assert artifact["world"]["new_actions"] == []
    assert artifact["world"]["revision_before"] == artifact["world"]["revision_after"]
    evidence = json.loads((output / "RUNNING.json").read_text())["failed_request_evidence"]
    assert evidence["provider_adapter_invoked"] is (status != "started")
    if status == "completed":
        assert Decimal(evidence["usage"]["estimated_cost"]) == Decimal("0.001")
    elif status == "error":
        assert evidence["usage"] is None and evidence["budget"]["halted"]


@pytest.mark.parametrize("path", ["format", "action"])
def test_paid_ledger_failure_in_repairs_stops_before_tools(tmp_path, monkeypatch, path):
    bundle = _real_bundle(tmp_path)
    scenario = next(s for s in bundle.scenarios if s["scenario_id"] == "H01")
    base = _FakePaidBase(scenario, "1.00")
    complete = base.complete
    if path == "format":
        def malformed_first(request):
            response = complete(request)
            return response.model_copy(update={"content":"invalid json"}) if base.network_calls == 1 else response
        base.complete = malformed_first
        expected_calls = 2
    else:
        from tests.test_context_engineering_ce11 import _RuntimeA1ContractRepairAgent
        setup = evaluation._setup_run
        def repair_setup(*args, **kwargs):
            result = setup(*args, **kwargs)
            result[0].game_npc_agent = _RuntimeA1ContractRepairAgent(result[1])
            return result
        monkeypatch.setattr(evaluation, "_setup_run", repair_setup)
        expected_calls = 1
    append = DurableRequestLedger.append
    def fail_terminal(ledger, record):
        if record["status"] == "completed" and base.network_calls == expected_calls:
            raise OSError("repair ledger unavailable")
        append(ledger, record)
    monkeypatch.setattr(DurableRequestLedger, "append", fail_terminal)
    output = tmp_path / "run"
    with pytest.raises(evaluation.PaidRequestEvidenceError):
        evaluation.run_real(output=output, confirm_paid=True, bundle=bundle,
                            adapter_factory=lambda *args: base, claim_root=tmp_path / "claims")
    assert base.network_calls == expected_calls
    artifacts = evaluation._load_artifacts(output)
    assert len(artifacts) == 1
    assert artifacts[0]["status"] == "failed" and not artifacts[0]["fallback"]
    assert artifacts[0]["world"]["new_actions"] == []


def test_failed_error_evidence_preserves_original_usage_and_latches(tmp_path):
    scenario = next(s for s in evaluation.load_bundle().scenarios if s["scenario_id"] == "H01")
    artifact = evaluation._execute_one(tmp_path / "shape", scenario, "C", 1)
    from xuanyi_npc.agents.context import GameNPCPlanningRequest
    request = GameNPCPlanningRequest.model_validate(artifact["adapter_requests"][0])
    base = _FakePaidBase(scenario, "1.00")
    complete = base.complete
    errors = []
    def provider_error(request):
        response = complete(request)
        error = LLMAdapterError("provider content error", usage=response.usage)
        errors.append(error)
        raise error
    base.complete = provider_error
    class FailedLedger:
        def append(self, record):
            if record["status"] == "error":
                raise OSError("disk full")
    wrapper = evaluation.PaidEvidenceAdapter(base, FailedLedger(), per_turn_cap=Decimal("0.50"), identity={})
    with pytest.raises(evaluation.PaidRequestEvidenceError) as caught:
        wrapper.complete(request)
    assert caught.value.abort_episode and wrapper.uncertain
    assert caught.value.provider_error is errors[0]
    assert caught.value.usage == errors[0].usage
    assert wrapper.known_turn_cost == Decimal("0.001")
    with pytest.raises(evaluation.PaidRequestEvidenceError):
        wrapper.complete(request)
    assert base.network_calls == 1
