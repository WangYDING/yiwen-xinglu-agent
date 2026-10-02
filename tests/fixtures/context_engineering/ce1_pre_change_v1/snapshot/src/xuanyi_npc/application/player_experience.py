"""Deterministic player-language proposals; this module never writes case state."""
from dataclasses import dataclass
import re
from typing import Literal

@dataclass(frozen=True)
class LanguageProposal:
    kind: str
    selection_id: str | None = None
    message: str = ""

CaseMessageIntent = Literal[
    "character_question", "investigation_action",
    "diagnosis_statement", "treatment_statement", "clarification_needed", "off_topic",
]

@dataclass(frozen=True)
class CaseMessageClassification:
    intent: CaseMessageIntent
    message_text: str
    recipient_id: str | None = None
    message: str = ""

_QUESTION_WORDS = ("询问", "请问", "问问", "问", "谁", "何时", "什么时候", "为什么", "为何", "怎么", "是否", "吗", "么")
_ACTION_WORDS = ("检查", "观察", "查看", "查阅", "触摸", "核对现场", "核对物件", "追踪炁息", "追查炁息", "探查", "检视")
_DIAGNOSIS_WORDS = ("辨证", "诊断", "我判断", "我认为根因", "异象源于")
_TREATMENT_WORDS = ("处置", "施治", "治疗方案", "我决定", "执行方案")
_OFF_TOPIC_WORDS = ("天气", "吃饭", "唱歌", "闲聊", "游戏攻略")

def classify_case_message(raw: str, current_target: str, participants) -> CaseMessageClassification:
    """Classify before applying the current-recipient fallback; this function never writes state."""
    text = raw.strip()
    by_name = {item.display_name: item.participant_id for item in participants}
    if text.startswith("@"):
        matched = next((name for name in by_name if text.startswith("@" + name)), None)
        if matched is None:
            return CaseMessageClassification("clarification_needed", text, message="本案没有这位可交谈人物，请从参与者列表选择。")
        rest = text[len(matched) + 1:].strip()
        if not rest:
            return CaseMessageClassification("clarification_needed", text, message="请选择接收者后再输入要说的话。")
        return CaseMessageClassification("character_question", rest, by_name[matched])
    if not text:
        return CaseMessageClassification("clarification_needed", text, message="请说明你想询问、调查、辨证或处置什么。")
    has_question = any(word in text for word in _QUESTION_WORDS)
    has_action = any(word in text for word in _ACTION_WORDS)
    named_people = tuple(name for name in by_name if name in text)
    if has_action and has_question:
        return CaseMessageClassification("clarification_needed", text, message="这句话同时包含人物问询和调查行动。请分开说明：要问谁，或要检查什么。")
    if has_action:
        return CaseMessageClassification("investigation_action", text)
    if any(word in text for word in _DIAGNOSIS_WORDS):
        return CaseMessageClassification("diagnosis_statement", text)
    if any(word in text for word in _TREATMENT_WORDS):
        return CaseMessageClassification("treatment_statement", text)
    if any(word in text for word in _OFF_TOPIC_WORDS):
        return CaseMessageClassification("off_topic", text)
    if has_question or named_people:
        if not current_target:
            return CaseMessageClassification("clarification_needed", text, message="当前接收者不明确，请先选择一位病例人物。")
        return CaseMessageClassification("character_question", text, current_target)
    return CaseMessageClassification("clarification_needed", text, message="我还不能判断你要询问人物还是执行调查。请补充问题对象或使用检查、观察、查阅等动作。")

def propose_investigation(text: str, investigations) -> LanguageProposal:
    value = re.sub(r"[，。！？、\s]", "", text.strip())
    if len(value) < 3:
        return LanguageProposal("clarify", message="请说清要询问谁、检查什么，或观察哪种变化。")
    if any(x in value for x in ("天气", "吃饭", "唱歌", "闲聊")):
        return LanguageProposal("off_topic", message="此事与当前异象关系不明。请围绕受影响者、契物、痕迹或炁息说明要查什么。")
    scored=[]
    for item in investigations:
        public=re.sub(r"[，。！？、\s]", "", item.public_description)
        score=sum(2 for ch in set(value) if ch in public)
        if any(x in value for x in ("问","询问")) and any(x in public for x in ("询问","核对")): score+=6
        if "炁" in value and "炁" in public: score+=8
        if any(x in value for x in ("检查","查看","查阅")) and any(x in public for x in ("检查","查阅")): score+=6
        scored.append((score,item.investigation_id))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 6 or (len(scored)>1 and scored[0][0]==scored[1][0]):
        return LanguageProposal("clarify", message="我还不能可靠判断调查目标。请补充对象与动作，例如‘询问某人来由’或‘检查某件物品的痕迹’。")
    return LanguageProposal("investigation",scored[0][1],"已按你的描述提出调查，并由病例规则复核能力与前置证据。")
