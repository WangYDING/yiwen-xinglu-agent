"""Frozen-scenario runner for one budget-bounded real MentorAction pilot."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from pydantic import SecretStr, ValidationError

from xuanyi_npc.agents.llm import ChatMessage, ChatRole, LLMRequest
from xuanyi_npc.agents.mentor import MENTOR_SYSTEM_PROMPT
from xuanyi_npc.domain.mentor import MentorAction
from xuanyi_npc.resources.runtime import read_runtime_text

from .real_mentor_transport import (
    AUTHORIZED_BUDGET_CNY,
    MODEL_ID,
    MentorPilotBudget,
    MentorPilotTransportError,
    RealMentorDeepSeekTransport,
    load_mentor_pilot_pricing,
)


MANIFEST_RESOURCE = "acceptance/r6_real_mentor_pilot_v2.json"
PRICING_RESOURCE = "pilot/deepseek_v4_flash_mentor_pricing_2026-08-13.json"


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_request(item: dict[str, Any], *, repair_code: str | None = None) -> LLMRequest:
    public = {"scenario_id": item["scenario_id"], "request_id": item["request_id"], "public_context": item["public_context"], "allowed_mentor_actions": item["allowed_action_types"]}
    messages = [ChatMessage(role=ChatRole.SYSTEM, content=MENTOR_SYSTEM_PROMPT), ChatMessage(role=ChatRole.USER, content=json.dumps(public, ensure_ascii=False, sort_keys=True))]
    if repair_code:
        messages.append(ChatMessage(role=ChatRole.USER, content=f"唯一一次公开契约修复。错误码：{repair_code}。继续使用相同公开上下文，只输出合法MentorAction JSON。"))
    schema: dict[str, Any] = {
        "title": "MentorAction",
        "type": "object",
        "additionalProperties": False,
        "required": ["action_type", "message"],
        "properties": {
            "action_type": {"type": "string", "enum": item["allowed_action_types"]},
            "message": {"type": "string", "minLength": 1},
            "hint_id": ({"type": ["string", "null"], "enum": [*item.get("allowed_hint_ids", []), None]}),
            "referenced_public_evidence_ids": {"type": "array", "maxItems": 0},
            "referenced_ability_ids": {"type": "array", "maxItems": 0},
            "referenced_relationship_dimensions": {"type": "array", "maxItems": 0},
        },
    }
    return LLMRequest(messages=tuple(messages), response_schema=schema)


def validate_action(item: dict[str, Any], content: str) -> MentorAction:
    try:
        action = MentorAction.model_validate_json(content)
    except ValidationError as exc:
        raise ValueError("mentor_action_schema_invalid") from exc
    if action.action_type.value not in item["allowed_action_types"]:
        raise ValueError("action_type_not_allowed")
    allowed_hints = set(item.get("allowed_hint_ids", []))
    if action.hint_id is not None and action.hint_id not in allowed_hints:
        raise ValueError("unknown_public_hint_id")
    if action.referenced_public_evidence_ids or action.referenced_ability_ids or action.referenced_relationship_dimensions:
        raise ValueError("unknown_public_reference")
    return action


def evaluate_content(item: dict[str, Any], action: MentorAction) -> dict[str, Any]:
    text = action.message.lower()
    required = item["expectation"]["required_concept_groups"]
    missing = [group for group in required if not any(term.lower() in text for term in group)]
    leaks = [term for term in item["expectation"]["forbidden_terms"] if term.lower() in text]
    player_action = any(term in text for term in item["expectation"]["player_action_claims"])
    expected_type = action.action_type.value in item["expectation"]["accepted_action_types"]
    return {"teaching_correct": not missing and expected_type, "missing_concept_groups": missing, "forbidden_leaks": leaks, "mentor_replaced_player_action": player_action, "safe": not leaks and not player_action, "scenario_complete": not missing and expected_type and not leaks and not player_action}


def _sanitized_usage(usage, cost: Decimal) -> dict[str, Any]:
    return {"model": usage.provider_model, "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens, "cache_hit_input_tokens": usage.cache_hit_input_tokens, "cache_miss_input_tokens": usage.cache_miss_input_tokens, "latency_ms": round(usage.latency_ms, 3), "cost_cny": str(cost)}


def run_paid_pilot(*, output: Path, budget: Decimal, transport_factory=RealMentorDeepSeekTransport) -> int:
    if budget != AUTHORIZED_BUDGET_CNY:
        return 2
    manifest = json.loads(read_runtime_text(MANIFEST_RESOURCE))
    pricing = load_mentor_pilot_pricing(Path(__file__).parents[1] / "resources" / PRICING_RESOURCE)
    env = dotenv_values(Path.cwd() / ".env", encoding="utf-8", interpolate=False)
    key = (env.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        print("拒绝运行：API Key不存在。")
        return 2
    output.mkdir(parents=True, exist_ok=True)
    raw_path = output / "raw_result.json"
    sanitized_path = output / "sanitized_result.json"
    guard = MentorPilotBudget(budget, pricing)
    transport = transport_factory(SecretStr(key), guard, timeout_seconds=manifest["config"]["timeout_seconds"])
    records: list[dict[str, Any]] = []
    raw_records: list[dict[str, Any]] = []
    stop_reason = None
    try:
        transport.discover_flash()
        for item in manifest["requests"]:
            attempts = 0
            action = None
            response = None
            contract_code = None
            while attempts < 2:
                attempts += 1
                try:
                    response = transport.complete(build_request(item, repair_code=contract_code))
                    action = validate_action(item, response.content)
                    break
                except ValueError as exc:
                    contract_code = str(exc)
                    if attempts >= 2:
                        break
                except MentorPilotTransportError as exc:
                    stop_reason = exc.code
                    break
            if stop_reason:
                records.append({"request_id": item["request_id"], "status": "not_completed", "attempts": attempts, "failure_code": stop_reason})
                break
            if action is None or response is None:
                records.append({"request_id": item["request_id"], "status": "contract_failed", "attempts": attempts, "failure_code": contract_code})
                continue
            cost = guard.confirmed_cost - sum((Decimal(x["usage"]["cost_cny"]) for x in records if x.get("usage")), Decimal("0"))
            evaluation = evaluate_content(item, action)
            records.append({"request_id": item["request_id"], "scenario_id": item["scenario_id"], "status": "observed", "attempts": attempts, "action": action.model_dump(mode="json"), "evaluation": evaluation, "usage": _sanitized_usage(response.usage, cost)})
            raw_records.append({"request_id": item["request_id"], "response": response.raw_response})
            if not evaluation["safe"] or (item["request_id"].startswith("inheritance_") and not evaluation["teaching_correct"]):
                stop_reason = "behavior_safety_stop"
                break
    except MentorPilotTransportError as exc:
        stop_reason = exc.code
    finally:
        transport.close()
    observed = {x["request_id"] for x in records}
    for item in manifest["requests"]:
        if item["request_id"] not in observed:
            records.append({"request_id": item["request_id"], "scenario_id": item["scenario_id"], "status": "not_observed"})
    raw = {"pilot_id": manifest["pilot_id"], "responses": raw_records}
    raw_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_sha = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    result = {"pilot_id": manifest["pilot_id"], "model": MODEL_ID, "authorized_budget_cny": "0.05", "effective_budget_cny": str(guard.limit), "models_calls": transport.models_calls, "chat_calls": transport.chat_calls, "confirmed_cost_cny": str(guard.confirmed_cost), "unverified_reserve_cny": str(guard.unverified_reserve), "maximum_committed_cost_cny": str(guard.maximum_committed_cost), "stop_reason": stop_reason, "records": records, "raw_result_sha256": raw_sha, "boundaries": {"bge_calls": 0, "embedding_calls": 0, "human_contacts": 0, "remote_operations": 0}}
    sanitized_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "completed" if stop_reason is None else "stopped", "stop_reason": stop_reason, "models_calls": transport.models_calls, "chat_calls": transport.chat_calls, "cost_cny": str(guard.confirmed_cost), "raw_sha256": raw_sha}, ensure_ascii=False))
    return 0 if stop_reason is None else 4
