from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from xuanyi_npc.domain import CaseDefinition, PlayerState, TreatmentOutcome
from xuanyi_npc.domain.memory import MemoryType
from xuanyi_npc.memory import (
    DeterministicMemoryProjector,
    MemorySourceEventType,
    MemoryWriteReason,
    UnsupportedMemorySourceError,
    VerifiedMemorySource,
    canonical_json,
    sha256_hex,
    stable_memory_id,
    stable_source_event_id,
)
from xuanyi_npc.memory.canonical import utc_text

from .memory_helpers import reference_case_results


HIDDEN_SENTINEL = "hidden_truth_must_never_enter_memory"


def project_result(
    projector: DeterministicMemoryProjector,
    case: CaseDefinition,
    player: PlayerState,
    before_revision: int,
    result: object,
):
    event = result.events[0]
    return projector.project_committed_event(
        event=event,
        case=case,
        player=player,
        session=result.session,
        source_revision=before_revision + 1,
    )


def test_memory_contracts_reject_unknown_fields(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(case_definition, qualified_player_state)
    source, _ = project_result(
        DeterministicMemoryProjector(),
        case_definition,
        qualified_player_state,
        results[0][0].revision,
        results[0][1],
    )
    payload = source.model_dump(mode="python")
    payload["unknown"] = "not allowed"

    with pytest.raises(ValidationError, match="extra_forbidden"):
        VerifiedMemorySource.model_validate(payload)


def test_stable_ids_canonical_json_utc_and_hash_are_fixed() -> None:
    source_id = stable_source_event_id(
        "investigation_completed",
        "session_memory_reference",
        1,
    )
    memory_id = stable_memory_id(
        "player_apprentice",
        source_id,
        "memory_projection_v1",
        0,
    )
    offset_time = datetime(2026, 8, 7, 17, 1, tzinfo=timezone(timedelta(hours=8)))
    value = {
        "items": frozenset({"b", "a"}),
        "time": offset_time,
        "nested": {"z": 2, "a": 1},
    }

    assert source_id == "ce_4db6b578311658c9b68ce932cde9f049"
    assert memory_id == "mem_5eea9023046e5cf9acc670d60c00f7df"
    assert utc_text(offset_time) == "2026-08-07T09:01:00.000000Z"
    assert canonical_json(value) == (
        '{"items":["a","b"],"nested":{"a":1,"z":2},'
        '"time":"2026-08-07T09:01:00.000000Z"}'
    )
    assert sha256_hex(value) == "b8cfc69c86d7304cc081b24227b8458312446e61e9d7ff5e5ea196de931baa54"


def test_investigation_projection_matches_public_snapshot(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(case_definition, qualified_player_state)
    before, result = results[0]

    source, memory = project_result(
        DeterministicMemoryProjector(),
        case_definition,
        qualified_player_state,
        before.revision,
        result,
    )

    assert source.source_event_type is MemorySourceEventType.INVESTIGATION_COMPLETED
    assert source.source_revision == 1
    assert source.public_payload.model_dump(mode="json") == {
        "payload_type": "investigation_completed",
        "case_id": "old_paper_umbrella",
        "case_title": "旧纸伞与失约书生",
        "investigation_id": "observe_scholar",
        "action_type": "observe_patient",
        "public_action_description": "观察书生的神色、动作、影子与周围灯火表现。",
        "newly_discovered_clues": [
            {
                "clue_id": "exam_fatigue",
                "description": "书生近来昼夜读书，神色疲惫。疲惫能解释困倦，却不能解释契痕。",
            },
            {
                "clue_id": "fading_shadow",
                "description": "灯火稳定时，书生的影缘仍比身体动作慢半拍。",
            },
        ],
    }
    assert memory.memory_type is MemoryType.EPISODIC
    assert memory.write_reason is MemoryWriteReason.VERIFIED_CASE_INVESTIGATION
    assert memory.relationship_impacts == ()
    assert "新发现" in memory.content
    assert "根因" not in memory.content


def test_wrong_diagnosis_is_recorded_only_as_a_submitted_hypothesis(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(
        case_definition,
        qualified_player_state,
        diagnosis_id="evil_spirit_attack",
    )
    before, result = results[6]

    source, memory = project_result(
        DeterministicMemoryProjector(),
        case_definition,
        qualified_player_state,
        before.revision,
        result,
    )

    assert source.source_event_type is MemorySourceEventType.DIAGNOSIS_SUBMITTED
    assert memory.memory_type is MemoryType.EPISODIC
    assert memory.write_reason is MemoryWriteReason.VERIFIED_DIAGNOSIS_SUBMISSION
    assert "玩家提交过公开假设" in memory.content
    assert "有外来灵体主动侵袭书生" in memory.content
    assert "诊断正确" not in memory.content
    assert "世界事实" not in memory.content


def test_treatment_projection_contains_only_public_observed_result(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(case_definition, qualified_player_state)
    before, result = results[7]

    source, memory = project_result(
        DeterministicMemoryProjector(),
        case_definition,
        qualified_player_state,
        before.revision,
        result,
    )

    assert source.source_event_type is MemorySourceEventType.TREATMENT_EXECUTED
    assert memory.memory_type is MemoryType.LEARNING
    assert memory.write_reason is MemoryWriteReason.VERIFIED_TREATMENT_OBSERVATION
    assert "在见证下将木牌送回旧渡口" in memory.content
    assert "处置后病例已经解决" in memory.content
    serialized = canonical_json((source, memory))
    assert "diagnosis_correct" not in serialized
    assert '"score"' not in serialized
    assert "valid_diagnosis_ids" not in serialized


def test_raw_treatment_truth_fields_do_not_affect_public_source_or_hash(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(case_definition, qualified_player_state)
    before, result = results[7]
    event = result.events[0]
    altered = event.model_copy(
        update={
            "diagnosis_correct": not event.diagnosis_correct,
            "score": 0,
            "outcome": TreatmentOutcome.WORSENED,
        }
    )
    projector = DeterministicMemoryProjector()

    original = projector.project_committed_event(
        event=event,
        case=case_definition,
        player=qualified_player_state,
        session=result.session,
        source_revision=before.revision + 1,
    )
    changed_hidden = projector.project_committed_event(
        event=altered,
        case=case_definition,
        player=qualified_player_state,
        session=result.session,
        source_revision=before.revision + 1,
    )

    assert changed_hidden == original


def test_hidden_case_fields_and_undiscovered_clues_never_enter_projection(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    data = case_definition.model_dump(mode="python")
    data["root_cause"] = "hidden_truth_sentinel"
    data["causal_chain"] = (HIDDEN_SENTINEL,)
    data["patient"]["hidden_information"] = (HIDDEN_SENTINEL,)
    data["clues"]["broken_promise"]["description"] = HIDDEN_SENTINEL
    hidden_case = CaseDefinition.model_validate(data)
    _, results = reference_case_results(hidden_case, qualified_player_state)
    before, result = results[0]

    source, memory = project_result(
        DeterministicMemoryProjector(),
        hidden_case,
        qualified_player_state,
        before.revision,
        result,
    )
    serialized = canonical_json((source, memory))

    _, baseline_results = reference_case_results(
        case_definition,
        qualified_player_state,
    )
    baseline_source, baseline_memory = project_result(
        DeterministicMemoryProjector(),
        case_definition,
        qualified_player_state,
        baseline_results[0][0].revision,
        baseline_results[0][1],
    )

    assert HIDDEN_SENTINEL not in serialized
    assert "hidden_truth_sentinel" not in serialized
    assert source.public_payload_hash == baseline_source.public_payload_hash
    assert memory.content_hash == baseline_memory.content_hash


def test_unknown_non_event_sources_are_rejected_before_projection(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(case_definition, qualified_player_state)

    with pytest.raises(UnsupportedMemorySourceError) as exc_info:
        DeterministicMemoryProjector().project_committed_event(
            event={"type": "respond", "content": HIDDEN_SENTINEL},
            case=case_definition,
            player=qualified_player_state,
            session=results[0][1].session,
            source_revision=1,
        )

    assert HIDDEN_SENTINEL not in str(exc_info.value)


def test_semantically_same_events_in_different_episodes_keep_distinct_ids(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, first_results = reference_case_results(
        case_definition,
        qualified_player_state,
        session_id="session_memory_first",
    )
    _, second_results = reference_case_results(
        case_definition,
        qualified_player_state,
        session_id="session_memory_second",
    )
    projector = DeterministicMemoryProjector()
    first_source, first_memory = project_result(
        projector,
        case_definition,
        qualified_player_state,
        0,
        first_results[0][1],
    )
    second_source, second_memory = project_result(
        projector,
        case_definition,
        qualified_player_state,
        0,
        second_results[0][1],
    )

    assert first_source.public_payload == second_source.public_payload
    assert first_source.source_event_id != second_source.source_event_id
    assert first_memory.memory_id != second_memory.memory_id
