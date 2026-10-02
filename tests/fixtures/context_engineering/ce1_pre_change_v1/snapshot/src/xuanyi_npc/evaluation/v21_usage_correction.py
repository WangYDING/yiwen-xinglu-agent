"""Offline correction of artifact usage from uniquely identified request evidence."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from xuanyi_npc.evaluation.v2_contracts import V2RunArtifact


class UsageCorrectionError(ValueError):
    pass


def load_request_ledger(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def correct_artifact_usage(
    artifact: V2RunArtifact,
    ledger_records: Iterable[dict[str, Any]],
) -> tuple[V2RunArtifact, dict[str, Any]]:
    """Correct usage only when every artifact request has one exact ledger identity."""
    by_id: dict[str, dict[str, Any]] = {}
    for record in ledger_records:
        request_id=record.get("provider_request_id")
        if not request_id:
            continue
        if request_id in by_id:
            raise UsageCorrectionError(f"duplicate ledger request id: {request_id}")
        by_id[request_id]=record

    request_events=[event for event in artifact.events if event.event_type == "model_request_finished"]
    event_ids=[event.data.get("provider_request_id") for event in request_events]
    if any(not value for value in event_ids) or len(set(event_ids)) != len(event_ids):
        raise UsageCorrectionError("artifact request identities are missing or duplicated")

    corrected_events=[]; usages=[]; corrected_ids=[]
    for event in artifact.events:
        if event.event_type != "model_request_finished":
            corrected_events.append(event); continue
        request_id=event.data["provider_request_id"]
        record=by_id.get(request_id)
        if record is None or record.get("status") != "completed" or record.get("usage") is None:
            raise UsageCorrectionError(f"missing completed ledger record: {request_id}")
        usage=record["usage"]
        if not usage.get("measurement_complete",False) or usage.get("estimated_cost") is None:
            raise UsageCorrectionError(f"incomplete ledger usage: {request_id}")
        if event.data.get("structured_output") != record.get("output"):
            raise UsageCorrectionError(f"output mismatch: {request_id}")
        for field in ("input_tokens","output_tokens"):
            existing=event.data.get(field)
            if existing is not None and existing != usage[field]:
                raise UsageCorrectionError(f"{field} mismatch: {request_id}")
        data=dict(event.data)
        if data.get("usage_status") != "KNOWN" or data.get("estimated_cost") is None:
            corrected_ids.append(request_id)
            data.update({"usage_status":"KNOWN","input_tokens":usage["input_tokens"],
                         "output_tokens":usage["output_tokens"],"estimated_cost":usage["estimated_cost"],
                         "system_fingerprint":usage.get("system_fingerprint")})
        corrected_events.append(event.model_copy(update={"data":data}))
        usages.append(usage)

    corrected=artifact.model_copy(update={
        "events":tuple(corrected_events),
        "model":usages[-1]["provider_model"] if usages else artifact.model,
        "input_tokens":sum(item["input_tokens"] for item in usages),
        "output_tokens":sum(item["output_tokens"] for item in usages),
        "known_cost_cny":float(sum(__import__("decimal").Decimal(str(item["estimated_cost"])) for item in usages)),
        "system_fingerprints":tuple(dict.fromkeys(item["system_fingerprint"] for item in usages if item.get("system_fingerprint"))),
    })
    audit={
        "schema_version":"v2.1_usage_correction_audit_v1",
        "run_id":artifact.run_id,
        "source_artifact_sha256":sha256(artifact.model_dump_json().encode("utf-8")).hexdigest().upper(),
        "request_count":len(usages),
        "unique_request_ids":len(set(event_ids)),
        "corrected_request_ids":corrected_ids,
        "association_key":"provider_request_id",
        "output_equality_required":True,
        "input_tokens":corrected.input_tokens,
        "output_tokens":corrected.output_tokens,
        "known_cost_cny":corrected.known_cost_cny,
    }
    return corrected,audit
