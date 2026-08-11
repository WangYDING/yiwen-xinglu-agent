"""Contextual public action contract and least-privilege repair feedback."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, StrictBool, ValidationError

from xuanyi_npc.domain import AgentAction, AgentActionType, CaseActionType, ToolName
from xuanyi_npc.domain.base import DomainModel, Identifier, NonEmptyText

from .views import CaseObservation, DiagnosisCandidateView, TreatmentOptionView


INVESTIGATION_TOOL_BY_ACTION: dict[CaseActionType, ToolName] = {
    CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
    CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
    CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
    CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
    CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
}


SAFE_ACTION_MESSAGES: dict[str, str] = {
    "invalid_tool_arguments": (
        "工具参数与当前公开契约不符；请使用准确工具名和唯一允许的参数字段。"
    ),
    "unknown_investigation": "该调查不在当前公开可用调查中，请刷新后重新选择。",
    "action_mismatch": "工具类型与该公开调查不匹配，请使用选项所列工具名。",
    "diagnosis_not_ready": "当前诊断尚未开放，请从刷新后的公开调查中选择行动。",
    "unknown_diagnosis": "该诊断不在当前公开候选词表中。",
    "evidence_not_discovered": "诊断只能引用当前已经发现的公开证据。",
    "unknown_treatment": "该处置不在当前公开可用处置中。",
    "unsupported_action": "该工具不属于当前公开可执行行动。",
    "action_contract_repair_failed": "修复后的行动仍不符合当前公开契约，已安全停止本步。",
}


class PublicInvestigationCall(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: ToolName
    investigation_id: Identifier
    public_description: NonEmptyText


class SafeActionRecoveryFeedback(DomainModel):
    """Only public, refreshed options allowed in a repair or rejection message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    error_code: Identifier
    public_message: NonEmptyText
    can_submit_diagnosis: StrictBool
    available_investigations: tuple[PublicInvestigationCall, ...] = Field(
        default_factory=tuple
    )
    diagnosis_candidates: tuple[DiagnosisCandidateView, ...] = Field(
        default_factory=tuple
    )
    treatment_candidates: tuple[TreatmentOptionView, ...] = Field(
        default_factory=tuple
    )
    oral_diagnosis_notice: Literal[
        "口头描述不等于提交诊断；必须调用 submit_diagnosis。"
    ] = "口头描述不等于提交诊断；必须调用 submit_diagnosis。"


class PublicActionContractError(ValueError):
    """A valid AgentAction JSON that is invalid for the current public view."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(SAFE_ACTION_MESSAGES.get(code, "行动不符合当前公开契约。"))


def build_safe_action_feedback(
    error_code: str,
    observation: CaseObservation,
) -> SafeActionRecoveryFeedback:
    investigations = tuple(
        PublicInvestigationCall(
            tool_name=INVESTIGATION_TOOL_BY_ACTION[item.action_type],
            investigation_id=item.investigation_id,
            public_description=item.public_description,
        )
        for item in observation.available_investigations
    )
    return SafeActionRecoveryFeedback(
        error_code=error_code,
        public_message=SAFE_ACTION_MESSAGES.get(
            error_code,
            "行动未被接受；请只使用刷新后的公开选项。",
        ),
        can_submit_diagnosis=observation.can_submit_diagnosis,
        available_investigations=investigations,
        diagnosis_candidates=observation.diagnosis_candidates,
        treatment_candidates=observation.available_treatments,
    )


class PublicActionContractValidator:
    """Validate a proposal against the exact current public action surface."""

    def validate(self, action: AgentAction, observation: CaseObservation) -> None:
        if action.action_type is AgentActionType.RESPOND:
            return
        if action.tool_call is None:
            raise PublicActionContractError("invalid_tool_arguments")
        call = action.tool_call
        if call.name in INVESTIGATION_TOOL_BY_ACTION.values():
            self._validate_investigation(call.name, call.arguments, observation)
            return
        if call.name is ToolName.SUBMIT_DIAGNOSIS:
            self._validate_diagnosis(call.arguments, observation)
            return
        if call.name is ToolName.EXECUTE_TREATMENT:
            self._validate_treatment(call.arguments, observation)
            return
        raise PublicActionContractError("unsupported_action")

    @staticmethod
    def _validate_investigation(
        tool_name: ToolName,
        arguments: dict[str, object],
        observation: CaseObservation,
    ) -> None:
        investigation_id = _single_identifier_argument(
            arguments,
            field_name="investigation_id",
        )
        option = next(
            (
                item
                for item in observation.available_investigations
                if item.investigation_id == investigation_id
            ),
            None,
        )
        if option is None:
            raise PublicActionContractError("unknown_investigation")
        if INVESTIGATION_TOOL_BY_ACTION[option.action_type] is not tool_name:
            raise PublicActionContractError("action_mismatch")

    @staticmethod
    def _validate_diagnosis(
        arguments: dict[str, object],
        observation: CaseObservation,
    ) -> None:
        if set(arguments) - {"diagnosis_id", "evidence_clue_ids"}:
            raise PublicActionContractError("invalid_tool_arguments")
        diagnosis_id = _required_identifier(arguments, "diagnosis_id")
        if diagnosis_id not in {
            item.diagnosis_id for item in observation.diagnosis_candidates
        }:
            raise PublicActionContractError("unknown_diagnosis")
        if not observation.can_submit_diagnosis:
            raise PublicActionContractError("diagnosis_not_ready")
        evidence = arguments.get("evidence_clue_ids", [])
        if not isinstance(evidence, (list, tuple, set, frozenset)) or any(
            not isinstance(item, str) for item in evidence
        ):
            raise PublicActionContractError("invalid_tool_arguments")
        discovered = {item.clue_id for item in observation.discovered_clues}
        if not set(evidence).issubset(discovered):
            raise PublicActionContractError("evidence_not_discovered")

    @staticmethod
    def _validate_treatment(
        arguments: dict[str, object],
        observation: CaseObservation,
    ) -> None:
        treatment_id = _single_identifier_argument(
            arguments,
            field_name="treatment_id",
        )
        if treatment_id not in {
            item.treatment_id for item in observation.available_treatments
        }:
            raise PublicActionContractError("unknown_treatment")


def _single_identifier_argument(
    arguments: dict[str, object],
    *,
    field_name: str,
) -> str:
    if set(arguments) != {field_name}:
        raise PublicActionContractError("invalid_tool_arguments")
    return _required_identifier(arguments, field_name)


def _required_identifier(arguments: dict[str, object], field_name: str) -> str:
    try:
        model = _IdentifierValue.model_validate({"value": arguments[field_name]})
    except (KeyError, ValidationError):
        raise PublicActionContractError("invalid_tool_arguments") from None
    return model.value


class _IdentifierValue(DomainModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: Identifier
