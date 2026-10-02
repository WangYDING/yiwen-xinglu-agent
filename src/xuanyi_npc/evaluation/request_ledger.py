"""Durable per-request evidence independent of episode artifact creation."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from threading import Lock

from xuanyi_npc.agents.llm import LLMAdapter, LLMRequest, LLMResponse


class RequestEvidencePersistenceError(RuntimeError):
    code = "request_evidence_persistence_failed"


class DurableRequestLedger:
    def __init__(self, path: Path) -> None:
        self.path=path; self.path.parent.mkdir(parents=True,exist_ok=True); self._lock=Lock(); self._sequence=0
        if self.path.exists() and self.path.stat().st_size:
            self._sequence=sum(1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip())

    def append(self, record: dict) -> None:
        with self._lock:
            self._sequence += 1
            payload={"schema_version":"v2.1_request_ledger_v1","sequence":self._sequence,
                     "recorded_at":datetime.now(timezone.utc).isoformat(),**record}
            try:
                with self.path.open("a",encoding="utf-8",newline="\n") as stream:
                    stream.write(json.dumps(payload,ensure_ascii=False,separators=(",",":"))+"\n")
                    stream.flush(); os.fsync(stream.fileno())
            except Exception as exc:
                self._sequence -= 1
                raise RequestEvidencePersistenceError("request evidence could not be durably saved") from exc


def reconcile_request_ledger(path: Path, budget_snapshot: dict) -> dict:
    """Reconcile only known per-request costs; never infer missing request detail."""
    records=[json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    known=[]
    missing=0
    for record in records:
        usage=record.get("usage")
        if usage is None or usage.get("estimated_cost") is None:
            missing += 1
        else:
            known.append(str(usage["estimated_cost"]))
    from decimal import Decimal
    ledger_cost=sum((Decimal(value) for value in known),Decimal("0"))
    budget_cost=Decimal(str(budget_snapshot["known_cost_cny"]))
    return {"record_count":len(records),"missing_cost_count":missing,
            "ledger_known_cost_cny":str(ledger_cost),"budget_known_cost_cny":str(budget_cost),
            "reconciled":missing == 0 and ledger_cost == budget_cost}


class EvidenceRecordingLLMAdapter:
    """Record each completed provider response before returning it to the agent."""
    def __init__(self, adapter: LLMAdapter, ledger: DurableRequestLedger) -> None:
        self.adapter=adapter; self.ledger=ledger

    @property
    def request_budget(self): return self.adapter.request_budget

    @property
    def config(self): return self.adapter.config

    def complete(self, request: LLMRequest) -> LLMResponse:
        fingerprint=sha256(request.model_dump_json().encode("utf-8")).hexdigest()
        try:
            response=self.adapter.complete(request)
        except Exception as exc:
            usage=getattr(exc,"usage",None)
            self.ledger.append({"status":"error","request_fingerprint":fingerprint,
                "error_code":getattr(exc,"code",type(exc).__name__),
                "usage":usage.model_dump(mode="json") if usage is not None else None,
                "budget":self._budget_snapshot()})
            raise
        self.ledger.append({"status":"completed","request_fingerprint":fingerprint,
            "provider_request_id":response.usage.provider_request_id if response.usage else None,
            "usage":response.usage.model_dump(mode="json") if response.usage else None,
            "output":response.content,"budget":self._budget_snapshot()})
        return response

    def _budget_snapshot(self) -> dict:
        guard=self.request_budget
        return {"max_cost_cny":str(guard.max_cost_cny),"known_cost_cny":str(guard.known_cost_cny),
                "maximum_committed_cost_cny":str(guard.maximum_committed_cost_cny),
                "can_start_episode":guard.can_start_episode,"halted":guard.halted,"stop_reason":guard.stop_reason}
