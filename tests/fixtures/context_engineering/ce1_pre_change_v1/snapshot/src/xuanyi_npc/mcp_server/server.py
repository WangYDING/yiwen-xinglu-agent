"""Official MCP v2 server factory for pure in-process M3-P0 validation."""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.tools import Tool
from pydantic import BaseModel, ConfigDict, ValidationError

from xuanyi_npc.application.mcp_facade import (
    MCPApplicationResult,
    MCPApplicationService,
)
from xuanyi_npc.domain import ToolName

from .contracts import (
    DiagnosisToolInput,
    InvestigationToolInput,
    MCPToolInput,
    ReadToolInput,
    TreatmentToolInput,
)


FROZEN_MCP_TOOL_NAMES = (
    "get_player_view",
    "get_case_observation",
    "observe_patient",
    "question_patient",
    "inspect_object",
    "observe_qi",
    "investigate_location",
    "submit_diagnosis",
    "execute_treatment",
)


_TOOL_INPUTS: dict[ToolName, type[MCPToolInput]] = {
    ToolName.GET_PLAYER_VIEW: ReadToolInput,
    ToolName.GET_CASE_OBSERVATION: ReadToolInput,
    ToolName.OBSERVE_PATIENT: InvestigationToolInput,
    ToolName.QUESTION_PATIENT: InvestigationToolInput,
    ToolName.INSPECT_OBJECT: InvestigationToolInput,
    ToolName.OBSERVE_QI: InvestigationToolInput,
    ToolName.INVESTIGATE_LOCATION: InvestigationToolInput,
    ToolName.SUBMIT_DIAGNOSIS: DiagnosisToolInput,
    ToolName.EXECUTE_TREATMENT: TreatmentToolInput,
}


_TOOL_DESCRIPTIONS = {
    ToolName.GET_PLAYER_VIEW: "刷新权限过滤后的玩家只读视图。",
    ToolName.GET_CASE_OBSERVATION: "刷新权限过滤后的病例公开观察。",
    ToolName.OBSERVE_PATIENT: "执行一个公开的望形调查选项。",
    ToolName.QUESTION_PATIENT: "执行一个公开的问询调查选项。",
    ToolName.INSPECT_OBJECT: "执行一个公开的验物调查选项。",
    ToolName.OBSERVE_QI: "执行一个公开的察炁调查选项。",
    ToolName.INVESTIGATE_LOCATION: "执行一个公开的地点调查选项。",
    ToolName.SUBMIT_DIAGNOSIS: "从公开诊断词表提交诊断和已发现证据。",
    ToolName.EXECUTE_TREATMENT: "从当前公开处置选项执行处置。",
}


def create_mcp_server(service: MCPApplicationService) -> MCPServer:
    """Build an injectable server without starting a transport or reading env files."""

    tools = [
        _make_structured_tool(service, ToolName(tool_name))
        for tool_name in FROZEN_MCP_TOOL_NAMES
    ]
    return MCPServer(
        name="xuanyi-m3-p0",
        instructions="仅提供权限过滤后的病例工具；所有状态修改由确定性领域层执行。",
        tools=tools,
    )


def _make_structured_tool(
    service: MCPApplicationService,
    tool_name: ToolName,
) -> Tool:
    input_model = _TOOL_INPUTS[tool_name]

    async def dispatch(
        raw_payload: dict[str, Any] | None = None,
    ) -> MCPApplicationResult:
        payload = raw_payload or {}
        try:
            validated = input_model.model_validate(payload)
        except ValidationError:
            return service.invalid_arguments(raw_arguments=payload)
        public = validated.model_dump(mode="json")
        player_id = public.pop("player_id")
        session_id = public.pop("session_id")
        try:
            return service.execute_tool(
                tool_name=tool_name,
                player_id=player_id,
                session_id=session_id,
                tool_arguments=public,
            )
        except Exception:
            return service.internal_failure()

    tool = Tool.from_function(
        dispatch,
        name=tool_name.value,
        description=_TOOL_DESCRIPTIONS[tool_name],
        structured_output=True,
    )
    tool.parameters = input_model.model_json_schema()
    tool.fn_metadata.arg_model = _passthrough_argument_model(tool.fn_metadata.arg_model)
    return tool


def _passthrough_argument_model(base_model: type[BaseModel]) -> type[BaseModel]:
    """Preserve raw top-level arguments so our strict contract owns safe errors."""

    def model_dump_one_level(self: BaseModel) -> dict[str, object]:
        payload = dict(self.model_extra or {})
        explicit_payload = getattr(self, "raw_payload", None)
        if explicit_payload is not None:
            payload["raw_payload"] = explicit_payload
        return {"raw_payload": payload}

    namespace: dict[str, object] = {
        "model_config": ConfigDict(arbitrary_types_allowed=True, extra="allow"),
        "model_dump_one_level": model_dump_one_level,
    }
    return type("RawMCPArguments", (base_model,), namespace)
