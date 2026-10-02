"""Fail-closed pool control and recoverable execution status for V2.1."""
from __future__ import annotations

import json
from pathlib import Path

from xuanyi_npc.evaluation.v2_contracts import GradeStatus, V2RunArtifact


MODEL_OUTCOMES = {None, "max_turns_exceeded"}


def blocking_reason(artifact: V2RunArtifact) -> str | None:
    """Return an implementation/protocol blocker; ordinary model failure is allowed."""
    if artifact.failure_code not in MODEL_OUTCOMES:
        return f"implementation_failure:{artifact.failure_code}"
    if artifact.input_tokens is None or artifact.output_tokens is None or artifact.known_cost_cny is None:
        return "usage_evidence_missing"
    trace = next((g for g in artifact.grades if g.grader_id == "trace_integrity"), None)
    if trace is None or trace.status is not GradeStatus.PASS:
        return "trace_evidence_failure"
    authorization = next((g for g in artifact.grades if g.grader_id == "authorization"), None)
    if authorization is not None and authorization.status in {GradeStatus.FAIL, GradeStatus.UNKNOWN}:
        return "permission_or_commit_gate_failure"
    return None


def write_execution_status(
    root: Path, *, planned: list[dict], started: list[dict], stop_reason: str | None
) -> None:
    started_count = len(started)
    payload = {
        "schema_version": "v2.1_execution_status_v1",
        "status": "COMPLETED" if started_count == len(planned) and stop_reason is None else "STOPPED",
        "planned_count": len(planned),
        "started_count": started_count,
        "stop_reason": stop_reason,
        "started": started,
        "unstarted": planned[started_count:],
    }
    path = root / "execution_status.json"
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
