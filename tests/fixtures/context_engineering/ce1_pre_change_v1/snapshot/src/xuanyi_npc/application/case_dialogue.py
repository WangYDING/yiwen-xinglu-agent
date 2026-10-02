"""Public case-character dialogue and investigation guides."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText


class GuideStage(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    stage_id: Identifier
    title: NonEmptyText
    public_purpose: NonEmptyText
    suggested_questions: tuple[NonEmptyText, ...]
    suggested_investigation_types: tuple[Identifier, ...]
    completion_requirement_ids: tuple[Identifier, ...]
    guide_prompt: NonEmptyText
    off_track_prompt: NonEmptyText


class CaseGuide(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    investigation_goal: NonEmptyText
    stages: tuple[GuideStage, ...]
    diagnosis_review_questions: tuple[NonEmptyText, ...]
    treatment_review_questions: tuple[NonEmptyText, ...]


class CaseParticipant(DomainModel):
    participant_id: Identifier
    display_name: NonEmptyText
    kind: Literal["patient", "witness", "group"] = "witness"
    public_intro: NonEmptyText


class ChatMessage(DomainModel):
    speaker_id: Identifier
    recipient_id: Identifier
    message_type: Literal["player", "case_character", "system", "clue", "rejection"]
    response_type: Literal[
        "understood_but_unknown",
        "known_partial_answer",
        "known_complete_answer",
        "refuses_to_answer",
        "clarification_needed",
    ] | None = None
    public_text: NonEmptyText
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CaseDialogueState(DomainModel):
    case_session_id: Identifier
    player_id: Identifier
    case_id: Identifier
    current_target: str = ""
    off_track_count: int = Field(default=0, ge=0)
    revision: int = Field(default=0, ge=0)
    recent_messages: tuple[ChatMessage, ...] = ()


class CaseDialogueStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root) / "case_dialogues"

    def load(self, session_id: str, player_id: str, case_id: str) -> CaseDialogueState:
        path = self.root / f"{session_id}.json"
        if not path.exists():
            return CaseDialogueState(
                case_session_id=session_id,
                player_id=player_id,
                case_id=case_id,
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["recent_messages"] = [
            message
            for message in raw.get("recent_messages", ())
            if message.get("message_type") != "mentor_private"
            and message.get("speaker_id") != "mentor"
        ]
        state = CaseDialogueState.model_validate(
            {
                key: raw[key]
                for key in (
                    "case_session_id",
                    "player_id",
                    "case_id",
                    "current_target",
                    "off_track_count",
                    "revision",
                    "recent_messages",
                )
                if key in raw
            }
        )
        if state.player_id != player_id or state.case_id != case_id:
            raise ValueError("dialogue ownership mismatch")
        return state

    def save(self, state: CaseDialogueState) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=self.root, prefix=".dialogue-", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(state.model_dump_json(indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.root / f"{state.case_session_id}.json")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def load_guides() -> dict[str, CaseGuide]:
    path = Path(__file__).parents[1] / "resources" / "clinic" / "case_guides_v1.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {case_id: CaseGuide.model_validate(guide) for case_id, guide in raw.items()}


PARTICIPANTS = {
    "mist_ferry_borrowed_lantern": (("ferryman_zhou", "周渡", "patient", "我是周渡，在这条雾渡上行船多年。"), ("borrower_he", "何借灯", "witness", "我是何借灯，这趟船上借来青灯的人。"), ("ferry_passengers", "同舟乘客", "group", "我们是这趟渡船上的同舟乘客。")),
    "old_paper_umbrella": (("scholar_lu", "陆砚生", "patient", "我是陆砚生，寄居镇中备考的书生。"),),
    "gray_hearth_inn": (("cook_shen", "沈禾", "patient", "我是沈禾，灰灶客栈的掌勺人。"), ("innkeeper_luo", "罗店主", "witness", "我是这家灰灶客栈的店主。")),
    "moon_well_echo": (("courier_qiao", "乔砚", "patient", "我是乔砚，替镇民递送木简的行脚人。"), ("lantern_seller_miao", "苗灯商", "witness", "我是苗灯商，在月井附近经营灯摊。")),
    "lantern_alley_conflicting_testimony": (("lantern_keeper_lin", "林照", "patient", "我是林照，负责照看双灯巷夜灯的灯守。"), ("witness_yu", "余青", "witness", "我是余青，当夜经过双灯巷的巡夜人。"), ("witness_shao", "邵安", "witness", "我是邵安，在双灯巷口经营摊铺。")),
    "returning_contract_nameless_shrine": (("shrine_visitor_wei", "魏循", "patient", "我是魏循，带着祖契前来古祠归还的旅人。"), ("shrine_keeper_qin", "秦守祠", "witness", "我是秦守祠，负责看守这座古祠。")),
}


def case_participants(case_id: str) -> tuple[CaseParticipant, ...]:
    return tuple(
        CaseParticipant(participant_id=item, display_name=name, kind=kind, public_intro=intro)
        for item, name, kind, intro in PARTICIPANTS[case_id]
    )


def asks_participant_identity(text: str) -> bool:
    value = "".join(text.strip().split()).rstrip("，。！？?")
    return value in {"你是谁", "你叫什么", "你叫什么名字", "请问你是谁"} or bool(
        value.startswith(("你是", "请问你是")) and value.endswith(("吗", "么"))
    )
