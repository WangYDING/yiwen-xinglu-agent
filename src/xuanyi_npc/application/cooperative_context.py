"""CE-2A history selection and current-pending public projections."""

from __future__ import annotations

import json

from xuanyi_npc.agents.llm import ChatMessage, ChatRole
from xuanyi_npc.domain.cooperation import (
    CooperativeTurnResult,
    PendingActionConfirmation,
    PlayerContribution,
)
from xuanyi_npc.domain.cooperative_context import (
    CooperativeContextSnapshot,
    HistoryOmissionView,
    PendingConfirmationContextView,
)
from xuanyi_npc.storage.sqlite_cooperation import (
    CooperativeTurnRecord,
    SQLiteCooperativeHistoryRepository,
)


HISTORY_MAX_COMPLETE_TURNS = 3
HISTORY_CONTENT_CHARACTER_BUDGET = 12_000
PENDING_CONTEXT_CHARACTER_LIMIT = 12_000


class RequiredCooperativeContextTooLarge(ValueError):
    pass


def _history_pair(record: CooperativeTurnRecord) -> tuple[ChatMessage, ChatMessage]:
    contribution = PlayerContribution.model_validate_json(record.contribution_json or "{}")
    result = CooperativeTurnResult.model_validate_json(record.result_json or "{}")
    player_content = json.dumps(
        {
            "source": "completed_historical_player_contribution",
            "authority": "player_belief_non_authoritative",
            "operation_id": record.operation_id,
            "contribution_type": contribution.contribution_type.value,
            "public_text": contribution.public_text,
            "responds_to_decision_id": contribution.responds_to_decision_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assistant_content = json.dumps(
        {
            "source": "completed_historical_npc_public_reply",
            "authority": "historical_non_authoritative_not_current_state_or_authorization",
            "operation_id": record.operation_id,
            "status": result.status.value,
            "npc_dialogue": result.decision.proposal.action.dialogue,
            "public_rationale": result.public_rationale,
            "environment_message": result.environment_message,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return (
        ChatMessage(role=ChatRole.USER, content=player_content),
        ChatMessage(role=ChatRole.ASSISTANT, content=assistant_content),
    )


def select_completed_history(
    repository: SQLiteCooperativeHistoryRepository,
    current: CooperativeTurnRecord,
) -> tuple[tuple[ChatMessage, ...], tuple[str, ...], HistoryOmissionView | None]:
    total = repository.completed_count_before(current)
    candidates = repository.recent_completed_before(
        current, HISTORY_MAX_COMPLETE_TURNS + 1
    )
    selected: list[tuple[CooperativeTurnRecord, tuple[ChatMessage, ChatMessage]]] = []
    used = 0
    reason = "turn_limit"
    for record in candidates:
        if len(selected) >= HISTORY_MAX_COMPLETE_TURNS:
            reason = "turn_limit"
            break
        pair = _history_pair(record)
        pair_chars = sum(len(message.content) for message in pair)
        if used + pair_chars > HISTORY_CONTENT_CHARACTER_BUDGET:
            reason = "character_budget"
            break
        selected.append((record, pair))
        used += pair_chars
    selected.reverse()
    messages = tuple(message for _, pair in selected for message in pair)
    operation_ids = tuple(record.operation_id for record, _ in selected)
    omitted = total - len(selected)
    omission = None
    if omitted:
        omission = HistoryOmissionView(
            omitted_completed_turn_count=omitted,
            reason=reason,
            public_notice=(
                f"同一玩家、案件、会话中，当前操作之前有 {omitted} 个已完成协作回合未注入；"
                "若当前问题依赖被省略内容，请玩家重述必要信息。"
            ),
        )
    return messages, operation_ids, omission


def project_pending_snapshot(
    pending_items: tuple[PendingActionConfirmation, ...],
    *,
    player_id: str,
    case_id: str,
    session_id: str,
    case_revision: int,
    responds_to_confirmation_id: str | None,
    responds_to_decision_id: str | None,
) -> tuple[PendingConfirmationContextView, ...]:
    views = tuple(
        PendingConfirmationContextView(
            confirmation_id=item.confirmation_id,
            decision_id=item.decision_id,
            action=item.action,
            authority_mode=item.authority_mode,
            public_rationale=item.public_rationale,
            case_revision=item.case_revision,
            responds_to_current_contribution=(
                responds_to_confirmation_id == item.confirmation_id
                and responds_to_decision_id == item.decision_id
            ),
        )
        for item in sorted(pending_items, key=lambda value: value.confirmation_id)
        if (item.player_id, item.case_id, item.session_id)
        == (player_id, case_id, session_id)
        and item.case_revision == case_revision
    )
    serialized = json.dumps(
        [item.model_dump(mode="json") for item in views],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(serialized) > PENDING_CONTEXT_CHARACTER_LIMIT:
        raise RequiredCooperativeContextTooLarge(
            "current pending confirmation context exceeds the required-context character limit"
        )
    return views


def build_context_snapshot(
    repository: SQLiteCooperativeHistoryRepository,
    current: CooperativeTurnRecord,
    pending_items: tuple[PendingActionConfirmation, ...],
    *,
    contribution: PlayerContribution,
    case_revision: int,
    responds_to_confirmation_id: str | None,
) -> tuple[CooperativeContextSnapshot, tuple[ChatMessage, ...]]:
    messages, operation_ids, omission = select_completed_history(repository, current)
    pending = project_pending_snapshot(
        pending_items,
        player_id=contribution.player_id,
        case_id=contribution.case_id,
        session_id=contribution.session_id,
        case_revision=case_revision,
        responds_to_confirmation_id=responds_to_confirmation_id,
        responds_to_decision_id=contribution.responds_to_decision_id,
    )
    return (
        CooperativeContextSnapshot(
            selected_history_operation_ids=operation_ids,
            history_omission=omission,
            pending_confirmations=pending,
        ),
        messages,
    )
