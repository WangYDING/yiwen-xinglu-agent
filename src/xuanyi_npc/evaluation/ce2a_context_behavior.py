"""CE-2A C/T evaluation harness with offline and guarded real modes."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import sys
from typing import Any, Callable, Iterable, Mapping

from xuanyi_npc.agents import GameNPCAgent
from xuanyi_npc.agents.game_npc import GameNPCAgentConfig
from xuanyi_npc.agents.deepseek import DeepSeekAdapterConfig, DeepSeekChatAdapter
from xuanyi_npc.agents.llm import LLMAdapterError, LLMRequest, LLMResponse
from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.application.clinic import ClinicActionInput, ClinicContributionInput, ClinicError, ClinicService
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import (
    AgentRuntimeKind,
    AuthorityMode,
    CooperativeTurnResult,
    GameNPCDecision,
    GameNPCDecisionProposal,
    NPCCapability,
    PendingActionConfirmation,
    PlayerContribution,
    PlayerContributionEvaluation,
    PlayerContributionType,
    SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_planning import GoalCondition, GoalConditionType, PlanStepIntent
from xuanyi_npc.domain.planning_contract import (
    GameNPCTurnProposal,
    GoalUpdateKind,
    GoalUpdateProposal,
    PlanDraft,
    PlanStepDraft,
    PlanUpdateKind,
    PlanUpdateProposal,
)
from xuanyi_npc.storage import JsonStateStore, StateNotFoundError
from xuanyi_npc.evaluation.costing import DeepSeekPilotPricing, load_deepseek_pilot_pricing
from xuanyi_npc.evaluation.request_ledger import DurableRequestLedger


PROJECT_ROOT = Path(__file__).resolve().parents[3]
V1_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "ce2a_context_behavior" / "v1"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "ce2a_context_behavior" / "v3"
CASE_ROOT = PROJECT_ROOT / "src" / "xuanyi_npc" / "resources" / "cases"
CAMPAIGN_PATH = PROJECT_ROOT / "src" / "xuanyi_npc" / "resources" / "campaign" / "cross_episode_rules_v1.json"
SOURCE_SNAPSHOT_PATHS = (
    "pyproject.toml",
    "src/xuanyi_npc/evaluation/ce2a_context_behavior.py",
    "src/xuanyi_npc/application/clinic.py",
    "src/xuanyi_npc/application/cooperative_context.py",
    "src/xuanyi_npc/application/cooperative_runtime.py",
    "src/xuanyi_npc/agents/game_npc.py",
    "src/xuanyi_npc/agents/bounded_output.py",
    "src/xuanyi_npc/agents/deepseek.py",
    "src/xuanyi_npc/evaluation/costing.py",
    "src/xuanyi_npc/evaluation/request_ledger.py",
    "src/xuanyi_npc/storage/sqlite_cooperation.py",
    "src/xuanyi_npc/resources/campaign/cross_episode_rules_v1.json",
    "src/xuanyi_npc/resources/cases/old_paper_umbrella.json",
    "src/xuanyi_npc/resources/cases/gray_hearth_inn.json",
    "src/xuanyi_npc/resources/cases/moon_well_echo.json",
    "src/xuanyi_npc/resources/cases/lantern_alley_conflicting_testimony.json",
    "src/xuanyi_npc/resources/cases/mist_ferry_borrowed_lantern.json",
    "src/xuanyi_npc/resources/cases/returning_contract_nameless_shrine.json",
    "tests/test_ce2a_context_behavior_evaluation.py",
)
FIXED_NOW = datetime(2026, 9, 26, 8, 0, tzinfo=timezone.utc)
EXPECTED_V2_SCENARIO_IDS = (
    "H01", "H02", "H03", "H04", "H05", "H06", "P02", "R01", "O01", "N01", "N02", "P01O", "P01A",
)


class EvaluationError(RuntimeError):
    """Stable local harness error."""


class RealRunBlocked(EvaluationError):
    """Raised whenever real-run prerequisites are incomplete."""


class FrozenClock:
    def now(self) -> datetime:
        return FIXED_NOW


class FixedPlayerIds:
    def __init__(self, value: str) -> None:
        self.value = value

    def new_player_id(self) -> str:
        return self.value


class FixedSessionIds:
    def __init__(self, value: str) -> None:
        self.value = value

    def new_session_id(self) -> str:
        return self.value


@dataclass(frozen=True)
class Bundle:
    root: Path
    public: dict[str, Any]
    private: dict[str, Any]
    protocol: dict[str, Any]

    @property
    def scenarios(self) -> tuple[dict[str, Any], ...]:
        return tuple(self.public["scenarios"])


@dataclass(frozen=True)
class SyntheticPrice:
    input_per_million: Decimal
    output_per_million: Decimal
    currency: str = "CNY"

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens) * self.input_per_million
            + Decimal(output_tokens) * self.output_per_million
        ) / Decimal(1_000_000)


class BudgetGuard:
    """Reservation-based budget arithmetic; token bounds must be supplied."""

    def __init__(self, *, price: SyntheticPrice, total_cap: Decimal, per_turn_cap: Decimal) -> None:
        self.price = price
        self.total_cap = total_cap
        self.per_turn_cap = per_turn_cap
        self.reserved = Decimal("0")

    def reserve(self, *, input_token_upper_bound: int | None, output_token_upper_bound: int | None) -> Decimal:
        if input_token_upper_bound is None or output_token_upper_bound is None:
            raise RealRunBlocked("reliable token upper bounds are required; characters are not tokens")
        upper = self.price.cost(input_token_upper_bound, output_token_upper_bound)
        if upper > self.per_turn_cap or self.reserved + upper > self.total_cap:
            raise RealRunBlocked("budget is insufficient for the next call upper bound")
        self.reserved += upper
        return upper

    def settle(self, reservation: Decimal, *, input_tokens: int | None, output_tokens: int | None) -> Decimal:
        # Missing usage remains charged at the conservative reservation, never zero.
        if input_tokens is None or output_tokens is None:
            return reservation
        actual = self.price.cost(input_tokens, output_tokens)
        self.reserved -= reservation - actual
        return actual


def _resolve_config_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def validate_real_run_config(
    config: Mapping[str, Any], *, bundle: Bundle, confirm_paid: bool,
) -> tuple[DeepSeekPilotPricing, tuple[str, ...]]:
    """Validate every non-secret prerequisite before an adapter is created."""

    frozen_protocol = _load_json(FIXTURE_ROOT / "protocol.json")
    if ({k:v for k,v in bundle.protocol.items() if k != "real_run"}
            != {k:v for k,v in frozen_protocol.items() if k != "real_run"}):
        raise RealRunBlocked("real config may only fill the frozen real_run section")

    if config.get("enabled") is not True:
        raise RealRunBlocked("real run is disabled in the frozen configuration")
    if config.get("paid_authorized") is not True or not confirm_paid:
        raise RealRunBlocked("explicit paid authorization is required in config and on the command line")
    if not config.get("authorization_id"):
        raise RealRunBlocked("a stable paid authorization_id is required")
    if config.get("provider") != "deepseek" or not config.get("model"):
        raise RealRunBlocked("an explicit supported provider and model are required")
    if config.get("temperature") != 0 or config.get("thinking") != "disabled":
        raise RealRunBlocked("real evaluation parameters must remain temperature=0 and thinking=disabled")
    try:
        total = Decimal(str(config["total_budget_cny"]))
        per_turn = Decimal(str(config["per_turn_budget_cny"]))
    except (KeyError, ArithmeticError, ValueError):
        raise RealRunBlocked("positive total and per-turn budgets are required") from None
    if total <= 0 or per_turn <= 0 or per_turn > total:
        raise RealRunBlocked("budget caps must be positive and per-turn must not exceed total")
    price_value = config.get("price_snapshot_path")
    expected_hash = config.get("price_snapshot_sha256")
    if not price_value or not expected_hash:
        raise RealRunBlocked("a verified price snapshot path and SHA-256 are required")
    price_path = _resolve_config_path(str(price_value))
    if not price_path.is_file() or _sha256(price_path) != expected_hash:
        raise RealRunBlocked("price snapshot is missing or its SHA-256 does not match")
    try:
        verified = date.fromisoformat(str(config["price_verified_on"]))
        valid_through = date.fromisoformat(str(config["price_valid_through"]))
    except (KeyError, ValueError):
        raise RealRunBlocked("price verification and validity dates are required") from None
    today = datetime.now(timezone.utc).date()
    if verified > today or valid_through < today or valid_through < verified:
        raise RealRunBlocked("price verification is future-dated or expired")
    pricing = load_deepseek_pilot_pricing(price_path)
    if pricing.model != config["model"]:
        raise RealRunBlocked("price snapshot model does not match the frozen model")
    scenario_ids = tuple(config.get("scenario_ids") or ())
    known = {item["scenario_id"] for item in bundle.scenarios}
    if not scenario_ids or len(set(scenario_ids)) != len(scenario_ids) or not set(scenario_ids) <= known:
        raise RealRunBlocked("real run requires a non-empty unique subset of frozen scenario IDs")
    repeats = config.get("repeats")
    if not isinstance(repeats, int) or isinstance(repeats, bool) or repeats < 1 or repeats > int(bundle.protocol["repeats"]):
        raise RealRunBlocked("real run repeats exceed the frozen protocol")
    if int(config.get("adapter_default_max_output_tokens", 0)) != 512 or int(config.get("initial_a1_max_output_tokens", 0)) != 2048:
        raise RealRunBlocked("A1 initial/repair output limits must remain frozen at 2048/512")
    return pricing, scenario_ids


def ensure_real_run_allowed(config: dict[str, Any]) -> None:
    """Compatibility guard used by preflight; never reads credentials."""

    validate_real_run_config(config, bundle=load_bundle(), confirm_paid=False)


class _PerTurnBudgetExceeded(LLMAdapterError):
    code = "ce2a_per_turn_budget_exhausted"

    def __init__(self) -> None:
        super().__init__("the next provider call exceeds the per-turn budget", abort_episode=True)


class PaidRequestEvidenceError(LLMAdapterError):
    """A ledger failure is fatal even when provider usage is already known."""

    code = "request_evidence_persistence_failed"

    def __init__(self, record, *, usage=None, provider_error=None):
        super().__init__("request evidence could not be durably saved; batch stopped",
                         usage=usage, abort_episode=True)
        self.record = record
        self.provider_error = provider_error
        self.prior_usages = getattr(provider_error, "prior_usages", ())


class PaidEvidenceAdapter:
    """Adds per-turn reservation and durable started/terminal evidence."""

    def __init__(self, adapter: DeepSeekChatAdapter, ledger: DurableRequestLedger, *,
                 per_turn_cap: Decimal, identity: Mapping[str, Any]) -> None:
        self.adapter = adapter
        self.ledger = ledger
        self.per_turn_cap = per_turn_cap
        self.identity = dict(identity)
        self.requests: list[LLMRequest] = []
        self.responses: list[LLMResponse] = []
        self.known_turn_cost = Decimal("0")
        self.uncertain = False
        self.evidence_failure: PaidRequestEvidenceError | None = None

    @property
    def config(self):
        return self.adapter.config

    @property
    def request_budget(self):
        return self.adapter.request_budget

    def _append(self, record, *, usage=None, provider_error=None):
        try:
            self.ledger.append(record)
        except Exception as exc:
            self.uncertain = True
            self.evidence_failure = PaidRequestEvidenceError(
                record, usage=usage, provider_error=provider_error)
            raise self.evidence_failure from exc

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self.evidence_failure is not None:
            raise self.evidence_failure
        reservation = self.adapter.conservative_request_reservation(request)
        if self.known_turn_cost + reservation.maximum_cost_cny > self.per_turn_cap:
            raise _PerTurnBudgetExceeded()
        fingerprint = hashlib.sha256(request.model_dump_json().encode("utf-8")).hexdigest()
        attempt = len(self.requests) + 1
        common = self.identity | {
            "attempt":attempt, "request_fingerprint":fingerprint,
            "reservation":reservation.model_dump(mode="json"),
        }
        self._append(common | {"status":"started", "provider_adapter_invoked":False})
        self.requests.append(request)
        common = common | {"provider_adapter_invoked":True}
        try:
            response = self.adapter.complete(request)
        except Exception as exc:
            usage = getattr(exc, "usage", None)
            if usage is None or usage.estimated_cost is None:
                self.uncertain = True
                self.adapter.request_budget.halt_unknown_usage()
            else:
                self.known_turn_cost += usage.estimated_cost
            self._append(common | {
                "status":"error", "error_code":getattr(exc, "code", type(exc).__name__),
                "usage":usage.model_dump(mode="json") if usage is not None else None,
                "budget":_provider_budget_snapshot(self.adapter),
            }, usage=usage, provider_error=exc)
            raise
        usage = response.usage
        if usage is None or usage.estimated_cost is None:
            self.uncertain = True
            self.adapter.request_budget.halt_unknown_usage()
            error = LLMAdapterError("provider usage is missing; paid run stopped", usage=usage, abort_episode=True)
            self._append(common | {"status":"error", "error_code":"usage_unavailable",
                                         "usage":usage.model_dump(mode="json") if usage else None,
                                         "budget":_provider_budget_snapshot(self.adapter)},
                         usage=usage, provider_error=error)
            raise error
        self.known_turn_cost += usage.estimated_cost
        self._append(common | {
            "status":"completed", "provider_request_id":usage.provider_request_id,
            "usage":usage.model_dump(mode="json"), "output":response.content,
            "budget":_provider_budget_snapshot(self.adapter),
        }, usage=usage)
        self.responses.append(response)
        return response


def _provider_budget_snapshot(adapter: Any) -> dict[str, Any]:
    guard = adapter.request_budget
    return {"max_cost_cny":str(guard.max_cost_cny), "known_cost_cny":str(guard.known_cost_cny),
            "maximum_committed_cost_cny":str(guard.maximum_committed_cost_cny),
            "can_start_episode":guard.can_start_episode, "halted":guard.halted, "stop_reason":guard.stop_reason}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_bundle(root: Path = FIXTURE_ROOT) -> Bundle:
    public = _load_json(root / "scenarios.json")
    private = _load_json(root / "rubric_private.json")
    if base_name := public.get("base_fixture"):
        base_path = (root / base_name).resolve()
        if _sha256(base_path) != public["base_fixture_sha256"]:
            raise EvaluationError("v2 public base fixture hash mismatch")
        base = _load_json(base_path)
        remove = set(public.get("remove_scenario_ids", ()))
        overrides = public.get("scenario_overrides", {})
        metadata = public.get("scenario_metadata", {})
        resolved = []
        for item in base["scenarios"]:
            if item["scenario_id"] in remove:
                continue
            resolved.append(item | overrides.get(item["scenario_id"], {}) | metadata.get(item["scenario_id"], {}))
        resolved.extend(public.get("add_scenarios", ()))
        public = {key:value for key, value in public.items() if key not in {
            "base_fixture", "base_fixture_sha256", "remove_scenario_ids", "scenario_overrides", "scenario_metadata", "add_scenarios"
        }} | {"scenarios":resolved}
    if base_name := private.get("base_fixture"):
        base_path = (root / base_name).resolve()
        if _sha256(base_path) != private["base_fixture_sha256"]:
            raise EvaluationError("v2 private base fixture hash mismatch")
        base = _load_json(base_path)
        remove = set(private.get("remove_scenario_ids", ()))
        overrides = private.get("rubric_overrides", {})
        resolved = [item | overrides.get(item["scenario_id"], {}) for item in base["rubrics"] if item["scenario_id"] not in remove]
        resolved.extend(private.get("add_rubrics", ()))
        private = {key:value for key, value in private.items() if key not in {
            "base_fixture", "base_fixture_sha256", "remove_scenario_ids", "rubric_overrides", "add_rubrics"
        }} | {"rubrics":resolved}
    return Bundle(
        root=root,
        public=public,
        private=private,
        protocol=_load_json(root / "protocol.json"),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def frozen_schedule(bundle: Bundle) -> tuple[dict[str, Any], ...]:
    schedule: list[dict[str, Any]] = []
    for repeat in range(1, int(bundle.protocol["repeats"]) + 1):
        for index, scenario in enumerate(bundle.scenarios, start=1):
            if (repeat == 1 and index % 2 == 1) or (repeat == 2 and index % 2 == 0):
                conditions = ("C", "T")
            else:
                conditions = ("T", "C")
            for condition in conditions:
                schedule.append({
                    "run_index": len(schedule) + 1,
                    "scenario_id": scenario["scenario_id"],
                    "repeat": repeat,
                    "condition": condition,
                })
    return tuple(schedule)


def _expand(value: str, target: int | None) -> str:
    if not target:
        return value
    suffix = "｜评测夹具公开填充"
    result = value
    while len(result) < target:
        result += suffix
    return result[:target]


def _domain_id(value: str | None) -> str | None:
    """Map human-readable fixture labels to the lowercase domain ID alphabet."""

    return value.lower() if value is not None else None


class ControlledOfflineAdapter:
    """Deterministic no-network adapter at the production adapter boundary."""

    class Config:
        max_output_tokens = 2048

    config = Config()

    def __init__(self, *, scenario: dict[str, Any], tool_name, target_id: str) -> None:
        self.scenario = scenario
        self.tool_name = tool_name
        self.target_id = target_id
        self.requests: list[LLMRequest] = []
        self.responses: list[LLMResponse] = []

    def _valid_content(self) -> str:
        operation_id = _domain_id(self.scenario["current"]["operation_id"])
        assert operation_id is not None
        if setup := self.scenario.get("setup"):
            diagnosis_id = setup["pending_source"]["diagnosis_id"]
            second = PlanStepDraft(
                intent=PlanStepIntent.PROPOSE_DIAGNOSIS,
                capability=NPCCapability.PROPOSE_DIAGNOSIS,
                suggested_tool=ToolName.SUBMIT_DIAGNOSIS,
                public_target_id=diagnosis_id,
                public_summary="如获批准，再提出公开诊断候选。",
                completion_signal=GoalCondition(condition_type=GoalConditionType.DIAGNOSIS_SUBMITTED),
            )
        else:
            second = PlanStepDraft(
                intent=PlanStepIntent.INVESTIGATE,
                capability=NPCCapability.USE_TOOL,
                suggested_tool=self.tool_name,
                public_target_id=self.target_id,
                public_summary="随后可核对一个当前公开调查项。",
                completion_signal=GoalCondition(
                    condition_type=GoalConditionType.INVESTIGATION_COMPLETED,
                    reference_id=self.target_id,
                ),
            )
        proposal = GameNPCTurnProposal(
            goal_update=GoalUpdateProposal(
                update=GoalUpdateKind.KEEP,
                public_rationale="离线模拟保持当前公开目标。",
            ),
            plan_update=PlanUpdateProposal(
                update=PlanUpdateKind.CREATE,
                draft=PlanDraft(steps=(
                    PlanStepDraft(
                        intent=PlanStepIntent.DISCUSS_WITH_PLAYER,
                        capability=NPCCapability.EXPLAIN,
                        public_summary="先给出不执行工具的公开回应。",
                        completion_signal=GoalCondition(
                            condition_type=GoalConditionType.MINIMUM_CLUE_COUNT,
                            threshold=99,
                        ),
                    ),
                    second,
                )),
                public_rationale="离线模拟只验证运行链，不评价语义理解。",
            ),
            decision=GameNPCDecisionProposal(
                contribution_evaluation=PlayerContributionEvaluation(
                    contribution_id=operation_id,
                    disposition=SuggestionDisposition.REQUEST_MORE_EVIDENCE,
                    reason_code="offline_semantic_unscored",
                    explanation="这是可控离线 adapter 输出，语义效果留待人工评分。",
                ),
                capability=NPCCapability.EXPLAIN,
                action=AgentAction(
                    action_id=f"npc_{operation_id}",
                    action_type=AgentActionType.RESPOND,
                    dialogue=f"离线模拟回复 {self.scenario['scenario_id']}；该回复不代表模型理解能力。",
                    confidence=0.0,
                ),
                explanation="只返回文字，不调用案件工具。",
            ),
        )
        return proposal.model_dump_json()

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        mode = self.scenario.get("adapter_mode", "valid")
        attempt = len(self.requests)
        if mode == "valid" or (mode == "format_repair" and attempt == 2):
            content = self._valid_content()
        else:
            content = "offline-invalid-structured-output"
        response = LLMResponse(content=content, usage=None)
        self.responses.append(response)
        return response


def _clinic(root: Path, scenario: dict[str, Any], *, context_enabled: bool, adapter: Any) -> ClinicService:
    scenario_slug = scenario["scenario_id"].lower()
    player_id = f"player_eval_{scenario_slug}"
    session_id = f"session_eval_{scenario_slug}"
    return ClinicService(
        store=JsonStateStore(root),
        base_catalog=CaseCatalog(CASE_ROOT),
        campaign_path=CAMPAIGN_PATH,
        clock=FrozenClock(),
        player_id_factory=FixedPlayerIds(player_id),
        session_id_factory=FixedSessionIds(session_id),
        game_npc_agent=GameNPCAgent(adapter),
        cooperative_memory_service=None,
        reflection_service=None,
        memory_mode="disabled",
        cooperative_record_enabled=True,
        cooperative_context_v2_enabled=context_enabled,
    )


class _LegalDiagnosisProposalAgent:
    """Setup-only deterministic agent that traverses the production policy path."""

    config = GameNPCAgentConfig()
    runtime_kind = AgentRuntimeKind.TEST_DOUBLE

    def __init__(self, diagnosis_id: str) -> None:
        self.diagnosis_id = diagnosis_id

    def decide(self, value):
        evidence = tuple(item.clue_id for item in value.case_observation.discovered_clues)
        proposal = GameNPCDecisionProposal(
                contribution_evaluation=PlayerContributionEvaluation(
                    contribution_id=value.turn_id,
                    disposition=SuggestionDisposition.ACCEPT,
                    reason_code="evaluation_legal_diagnosis_proposal",
                    explanation="依据已公开证据提出诊断候选。",
                ),
                capability=NPCCapability.PROPOSE_DIAGNOSIS,
                action=AgentAction(
                    action_id=f"npc_{value.turn_id}",
                    action_type=AgentActionType.USE_TOOL,
                    dialogue="提出一个公开诊断候选，等待玩家确认。",
                    tool_call=ToolCallRequest(
                        name=ToolName.SUBMIT_DIAGNOSIS,
                        arguments={"diagnosis_id":self.diagnosis_id, "evidence_clue_ids":list(evidence)},
                    ),
                    confidence=0.5,
                ),
                explanation="这只是待确认提案，不执行诊断提交。",
            )
        return GameNPCDecision(
            decision_id=f"decision_{value.turn_id}", turn_id=value.turn_id,
            proposal=proposal, llm_attempts=1, used_fallback=False,
        )


def _setup_legal_pending(clinic: ClinicService, scenario: dict[str, Any], player_id: str, session_id: str) -> None:
    setup = scenario.get("setup")
    if not setup:
        return
    clinic.cooperative_record_enabled = False
    action_index = 0
    while setup.get("complete_all_investigations"):
        observation = clinic.resume_case(player_id, scenario["case_id"], session_id).observation
        assert observation is not None
        if not observation.available_investigations:
            break
        item = observation.available_investigations[0]
        action_index += 1
        clinic.submit_case_action(ClinicActionInput(
            player_id=player_id, case_id=scenario["case_id"], session_id=session_id,
            operation_id=f"fixture_setup_{scenario['scenario_id'].lower()}_{action_index}",
            action_type="investigation", selection_id=item.investigation_id,
        ))
    source = setup["pending_source"]
    proposal_operation = _domain_id(source["proposal_operation_id"])
    clinic.game_npc_agent = _LegalDiagnosisProposalAgent(source["diagnosis_id"])
    result = clinic.submit_player_contribution(ClinicContributionInput(
        player_id=player_id, case_id=scenario["case_id"], session_id=session_id,
        operation_id=proposal_operation, text="基于全部公开调查形成诊断提案。",
        contribution_type=PlayerContributionType.SUGGESTION,
    ))
    expected = f"confirm_decision_{proposal_operation}"
    if result.status.value != "proposal_pending" or expected not in clinic.cooperative_pending:
        raise EvaluationError("legal diagnosis setup did not produce the expected pending proposal")
    clinic.cooperative_record_enabled = True


def _history_result(operation_id: str, dialogue: str, rationale: str, environment: str | None) -> CooperativeTurnResult:
    operation_id = _domain_id(operation_id)
    assert operation_id is not None
    proposal = GameNPCDecisionProposal(
        contribution_evaluation=PlayerContributionEvaluation(
            contribution_id=operation_id,
            disposition=SuggestionDisposition.REQUEST_MORE_EVIDENCE,
            reason_code="synthetic_fixture_history",
            explanation="人工构造的评测历史，不是案件权威事实。",
        ),
        capability=NPCCapability.EXPLAIN,
        action=AgentAction(
            action_id=f"fixture_action_{operation_id}",
            action_type=AgentActionType.RESPOND,
            dialogue=dialogue,
            confidence=0.0,
        ),
        explanation="人工评测夹具的公开回复。",
    )
    decision = GameNPCDecision(
        decision_id=f"fixture_decision_{operation_id}",
        turn_id=operation_id,
        proposal=proposal,
        llm_attempts=1,
        used_fallback=False,
    )
    return CooperativeTurnResult(
        turn_id=operation_id,
        status="responded",
        decision=decision,
        runtime_kind=AgentRuntimeKind.TEST_DOUBLE,
        authority_mode=AuthorityMode.AUTONOMOUS,
        public_rationale=rationale,
        environment_message=environment,
    )


def _seed_history(clinic: ClinicService, scenario: dict[str, Any], player_id: str, session_id: str) -> None:
    repository = clinic.cooperative_history_repository
    assert repository is not None
    for item in scenario["history"]:
        target = item.get("expand_fields_to_characters")
        contribution = PlayerContribution(
            contribution_id=_domain_id(item["operation_id"]),
            player_id=player_id,
            case_id=scenario["case_id"],
            session_id=session_id,
            contribution_type=PlayerContributionType(item["contribution_type"]),
            public_text=_expand(item["player_text"], target),
            created_at=FIXED_NOW,
        )
        stable = {
            "player_id": player_id,
            "case_id": scenario["case_id"],
            "session_id": session_id,
            "operation_id": _domain_id(item["operation_id"]),
            "text": contribution.public_text,
            "contribution_type": contribution.contribution_type.value,
            "responds_to_decision_id": None,
            "pending_confirmation_id": None,
        }
        record, created = repository.begin(
            player_id=player_id,
            case_id=scenario["case_id"],
            session_id=session_id,
            operation_id=_domain_id(item["operation_id"]),
            stable_request=stable,
            contribution_json=contribution.model_dump_json(),
            owner_process_id="ce2a_offline_fixture",
        )
        if not created:
            raise EvaluationError(f"duplicate fixture history operation: {item['operation_id']}")
        result = _history_result(
            item["operation_id"],
            _expand(item["npc_dialogue"], target),
            _expand(item["public_rationale"], target),
            _expand("人工评测夹具环境信息。", target) if target else None,
        )
        repository.mark_prepared(record, result.decision.model_dump_json())
        repository.complete(record, result.model_dump_json())


def _pending(clinic: ClinicService, scenario: dict[str, Any], player_id: str, session_id: str) -> None:
    case = clinic.base_catalog.get(scenario["case_id"])
    assert case is not None
    revision = clinic.store.load_case_session(session_id).revision
    for item in scenario["pending"]:
        investigation = next(x for x in case.investigations if x.investigation_id == item["public_id"])
        action = AgentAction(
            action_id=f"pending_action_{str(_domain_id(item['confirmation_id']))}",
            action_type=AgentActionType.USE_TOOL,
            dialogue=f"公开提议调查 {item['public_id']}，等待确认。",
            tool_call=ToolCallRequest(
                name=INVESTIGATION_TOOL_BY_ACTION[investigation.action_type],
                arguments={"investigation_id": item["public_id"]},
            ),
            confidence=0.5,
        )
        pending = PendingActionConfirmation(
            confirmation_id=_domain_id(item["confirmation_id"]),
            decision_id=_domain_id(item["decision_id"]),
            player_id=player_id,
            case_id=scenario["case_id"],
            session_id=session_id,
            action=action,
            authority_mode=AuthorityMode.CONFIRMATION_REQUIRED,
            public_rationale=item["public_rationale"],
            case_revision=revision,
        )
        with clinic._cooperative_pending_lock:
            clinic.cooperative_pending[pending.confirmation_id] = pending


def _setup_run(
    run_root: Path, scenario: dict[str, Any], condition: str, *, adapter_override: Any | None = None,
) -> tuple[ClinicService, Any, str, str, dict[str, Any]]:
    case = CaseCatalog(CASE_ROOT).get(scenario["case_id"])
    if case is None:
        raise EvaluationError(f"unknown case {scenario['case_id']}")
    # The simulated proposal uses the case's first initially public action for
    # its future (non-executed) plan step.  Scenario bindings remain the
    # semantic probe; a gated binding must not accidentally turn a valid
    # adapter response into an unrelated contract-repair probe.
    investigation = case.investigations[0]
    primary_id = investigation.investigation_id
    adapter = adapter_override or ControlledOfflineAdapter(
        scenario=scenario,
        tool_name=INVESTIGATION_TOOL_BY_ACTION[investigation.action_type],
        target_id=primary_id,
    )
    clinic = _clinic(run_root, scenario, context_enabled=condition == "T", adapter=adapter)
    home = clinic.create_player(f"CE2A评测{scenario['scenario_id']}")
    player_id = home.player_summary.player_id
    opened = clinic.start_case(player_id, scenario["case_id"], cooperative=True)
    if opened.session_id is None or opened.observation is None:
        raise EvaluationError(f"could not start case {scenario['case_id']}")
    session_id = opened.session_id
    _setup_legal_pending(clinic, scenario, player_id, session_id)
    clinic.game_npc_agent = GameNPCAgent(adapter)
    _seed_history(clinic, scenario, player_id, session_id)
    _pending(clinic, scenario, player_id, session_id)
    if scenario.get("restart_before_current"):
        clinic = _clinic(run_root, scenario, context_enabled=condition == "T", adapter=adapter)
    session = clinic.store.load_case_session(session_id)
    try:
        agent_state = clinic.store.load_cooperative_agent_state(
            session_id, player_id=player_id, case_id=scenario["case_id"],
        ).model_dump(mode="json")
    except StateNotFoundError:
        agent_state = None
    pending_snapshot = sorted(clinic.cooperative_pending)
    initial = {
        "player_id": player_id,
        "case_id": scenario["case_id"],
        "session_id": session_id,
        "session": session.model_dump(mode="json"),
        "agent_state": agent_state,
        "pending_confirmation_ids": pending_snapshot,
        "history_operation_ids": [_domain_id(item["operation_id"]) for item in scenario["history"]],
        "memory_mode": clinic.memory_mode,
        "reflection_enabled": clinic.reflection_service is not None,
        "record_enabled": clinic.cooperative_record_enabled,
    }
    initial["equivalence_hash"] = hashlib.sha256(_canonical({
        **initial,
        "record_enabled": True,
    }).encode("utf-8")).hexdigest()
    return clinic, adapter, player_id, session_id, initial


def _request_dump(request: LLMRequest) -> dict[str, Any]:
    return request.model_dump(mode="json")


def _execute_one(run_root: Path, scenario: dict[str, Any], condition: str, repeat: int, *, adapter_override: Any | None = None) -> dict[str, Any]:
    clinic, adapter, player_id, session_id, initial = _setup_run(
        run_root, scenario, condition, adapter_override=adapter_override,
    )
    before = clinic.store.load_case_session(session_id)
    current = scenario["current"]
    request = ClinicContributionInput(
        player_id=player_id,
        case_id=scenario["case_id"],
        session_id=session_id,
        operation_id=_domain_id(current["operation_id"]),
        text=current["text"],
        contribution_type=PlayerContributionType(current["contribution_type"]),
        responds_to_decision_id=_domain_id(current.get("responds_to_decision_id")),
        pending_confirmation_id=_domain_id(current.get("pending_confirmation_id")),
    )
    result: CooperativeTurnResult | None = None
    error: dict[str, Any] | None = None
    try:
        result = clinic.submit_player_contribution(request)
        status = "completed"
    except ClinicError as exc:
        status = "failed"
        error = {"code": exc.code, "message": str(exc)}
    except KeyboardInterrupt:
        status = "interrupted"
        error = {"code": "keyboard_interrupt", "message": "run interrupted; automatic resume is forbidden"}
    after = clinic.store.load_case_session(session_id)
    agent = clinic.game_npc_agent
    traces = getattr(agent, "last_context_builds", lambda: ())()
    result_dump = result.model_dump(mode="json") if result else None
    return {
        "artifact_schema_version": "ce2a_context_behavior_run_v2",
        "scenario_id": scenario["scenario_id"],
        "condition": condition,
        "repeat": repeat,
        "status": status,
        "semantic_score": None,
        "semantic_score_status": "unscored",
        "public_scenario": {
            key: scenario[key]
            for key in (
                "scenario_id", "case_id", "bindings", "initial_state", "history",
                "pending", "current", "preconditions", "history_dependency_eligible",
            )
        }
        | ({"binding_note": scenario["binding_note"]} if "binding_note" in scenario else {})
        | ({"known_policy_constraint": scenario["known_policy_constraint"]} if "known_policy_constraint" in scenario else {}),
        "initial_state": initial,
        "request": request.model_dump(mode="json"),
        "adapter_requests": [_request_dump(item) for item in adapter.requests],
        "adapter_call_count": len(adapter.requests),
        "usage": [response.usage.model_dump(mode="json") if response.usage else None for response in adapter.responses],
        "context_build_traces": [asdict(item) for item in traces],
        "result": result_dump,
        "final_reply": result.decision.proposal.action.dialogue if result else None,
        "planning": {
            "goal_changed": result.goal_changed if result else None,
            "plan_changed": result.plan_changed if result else None,
            "plan_summary": list(result.plan_public_summary) if result else [],
            "error_code": result.error_code if result else None,
        },
        "world": {
            "revision_before": before.revision,
            "revision_after": after.revision,
            "action_count_before": len(before.action_history),
            "action_count_after": len(after.action_history),
            "new_actions": [item.model_dump(mode="json") for item in after.action_history[len(before.action_history):]],
        },
        "pending_after": sorted(clinic.cooperative_pending),
        "fallback": bool(result and result.decision.used_fallback),
        "repair_kind": result.decision.repair_kind if result else None,
        "error": error,
    }


def _scenario_map(bundle: Bundle) -> dict[str, dict[str, Any]]:
    return {item["scenario_id"]: item for item in bundle.scenarios}


def _copy_frozen_inputs(bundle: Bundle, output: Path) -> None:
    destination = output / "frozen_inputs"
    destination.mkdir()
    for name in ("scenarios.json", "rubric_private.json", "protocol.json", "manifest.json"):
        source = bundle.root / name
        if source.exists():
            shutil.copy2(source, destination / name)
    (destination / "resolved_scenarios.json").write_text(
        json.dumps(bundle.public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "resolved_rubric_private.json").write_text(
        json.dumps(bundle.private, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (destination / "resolved_protocol.json").write_text(
        json.dumps(bundle.protocol, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    source_root = destination / "source_snapshot"
    for relative in SOURCE_SNAPSHOT_PATHS:
        source = PROJECT_ROOT / relative
        target = source_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    identities = {
        relative: {"sha256": _sha256(PROJECT_ROOT / relative), "snapshot_path": f"frozen_inputs/source_snapshot/{relative}"}
        for relative in SOURCE_SNAPSHOT_PATHS
    }
    try:
        git_status = subprocess.run(
            ["git", "status", "--short"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.splitlines()
        git_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        git_status, git_commit = None, None
    (output / "workspace_identity.json").write_text(json.dumps({
        "identity_schema_version":"ce2a_evaluation_workspace_identity_v1",
        "git_commit":git_commit,
        "git_status_short":git_status,
        "files":identities,
        "python":sys.version,
        "dependencies": {
            name: importlib.metadata.version(name)
            for name in ("pydantic", "httpx", "mcp")
        },
        "note":"Exact selected source contents are copied beside this file; commit alone is not the identity.",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _pair_differences(artifacts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for item in artifacts:
        grouped.setdefault((item["scenario_id"], item["repeat"]), {})[item["condition"]] = item
    output = []
    for (scenario_id, repeat), pair in sorted(grouped.items()):
        c, t = pair.get("C"), pair.get("T")
        if c is None or t is None:
            output.append({"scenario_id": scenario_id, "repeat": repeat, "pair_complete": False})
            continue
        per_attempt = []
        for index in range(max(len(c["adapter_requests"]), len(t["adapter_requests"]))):
            cr = c["adapter_requests"][index] if index < len(c["adapter_requests"]) else None
            tr = t["adapter_requests"][index] if index < len(t["adapter_requests"]) else None
            c_text = "" if cr is None else "\n".join(x["content"] for x in cr["messages"])
            t_text = "" if tr is None else "\n".join(x["content"] for x in tr["messages"])
            per_attempt.append({
                "attempt": index + 1,
                "c_present": cr is not None,
                "t_present": tr is not None,
                "c_message_roles": [] if cr is None else [x["role"] for x in cr["messages"]],
                "t_message_roles": [] if tr is None else [x["role"] for x in tr["messages"]],
                "t_has_v2_rules": "CE2A 协作上下文规则" in t_text,
                "c_has_v2_rules": "CE2A 协作上下文规则" in c_text,
                "content_equal": cr == tr,
                "response_schema_equal": (
                    cr is not None and tr is not None
                    and cr["response_schema"] == tr["response_schema"]
                ),
                "repair_reuses_initial_snapshot_c": (
                    index == 0 or cr is None
                    or cr["messages"][: len(c["adapter_requests"][0]["messages"])]
                    == c["adapter_requests"][0]["messages"]
                ),
                "repair_reuses_initial_snapshot_t": (
                    index == 0 or tr is None
                    or tr["messages"][: len(t["adapter_requests"][0]["messages"])]
                    == t["adapter_requests"][0]["messages"]
                ),
            })
        boundary_ok = all(
            not item["c_has_v2_rules"]
            and item["t_has_v2_rules"]
            and item["response_schema_equal"]
            and item["repair_reuses_initial_snapshot_c"]
            and item["repair_reuses_initial_snapshot_t"]
            for item in per_attempt
        )
        output.append({
            "scenario_id": scenario_id,
            "repeat": repeat,
            "pair_complete": True,
            "initial_equivalent": c["initial_state"]["equivalence_hash"] == t["initial_state"]["equivalence_hash"],
            "allowed_expected_differences": ["v2 rules", "completed history envelopes", "pending public projection", "history omission metadata"],
            "adapter_boundary_ok": boundary_ok,
            "attempts": per_attempt,
        })
    return output


def export_blind_material(artifacts: Iterable[dict[str, Any]], output: Path, *, fixture_id: str = "ce2a-v2") -> dict[str, Any]:
    rows = []
    mapping = []
    for item in artifacts:
        raw = f"{item['scenario_id']}:{item['repeat']}:{item['condition']}:{fixture_id}"
        blind_id = "blind_" + hashlib.sha256(raw.encode()).hexdigest()[:12]
        rows.append({
            "blind_id": blind_id,
            "scenario_id": item["scenario_id"],
            "repeat": item["repeat"],
            "public_background": item["public_scenario"],
            "current_request": item["request"],
            "final_reply": item["final_reply"],
            "runtime_boundary": {
                "status": item["status"],
                "actual_tools": item["world"]["new_actions"],
                "world_revision_changed": item["world"]["revision_before"] != item["world"]["revision_after"],
                "error": item["error"],
            },
            "score": None,
            "reason": None,
        })
        mapping.append({"blind_id": blind_id, "scenario_id": item["scenario_id"], "repeat": item["repeat"], "condition": item["condition"]})
    rows.sort(key=lambda value: value["blind_id"])
    payload = {"schema_version":"ce2a_blind_review_v1","instructions":"score must remain null until a human assigns 0, 1, or 2 and gives a reason","items":rows}
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output.parent / "blind_mapping_private.json").write_text(json.dumps({"items":mapping}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def build_report(artifacts: Iterable[dict[str, Any]], scores: dict[str, Any] | None = None, mapping: dict[str, Any] | None = None,
                 *, expected_scenario_ids: Iterable[str] | None = None, repeats: int = 2) -> dict[str, Any]:
    rows = list(artifacts)
    counts = {name: sum(1 for row in rows if row["status"] == name) for name in ("completed", "failed", "interrupted")}
    score_by_key: dict[tuple[str, int, str], int] = {}
    if scores is not None and mapping is not None:
        by_blind = {item["blind_id"]: item for item in mapping["items"]}
        for item in scores["items"]:
            score = item.get("score")
            if score is None:
                continue
            if score not in (0, 1, 2) or not item.get("reason"):
                raise EvaluationError("scored blind rows require score 0/1/2 and a non-empty reason")
            identity = by_blind[item["blind_id"]]
            score_by_key[(identity["scenario_id"], identity["repeat"], identity["condition"])] = score
    pairs = {"win":0,"tie":0,"loss":0,"unscored":0,"missing":0}
    expected_ids = tuple(expected_scenario_ids or EXPECTED_V2_SCENARIO_IDS)
    for scenario_id in expected_ids:
        for repeat in range(1, repeats + 1):
            pair_rows = [row for row in rows if row["scenario_id"] == scenario_id and row["repeat"] == repeat]
            if {row["condition"] for row in pair_rows} != {"C", "T"}:
                pairs["missing"] += 1
                continue
            c = score_by_key.get((scenario_id, repeat, "C"))
            t = score_by_key.get((scenario_id, repeat, "T"))
            if c is None or t is None:
                pairs["unscored"] += 1
            elif t > c:
                pairs["win"] += 1
            elif t < c:
                pairs["loss"] += 1
            else:
                pairs["tie"] += 1
    known_usage = sum(1 for row in rows for value in row["usage"] if value is not None)
    total_calls = sum(row["adapter_call_count"] for row in rows)
    return {
        "schema_version":"ce2a_context_behavior_report_v1",
        "run_counts": {
            **counts,
            "unscored": len(rows) - len(score_by_key),
            "total": len(rows),
            "expected": len(expected_ids) * repeats * 2,
            "missing": len(expected_ids) * repeats * 2 - len(rows),
        },
        "coverage": {"independent_scenarios": len({row["scenario_id"] for row in rows}), "repeated_runs_are_not_independent": True},
        "paired_semantic_result": pairs,
        "runtime": {
            "repairs": sum(row["repair_kind"] is not None for row in rows),
            "fallbacks": sum(row["fallback"] for row in rows),
            "adapter_calls": total_calls,
            "policy_or_permission_blocks": sum(bool(row["planning"]["error_code"]) for row in rows),
            "plan_blocks": sum(
                row["planning"]["error_code"] in {"goal_plan_policy_rejected", "action_outside_active_plan"}
                for row in rows
            ),
            "permission_blocks": sum(
                bool(row["error"]) and row["error"]["code"] in {
                    "confirmation_unavailable", "confirmation_ownership_mismatch",
                }
                for row in rows
            ),
            "declared_existing_policy_constraints": sum(
                "known_policy_constraint" in row["public_scenario"] for row in rows
            ),
        },
        "usage_and_cost": {
            "known_usage_calls": known_usage,
            "unknown_usage_calls": total_calls - known_usage,
            "real_cost": "unknown; no real calls were made",
            "estimated_cost": "not computed from characters",
            "synthetic_test_price": "covered only by BudgetGuard unit tests; it is not a real quote and is not applied to missing usage",
        },
        "interpretation_limit": "offline controlled responses validate construction and boundaries only; semantic model understanding remains human-unscored",
    }


def run_offline(*, output: Path, bundle: Bundle | None = None) -> Path:
    bundle = bundle or load_bundle()
    if output.exists():
        raise EvaluationError(f"output already exists and will not be overwritten: {output}")
    output.mkdir(parents=True)
    (output / "RUNNING.json").write_text(json.dumps({"status":"running","resume_allowed":False}, indent=2) + "\n", encoding="utf-8")
    _copy_frozen_inputs(bundle, output)
    schedule = frozen_schedule(bundle)
    scenarios = _scenario_map(bundle)
    artifacts: list[dict[str, Any]] = []
    runs_root = output / "runs"
    runs_root.mkdir()
    try:
        for entry in schedule:
            run_name = f"{entry['run_index']:02d}_{entry['scenario_id']}_r{entry['repeat']}_{entry['condition']}"
            run_root = runs_root / run_name
            run_root.mkdir()
            artifact = _execute_one(run_root / "state", scenarios[entry["scenario_id"]], entry["condition"], entry["repeat"])
            artifact["run_index"] = entry["run_index"]
            (run_root / "artifact.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            artifacts.append(artifact)
    except BaseException:
        (output / "RUNNING.json").write_text(json.dumps({"status":"interrupted","resume_allowed":False,"reason":"possible model/tool boundary already crossed; start a new output directory"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    differences = _pair_differences(artifacts)
    (output / "pair_differences.json").write_text(json.dumps(differences, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    export_blind_material(artifacts, output / "blind_review.json", fixture_id=bundle.public["fixture_id"])
    report = build_report(
        artifacts, expected_scenario_ids=(item["scenario_id"] for item in bundle.scenarios),
        repeats=int(bundle.protocol["repeats"]),
    )
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "RUNNING.json").unlink()
    (output / "COMPLETE.json").write_text(json.dumps({"status":"complete","run_count":len(artifacts)}, indent=2) + "\n", encoding="utf-8")
    return output


def _default_real_adapter_factory(config: Mapping[str, Any], pricing: DeepSeekPilotPricing) -> DeepSeekChatAdapter:
    env_config = DeepSeekAdapterConfig.from_env(os.environ)
    expected_base = str(config["base_url"]).rstrip("/")
    if env_config.model != config["model"] or env_config.base_url != expected_base:
        raise RealRunBlocked("environment provider model/base URL does not match the frozen real-run config")
    explicit = env_config.model_copy(update={
        "timeout_seconds":float(config["timeout_seconds"]),
        "max_output_tokens":int(config["adapter_default_max_output_tokens"]),
        "pilot_max_cost_cny":Decimal(str(config["total_budget_cny"])),
    })
    return DeepSeekChatAdapter(explicit, pricing=pricing)


def run_real(
    *, output: Path, confirm_paid: bool, bundle: Bundle | None = None,
    adapter_factory: Callable[[Mapping[str, Any], DeepSeekPilotPricing], Any] | None = None,
    claim_root: Path | None = None,
) -> Path:
    """Run an explicitly authorized paid subset; callers must never auto-resume it."""

    bundle = bundle or load_bundle()
    config = bundle.protocol["real_run"]
    pricing, scenario_ids = validate_real_run_config(config, bundle=bundle, confirm_paid=confirm_paid)
    if output.exists():
        raise EvaluationError(f"output already exists and will not be overwritten: {output}")
    claim_root = claim_root or PROJECT_ROOT / "runtime_evaluations" / ".ce2a_real_run_claims"
    claim_root.mkdir(parents=True, exist_ok=True)
    claim = claim_root / f"{config['authorization_id']}.json"
    try:
        with claim.open("x", encoding="utf-8") as stream:
            json.dump({"authorization_id":config["authorization_id"], "status":"claimed", "output":str(output)}, stream)
    except FileExistsError:
        raise RealRunBlocked("this paid authorization_id was already claimed; automatic rerun is forbidden") from None
    output.mkdir(parents=True)
    (output / "RUNNING.json").write_text(json.dumps({
        "status":"running", "mode":"real", "resume_allowed":False,
        "authorization_id":config["authorization_id"],
    }, indent=2) + "\n", encoding="utf-8")
    _copy_frozen_inputs(bundle, output)
    (output / "real_run_config_public.json").write_text(json.dumps({
        key:value for key,value in config.items() if "key" not in key.lower()
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger = DurableRequestLedger(output / "request_ledger.jsonl")
    factory = adapter_factory or _default_real_adapter_factory
    base_adapter = None
    wrapper = None
    artifacts: list[dict[str, Any]] = []
    runs_root = output / "runs"
    runs_root.mkdir()
    schedule = [entry for entry in frozen_schedule(bundle)
                if entry["scenario_id"] in scenario_ids and entry["repeat"] <= int(config["repeats"])]
    scenarios = _scenario_map(bundle)
    try:
        base_adapter = factory(config, pricing)
        for index, entry in enumerate(schedule, start=1):
            wrapper = PaidEvidenceAdapter(
                base_adapter, ledger, per_turn_cap=Decimal(str(config["per_turn_budget_cny"])),
                identity={"authorization_id":config["authorization_id"], "scenario_id":entry["scenario_id"],
                          "condition":entry["condition"], "repeat":entry["repeat"]},
            )
            run_name = f"{index:02d}_{entry['scenario_id']}_r{entry['repeat']}_{entry['condition']}"
            run_root = runs_root / run_name
            run_root.mkdir()
            artifact = _execute_one(
                run_root / "state", scenarios[entry["scenario_id"]], entry["condition"], entry["repeat"],
                adapter_override=wrapper,
            )
            artifact["run_index"] = index
            (run_root / "artifact.json").write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            artifacts.append(artifact)
            if wrapper.evidence_failure is not None:
                raise wrapper.evidence_failure
            if wrapper.uncertain or base_adapter.request_budget.halted:
                raise EvaluationError("paid request result or usage is uncertain; manual reconciliation is required")
    except BaseException as exc:
        (output / "RUNNING.json").write_text(json.dumps({
            "status":"interrupted", "resume_allowed":False,
            "reason":"paid request or tool boundary may have been crossed; do not auto-resume",
            "error_code":getattr(exc, "code", type(exc).__name__),
            "failed_request_evidence":(wrapper.evidence_failure.record
                                       if wrapper and wrapper.evidence_failure else None),
            "budget":_provider_budget_snapshot(base_adapter) if base_adapter else None,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise
    finally:
        close = getattr(base_adapter, "close", None)
        if callable(close):
            close()
    (output / "pair_differences.json").write_text(json.dumps(_pair_differences(artifacts), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    export_blind_material(artifacts, output / "blind_review.json", fixture_id=bundle.public["fixture_id"])
    report = build_report(artifacts, expected_scenario_ids=scenario_ids, repeats=int(config["repeats"]))
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "RUNNING.json").unlink()
    (output / "COMPLETE.json").write_text(json.dumps({
        "status":"complete", "run_count":len(artifacts), "authorization_id":config["authorization_id"],
    }, indent=2) + "\n", encoding="utf-8")
    return output


def _preflight_checks(bundle: Bundle) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check":name,"status":"ready" if ok else "blocked","detail":detail})

    ids = [item["scenario_id"] for item in bundle.scenarios]
    add("scenario_set", tuple(ids) == EXPECTED_V2_SCENARIO_IDS, f"found {ids}")
    rubrics = {item["scenario_id"] for item in bundle.private["rubrics"]}
    add("private_rubric", rubrics == set(ids), "one model-invisible rubric row per scenario")
    public_serialized = _canonical(bundle.public)
    canaries = [item["model_invisible_canary"] for item in bundle.private["rubrics"]]
    add("private_answers_model_invisible", not any(value in public_serialized for value in canaries),
        "private rubric canaries are absent from the public scenario fixture")
    p01o = next((item for item in bundle.scenarios if item["scenario_id"] == "P01O"), None)
    leak_ok = bool(
        p01o and p01o["bindings"][0]["public_id"] not in p01o["current"]["text"]
        and p01o["initial_state"].get("expected_plan") is None
        and next(item for item in bundle.scenarios if item["scenario_id"] == "H04")["history_dependency_eligible"] is False
    )
    add("scenario_information_leak_audit", leak_ok,
        "P01O current text/Plan do not uniquely disclose the referenced pending object; H04 is a negative control")
    valid_types = {item.value for item in PlayerContributionType}
    catalog = CaseCatalog(CASE_ROOT)
    binding_errors = []
    for scenario in bundle.scenarios:
        case = catalog.get(scenario["case_id"])
        if case is None:
            binding_errors.append(f"{scenario['scenario_id']}: missing case")
            continue
        public = {item.investigation_id: item.public_description for item in case.investigations}
        public.update({item.diagnosis_id:item.public_description for item in case.diagnosis_candidates.values()})
        for binding in scenario["bindings"]:
            if public.get(binding["public_id"]) != binding["public_description"]:
                binding_errors.append(f"{scenario['scenario_id']}: {binding['public_id']} mismatch")
        for history in scenario["history"]:
            if history["source"] != "synthetic_evaluation_fixture" or history["contribution_type"] not in valid_types:
                binding_errors.append(f"{scenario['scenario_id']}: invalid synthetic history metadata")
        if scenario["current"]["contribution_type"] not in valid_types:
            binding_errors.append(f"{scenario['scenario_id']}: invalid current contribution type")
    add("public_bindings_and_history_sources", not binding_errors, "; ".join(binding_errors) or "all case IDs/descriptions and synthetic-history markers match")
    schedule = frozen_schedule(bundle)
    expected = int(bundle.protocol["expected_turn_count"])
    per_turn = int(bundle.protocol["max_adapter_calls_per_turn"])
    add("frozen_schedule", len(schedule) == expected == len(ids) * int(bundle.protocol["repeats"]) * 2, f"{len(schedule)} turns in deterministic AB/BA order")
    add("call_upper_bound", len(schedule) * per_turn == int(bundle.protocol["max_total_adapter_calls"]), f"{len(schedule)} x {per_turn} = {len(schedule)*per_turn}, no adapter retry layer")
    legal_conditions = bundle.protocol["conditions"] == {"C":{"record_enabled":True,"context_v2_enabled":False},"T":{"record_enabled":True,"context_v2_enabled":True}}
    add("condition_contract", legal_conditions, "C and T both record; only T enables context v2")
    add("memory_and_reflection", bundle.protocol["memory_mode"] == "disabled" and bundle.protocol["reflection_enabled"] is False, "optional memory and Reflection are disabled equally")
    synthetic = bundle.protocol["synthetic_test_pricing"]
    suggested = bundle.protocol["suggested_not_authorized_budget_cny"]
    budget_ok = (
        synthetic.get("is_real_quote") is False
        and Decimal(synthetic["input_price_per_million"]) >= 0
        and Decimal(synthetic["output_price_per_million"]) >= 0
        and Decimal(suggested["total"]) > 0
        and Decimal(suggested["per_turn"]) > 0
    )
    add("budget_configuration", budget_ok, "synthetic prices are labeled non-quotes; suggested caps remain unauthorized")
    manifest_path = bundle.root / "manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.is_file() else {"files":{}}
    manifest_mismatches = (["manifest.json missing"] if not manifest_path.is_file() else []) + [
        path for path, expected_hash in manifest["files"].items()
        if not (PROJECT_ROOT / path).is_file() or _sha256(PROJECT_ROOT / path) != expected_hash
    ]
    add(
        "frozen_content_identity",
        not manifest_mismatches,
        "all fixture, evaluator, runtime, case and test hashes match"
        if not manifest_mismatches else f"mismatch: {manifest_mismatches}",
    )
    real = bundle.protocol["real_run"]
    try:
        ensure_real_run_allowed(real)
    except RealRunBlocked as exc:
        add("real_run_guard", True, f"blocked as required: {exc}")
    else:
        add("real_run_guard", False, "real run unexpectedly allowed")
    # Build every production Clinic starting point in disposable isolated roots.
    setup_errors = []
    # Windows can briefly retain an SQLite WAL handle after the final context
    # manager exits; preflight data is disposable and cleanup must not turn a
    # successful validation into a false failure.
    with tempfile.TemporaryDirectory(prefix="ce2a-preflight-", ignore_cleanup_errors=True) as temporary:
        for scenario in bundle.scenarios:
            hashes = []
            for condition in ("C", "T"):
                root = Path(temporary) / scenario["scenario_id"] / condition
                try:
                    clinic, _, _, session_id, initial = _setup_run(root, scenario, condition)
                    hashes.append(initial["equivalence_hash"])
                    if scenario["scenario_id"] == "R01" and clinic.cooperative_pending:
                        raise EvaluationError("restart restored process-local pending")
                    if scenario["scenario_id"] in {"P01O", "P01A"} and len(clinic.cooperative_pending) != 1:
                        raise EvaluationError(f"{scenario['scenario_id']} did not contain one runtime-produced pending entry")
                    if setup := scenario.get("setup"):
                        state = initial["agent_state"]
                        if state is None or state["current_goal"]["goal_type"] != scenario["initial_state"]["expected_goal_type"]:
                            raise EvaluationError(f"{scenario['scenario_id']} goal precondition mismatch")
                        if state["current_plan"] != scenario["initial_state"]["expected_plan"]:
                            raise EvaluationError(f"{scenario['scenario_id']} plan precondition mismatch")
                        if initial["session"]["submitted_diagnosis_id"] is not None:
                            raise EvaluationError(f"{scenario['scenario_id']} setup executed diagnosis instead of proposing")
                    observation = clinic.resume_case(initial["player_id"], scenario["case_id"], session_id).observation
                    if observation.session_revision != initial["session"]["revision"]:
                        raise EvaluationError("unexpected setup revision drift")
                except Exception as exc:
                    setup_errors.append(f"{scenario['scenario_id']}/{condition}: {type(exc).__name__}: {exc}")
            if len(set(hashes)) > 1:
                setup_errors.append(f"{scenario['scenario_id']}: C/T initial identity mismatch")
    add("production_setup_and_isolation", not setup_errors, "; ".join(setup_errors) or f"all {len(ids)*2} C/T starts are independently writable and equivalent")
    add("O01_binding_deviation", True, "uses two valid long turns; older complete turn is omitted because one legal turn cannot exceed 12000 characters")
    return checks


def preflight(*, report_path: Path, bundle: Bundle | None = None) -> dict[str, Any]:
    bundle = bundle or load_bundle()
    checks = _preflight_checks(bundle)
    result = {
        "schema_version":"ce2a_context_behavior_preflight_v2",
        "fixture_id":bundle.public["fixture_id"],
        "overall":"ready" if all(item["status"] == "ready" for item in checks) else "blocked",
        "checks":checks,
        "fixture_sha256": {name:_sha256(bundle.root / name) for name in ("scenarios.json","rubric_private.json","protocol.json")},
        "real_model_calls":0,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.with_suffix(".json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# CE-2A 上下文行为离线预检", "", f"总体：**{result['overall']}**", "", "| 检查 | 状态 | 说明 |", "|---|---|---|"]
    lines.extend(f"| {item['check']} | {item['status']} | {item['detail'].replace('|','/')} |" for item in checks)
    lines += ["", "真实模型调用：0。语义理解效果未评估。", ""]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return result


def _load_artifacts(output: Path) -> list[dict[str, Any]]:
    return [_load_json(path) for path in sorted((output / "runs").glob("*/artifact.json"))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CE-2A offline context behavior evaluation")
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--report", type=Path, required=True)
    run = sub.add_parser("run-offline")
    run.add_argument("--output", type=Path, required=True)
    report = sub.add_parser("report")
    report.add_argument("--output", type=Path, required=True)
    report.add_argument("--scores", type=Path)
    real = sub.add_parser("run-real")
    real.add_argument("--config", type=Path, default=FIXTURE_ROOT / "protocol.json")
    real.add_argument("--output", type=Path, required=True)
    real.add_argument("--confirm-paid", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            value = preflight(report_path=args.report)
            print(json.dumps({"overall":value["overall"],"report":str(args.report)}, ensure_ascii=False))
            return 0 if value["overall"] == "ready" else 2
        if args.command == "run-offline":
            run_offline(output=args.output)
            print(json.dumps({"status":"complete","output":str(args.output)}, ensure_ascii=False))
            return 0
        if args.command == "report":
            artifacts = _load_artifacts(args.output)
            scores = _load_json(args.scores) if args.scores else None
            mapping_path = args.output / "blind_mapping_private.json"
            mapping = _load_json(mapping_path) if scores else None
            value = build_report(artifacts, scores=scores, mapping=mapping)
            (args.output / "report.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(value, ensure_ascii=False))
            return 0
        protocol = _load_json(args.config)
        frozen = load_bundle()
        if protocol.get("fixture_version") != frozen.protocol.get("fixture_version"):
            raise EvaluationError("real config fixture_version must match the frozen scenario bundle")
        bundle = Bundle(root=frozen.root, public=frozen.public, private=frozen.private, protocol=protocol)
        run_real(output=args.output, confirm_paid=args.confirm_paid, bundle=bundle)
        print(json.dumps({"status":"complete","output":str(args.output)}, ensure_ascii=False))
        return 0
    except (EvaluationError, RealRunBlocked) as exc:
        print(json.dumps({"status":"blocked","error":str(exc)}, ensure_ascii=False))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
