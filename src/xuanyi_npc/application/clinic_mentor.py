"""Opt-in clinic mentor expression runtime with persistent process budget."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from pydantic import ConfigDict, Field

from xuanyi_npc.application.mentor_communication import (
    MentorActionV2, MentorCommunicationPlanner, PilotStopCategory,
    build_communication_request, deterministic_fallback, evaluate_mentor_action_v2,
    classify_transport_failure,
)
from xuanyi_npc.domain.base import DomainModel, Identifier
MAX_OUTPUT_TOKENS=512


class ClinicMentorRuntimeError(RuntimeError):
    def __init__(self,code):super().__init__(code);self.code=code


class ClinicMentorBudgetGuard:
    """Clinic-scoped exact Decimal budget compatible with mentor transport."""
    def __init__(self,limit:Decimal,pricing):
        if limit<=0 or limit>Decimal("0.05"):raise ValueError("clinic mentor budget must be in (0, 0.05]")
        self.limit=limit;self.max_cost_cny=limit;self.pricing=pricing;self.confirmed_cost=Decimal("0");self.unverified_reserve=Decimal("0");self.active_reserve=None;self.halted=False;self.checkpoint:Callable[[str],None]|None=None
    @property
    def maximum_committed_cost(self):return self.confirmed_cost+self.unverified_reserve+(self.active_reserve or Decimal("0"))
    def estimate(self,payload):
        encoded=json.dumps(payload,ensure_ascii=False,separators=(",",":"),sort_keys=True).encode("utf-8")
        unit=Decimal(self.pricing.unit_tokens)
        return (Decimal(len(encoded)+self.pricing.reservation_framing_bytes)*self.pricing.input_cache_miss_cny_per_million+Decimal(MAX_OUTPUT_TOKENS)*self.pricing.output_cny_per_million)/unit
    def reserve(self,payload):
        if self.halted or self.active_reserve is not None:raise ClinicMentorRuntimeError("budget_halted")
        amount=self.estimate(payload)
        if self.maximum_committed_cost+amount>self.limit:raise ClinicMentorRuntimeError("budget_exceeded")
        self.active_reserve=amount
        if self.checkpoint:self.checkpoint("reserved")
        return amount
    def settle(self,usage):
        if self.active_reserve is None:raise RuntimeError("no active clinic reservation")
        unit=Decimal(self.pricing.unit_tokens);cost=(Decimal(usage.cache_hit_input_tokens)*self.pricing.input_cache_hit_cny_per_million+Decimal(usage.cache_miss_input_tokens)*self.pricing.input_cache_miss_cny_per_million+Decimal(usage.output_tokens)*self.pricing.output_cny_per_million)/unit
        if cost>self.active_reserve:self.halt_unverified();raise ClinicMentorRuntimeError("usage_exceeds_reservation")
        self.confirmed_cost+=cost;self.active_reserve=None
        if self.checkpoint:self.checkpoint("settled")
        return cost
    def halt_unverified(self):
        if self.active_reserve is not None:self.unverified_reserve+=self.active_reserve;self.active_reserve=None
        self.halted=True
        if self.checkpoint:self.checkpoint("halted")


class ClinicMentorMode(str,Enum):
    OFF="off";FAKE="fake";DEEPSEEK="deepseek"


class ClinicMentorBudgetState(DomainModel):
    model_config=ConfigDict(extra="forbid",frozen=True)
    run_id: Identifier
    authorized_budget: Decimal=Field(gt=0,le=Decimal("0.05"))
    confirmed_cost: Decimal=Field(ge=0)
    unresolved_reserve: Decimal=Field(ge=0)
    request_count: int=Field(ge=0)
    repair_count: int=Field(ge=0)
    frozen: bool
    freeze_reason: str|None=None


class ClinicMentorResult(DomainModel):
    model_config=ConfigDict(extra="forbid",frozen=True)
    request_id: Identifier
    mode: ClinicMentorMode
    message: str
    model_passed: bool
    fallback_used: bool
    attempts: int
    stop_category: str|None=None
    notice: str|None=None
    covered_point_count: int
    required_point_count: int


@dataclass
class ClinicMentorRuntime:
    mode: ClinicMentorMode
    state_root: Path
    transport: Any|None=None
    authorized_budget: Decimal=Decimal("0.05")
    planner: MentorCommunicationPlanner=MentorCommunicationPlanner()

    def __post_init__(self):
        self.state_root=Path(self.state_root);self.path=self.state_root/"clinic_mentor_budget.json"
        self.metrics_path=self.state_root/"clinic_mentor_metrics.jsonl"
        if self.mode is ClinicMentorMode.DEEPSEEK:
            self.budget_state=self._load_or_create()
            if self.transport is None: raise ValueError("deepseek clinic mode requires explicit mentor transport")
            guard=self.transport.budget
            guard.confirmed_cost=self.budget_state.confirmed_cost
            guard.unverified_reserve=self.budget_state.unresolved_reserve
            guard.halted=self.budget_state.frozen
            guard.checkpoint=self._budget_checkpoint
        else:
            self.budget_state=ClinicMentorBudgetState(run_id="local_mentor",authorized_budget=self.authorized_budget,confirmed_cost=Decimal("0"),unresolved_reserve=Decimal("0"),request_count=0,repair_count=0,frozen=False)

    def _load_or_create(self):
        if self.path.exists():
            state=ClinicMentorBudgetState.model_validate_json(self.path.read_text(encoding="utf-8"))
            if state.authorized_budget!=self.authorized_budget: raise ValueError("new clinic budget authorization requires a new state directory")
            return state
        state=ClinicMentorBudgetState(run_id="clinic_"+secrets.token_hex(8),authorized_budget=self.authorized_budget,confirmed_cost=Decimal("0"),unresolved_reserve=Decimal("0"),request_count=0,repair_count=0,frozen=False)
        self._save(state);return state

    def _save(self,state):
        self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix(".tmp")
        tmp.write_text(state.model_dump_json(indent=2),encoding="utf-8");tmp.replace(self.path);self.budget_state=state

    def _sync(self,*,request_inc=0,repair_inc=0,frozen=None,reason=None):
        guard=self.transport.budget
        state=self.budget_state.model_copy(update={"confirmed_cost":guard.confirmed_cost,"unresolved_reserve":guard.unverified_reserve,"request_count":self.budget_state.request_count+request_inc,"repair_count":self.budget_state.repair_count+repair_inc,"frozen":guard.halted if frozen is None else frozen,"freeze_reason":reason if reason is not None else self.budget_state.freeze_reason})
        self._save(state)

    def _budget_checkpoint(self,event):
        """Persist the conservative reserve before HTTP so a crash cannot reset it."""
        guard=self.transport.budget
        unresolved=guard.unverified_reserve+(guard.active_reserve or Decimal("0"))
        in_flight=event=="reserved"
        state=self.budget_state.model_copy(update={"confirmed_cost":guard.confirmed_cost,"unresolved_reserve":unresolved,"frozen":guard.halted or in_flight,"freeze_reason":"unresolved_request" if in_flight else ("usage_unresolved" if guard.halted else None)})
        self._save(state)

    def express(self,request_id:str,public_context:dict[str,Any])->ClinicMentorResult:
        plan=self.planner.build(request_id,public_context);fallback=deterministic_fallback(plan)
        if self.mode is not ClinicMentorMode.DEEPSEEK or self.budget_state.frozen:
            notice="导师表达暂时切换为本地安全模式" if self.budget_state.frozen else None
            return ClinicMentorResult(request_id=request_id,mode=self.mode,message=fallback.message,model_passed=False,fallback_used=True,attempts=0,notice=notice,covered_point_count=len(plan.required_public_point_ids),required_point_count=len(plan.required_public_point_ids))
        missing=();last_eval=None
        for attempt in (1,2):
            try:
                response=self.transport.complete(build_communication_request(plan,repair_missing=missing))
                self._sync(request_inc=1,repair_inc=1 if attempt==2 else 0)
                content=response.content
                if any(term.lower() in content.lower() for term in ("AgentAction","病例工具","MCP工具","MENTOR_SECRET","精确门槛","正确答案","我已替你调查","我替你诊断","我替你处置","我自行授予")):
                    return self._freeze(plan,request_id,PilotStopCategory.SAFETY.value,attempt,request_inc=0)
                action=MentorActionV2.model_validate_json(content);evaluation=evaluate_mentor_action_v2(plan,action);last_eval=evaluation
                if not evaluation.safe:return self._freeze(plan,request_id,PilotStopCategory.SAFETY.value,attempt,request_inc=0)
                if evaluation.unknown_point_ids:
                    if attempt==2:return self._freeze(plan,request_id,PilotStopCategory.CONTRACT.value,attempt,request_inc=0)
                    missing=plan.required_public_point_ids;continue
                if evaluation.complete:
                    self._metric(request_id,"first" if attempt==1 else "repair",response.usage,None)
                    return ClinicMentorResult(request_id=request_id,mode=self.mode,message=action.message,model_passed=True,fallback_used=False,attempts=attempt,covered_point_count=len(action.covered_point_ids),required_point_count=len(plan.required_public_point_ids))
                missing=tuple(dict.fromkeys((*evaluation.missing_point_ids,*evaluation.unsupported_claimed_point_ids,*evaluation.contradicted_point_ids)))
            except Exception as exc:
                if hasattr(exc,"code"):
                    return self._freeze(plan,request_id,classify_transport_failure(exc.code).value,attempt)
                if attempt==2:return self._freeze(plan,request_id,PilotStopCategory.CONTRACT.value,attempt,request_inc=0)
                missing=plan.required_public_point_ids
        self._metric(request_id,"fallback",None,PilotStopCategory.TEACHING_QUALITY.value)
        return ClinicMentorResult(request_id=request_id,mode=self.mode,message=fallback.message,model_passed=False,fallback_used=True,attempts=2,stop_category=PilotStopCategory.TEACHING_QUALITY.value,covered_point_count=len(last_eval.missing_point_ids) if last_eval else 0,required_point_count=len(plan.required_public_point_ids))

    def _freeze(self,plan,request_id,category,attempt,request_inc=1):
        self.transport.budget.halted=True;self._sync(request_inc=request_inc,frozen=True,reason=category)
        self._metric(request_id,"frozen",None,category);fallback=deterministic_fallback(plan)
        return ClinicMentorResult(request_id=request_id,mode=self.mode,message=fallback.message,model_passed=False,fallback_used=True,attempts=attempt,stop_category=category,notice="导师表达暂时切换为本地安全模式",covered_point_count=len(plan.required_public_point_ids),required_point_count=len(plan.required_public_point_ids))

    def _metric(self,interaction,outcome,usage,stop):
        record={"run_id":self.budget_state.run_id,"interaction_type":interaction,"model":"deepseek-v4-flash" if self.mode is ClinicMentorMode.DEEPSEEK else "local","outcome":outcome,"input_tokens":getattr(usage,"input_tokens",0),"output_tokens":getattr(usage,"output_tokens",0),"latency_ms":getattr(usage,"latency_ms",0),"confirmed_cost":str(self.budget_state.confirmed_cost),"stop_category":stop}
        with self.metrics_path.open("a",encoding="utf-8") as handle:handle.write(json.dumps(record,ensure_ascii=False)+"\n")

    @property
    def status(self):
        remaining=max(Decimal("0"),self.budget_state.authorized_budget-self.budget_state.confirmed_cost-self.budget_state.unresolved_reserve)
        return {"mode":self.mode.value,"available":self.mode is not ClinicMentorMode.DEEPSEEK or not self.budget_state.frozen,"used_cost":str(self.budget_state.confirmed_cost),"remaining_budget":str(remaining),"fallback_active":self.budget_state.frozen}
