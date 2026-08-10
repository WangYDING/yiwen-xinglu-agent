"""Explicit Fake reference scripts for demos and regression tests only."""

from __future__ import annotations

from pydantic import ConfigDict

from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseActionType,
    CaseDefinition,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.domain.base import DomainModel, Identifier

from .doctor import DoctorAgent
from .fake_llm import ScriptedFakeLLM


class FakeReferenceScript(DomainModel):
    """Frozen successful trace identity, never exposed as public case content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    investigation_ids: tuple[Identifier, ...]
    diagnosis_id: Identifier
    treatment_id: Identifier


REFERENCE_FAKE_SCRIPTS: dict[str, FakeReferenceScript] = {
    "old_paper_umbrella": FakeReferenceScript(
        investigation_ids=(
            "observe_scholar",
            "ask_about_memory",
            "inspect_umbrella",
            "observe_contract_trace",
            "search_book_chest",
            "ask_about_promise",
        ),
        diagnosis_id="rain_vow_breach",
        treatment_id="return_token_and_fulfill_vow",
    ),
    "gray_hearth_inn": FakeReferenceScript(
        investigation_ids=(
            "observe_cook",
            "question_innkeeper",
            "inspect_fuel_and_hearth",
            "inspect_hearth_contract",
            "observe_flue_qi",
            "investigate_smoke_passage",
        ),
        diagnosis_id="displaced_hearth_contract",
        treatment_id="restore_token_and_clear_flue",
    ),
    "moon_well_echo": FakeReferenceScript(
        investigation_ids=(
            "observe_courier",
            "question_route",
            "inspect_wooden_slip",
            "inspect_binding_cord",
            "observe_well_echo_qi",
            "question_lantern_witness",
        ),
        diagnosis_id="misbound_message_handoff",
        treatment_id="verify_recipient_and_deliver",
    ),
}


TOOL_BY_ACTION = {
    CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
    CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
    CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
    CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
    CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
}


def build_reference_fake_agent(
    case: CaseDefinition,
    *,
    completed_event_count: int = 0,
) -> tuple[DoctorAgent, ScriptedFakeLLM]:
    """Build the remaining 8-action reference trace for one supported case."""

    try:
        script = REFERENCE_FAKE_SCRIPTS[case.case_id]
    except KeyError as exc:
        raise ValueError("no Fake demonstration script exists for this case") from exc
    actions: list[AgentAction] = []
    evidence: set[str] = set()
    investigations = {
        investigation.investigation_id: investigation
        for investigation in case.investigations
    }
    for investigation_id in script.investigation_ids:
        investigation = investigations[investigation_id]
        evidence.update(investigation.reveals_clue_ids)
        actions.append(
            AgentAction(
                action_id="placeholder",
                action_type=AgentActionType.USE_TOOL,
                dialogue="按公开选项继续调查。",
                tool_call=ToolCallRequest(
                    name=TOOL_BY_ACTION[investigation.action_type],
                    arguments={"investigation_id": investigation_id},
                ),
                confidence=1.0,
            )
        )
    actions.extend(
        (
            AgentAction(
                action_id="placeholder",
                action_type=AgentActionType.USE_TOOL,
                dialogue="根据已发现的公开证据提交候选诊断。",
                tool_call=ToolCallRequest(
                    name=ToolName.SUBMIT_DIAGNOSIS,
                    arguments={
                        "diagnosis_id": script.diagnosis_id,
                        "evidence_clue_ids": sorted(evidence),
                    },
                ),
                confidence=1.0,
            ),
            AgentAction(
                action_id="placeholder",
                action_type=AgentActionType.USE_TOOL,
                dialogue="执行当前公开可见的处置。",
                tool_call=ToolCallRequest(
                    name=ToolName.EXECUTE_TREATMENT,
                    arguments={"treatment_id": script.treatment_id},
                ),
                confidence=1.0,
            ),
        )
    )
    remaining = actions[completed_event_count:]
    serialized = tuple(
        action.model_copy(update={"action_id": f"agent_step_{index:03d}"})
        .model_dump_json()
        for index, action in enumerate(remaining, start=1)
    )
    adapter = ScriptedFakeLLM(serialized)
    return DoctorAgent(adapter), adapter
