import json

from xuanyi_npc.agents import ScriptedFakeLLM
from xuanyi_npc.agents.game_npc import GameNPCAgent
from xuanyi_npc.domain import ToolName
from xuanyi_npc.domain.planning_contract import GameNPCTurnProposal
from tests.test_p2_plan_decision_alignment import _diagnosis_input, _proposal
from tests.test_p3a_repair_attempt_telemetry import _empty_diagnosis_step


def test_model_visible_schema_states_complete_diagnosis_plan_contract() -> None:
    schema = GameNPCTurnProposal.model_json_schema()
    serialized = json.dumps(schema, ensure_ascii=False)

    assert "propose_diagnosis" in serialized
    assert "suggested_tool=submit_diagnosis" in serialized
    assert "public_target_id" in serialized
    assert "diagnosis_id from the public diagnosis candidates" in serialized
    assert "must equal Decision.tool_call.arguments.diagnosis_id" in serialized


def test_initial_and_repair_share_model_visible_contract_and_one_repair(
    case_definition, qualified_player_state
) -> None:
    value = _diagnosis_input(case_definition, qualified_player_state)
    valid, diagnosis_id, _ = _proposal(value)
    invalid = _empty_diagnosis_step(valid)
    adapter = ScriptedFakeLLM([invalid.model_dump_json(), valid.model_dump_json()])
    agent = GameNPCAgent(adapter)

    result = agent.propose_turn(value)
    execution = agent.last_planning_execution()

    assert len(adapter.requests) == 2
    assert execution.attempts == 2
    assert execution.repair_attempted is True
    assert execution.repair_succeeded is True
    assert adapter.requests[0].response_schema == adapter.requests[1].response_schema
    schema_text = json.dumps(adapter.requests[1].response_schema, ensure_ascii=False)
    assert "suggested_tool=submit_diagnosis" in schema_text
    assert "must equal Decision.tool_call.arguments.diagnosis_id" in schema_text
    step = result.plan_update.draft.steps[0]
    assert step.suggested_tool is ToolName.SUBMIT_DIAGNOSIS
    assert step.public_target_id == diagnosis_id
    assert result.decision.action.tool_call.arguments["diagnosis_id"] == diagnosis_id
