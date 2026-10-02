from xuanyi_npc.evaluation.v2_stall_audit import (
    classify_memory_diagnosis, classify_task,
)


def _artifact(events, *, status="active", failure=None):
    return {
        "run_id": "t01_r01",
        "scenario_id": "T01",
        "events": events,
        "terminal_snapshot": {"terminal_status": status},
        "failure_code": failure,
    }


def test_stall_audit_classifies_diagnosis_without_later_tool_attempt():
    category, evidence = classify_task(_artifact([
        {"event_type": "tool_attempted", "turn": 8, "data": {"tool": "submit_diagnosis"}},
        {"event_type": "world_committed", "turn": 9, "data": {"tool": "submit_diagnosis"}},
    ]))
    assert category == "diagnosis_committed_no_treatment"
    assert evidence["first_diagnosis_commit_turn"] == 9
    assert evidence["post_diagnosis_tool_attempt_count"] == 0


def test_stall_audit_keeps_provider_failure_separate():
    category, _ = classify_task(_artifact([], failure="deepseek_provider_error"))
    assert category == "provider_error"


def test_old_memory_trace_confirms_diagnosis_without_commit_tool_field():
    artifact = _artifact([
        {"event_type": "tool_attempted", "turn": 4,
         "data": {"tool": "submit_diagnosis"}},
        {"event_type": "confirmation_received", "turn": 5,
         "data": {"valid": True, "action_digest": "same"}},
        {"event_type": "tool_attempted", "turn": 5,
         "data": {"tool": "submit_diagnosis"}},
        {"event_type": "world_committed", "turn": 5,
         "data": {"controlled": True, "action_digest": "same"}},
    ])
    artifact["condition"] = "M1"
    artifact["terminal_snapshot"]["submitted_diagnosis_id"] = "public_diagnosis"

    evidence = classify_memory_diagnosis(artifact)

    assert evidence["diagnosis_tool_attempt_count"] == 2
    assert evidence["confirmed_diagnosis_commit_count"] == 1
    assert evidence["diagnosis_commit_evidence_status"] == "CONFIRMED"


def test_memory_terminal_diagnosis_without_matching_commit_is_unknown():
    artifact = _artifact([])
    artifact["condition"] = "M2"
    artifact["terminal_snapshot"]["submitted_diagnosis_id"] = "public_diagnosis"

    evidence = classify_memory_diagnosis(artifact)

    assert evidence["confirmed_diagnosis_commit_count"] == 0
    assert evidence["diagnosis_commit_evidence_status"] == "UNKNOWN"


def test_uncommitted_diagnosis_attempt_is_not_counted_as_commit():
    artifact = _artifact([
        {"event_type": "tool_attempted", "turn": 8,
         "data": {"tool": "submit_diagnosis"}},
    ])
    artifact["condition"] = "M0"
    artifact["terminal_snapshot"]["submitted_diagnosis_id"] = None

    evidence = classify_memory_diagnosis(artifact)

    assert evidence["diagnosis_tool_attempt_count"] == 1
    assert evidence["confirmed_diagnosis_commit_count"] == 0
    assert evidence["diagnosis_commit_evidence_status"] == "NO_COMMIT_EVIDENCE"
