from xuanyi_npc.agents.llm import LLMResponse
from xuanyi_npc.evaluation.structured_output_diagnostics import (
    CapturingAdapter,
    StructuredFailureStage,
    diagnose_captured_responses,
)


class FakeAdapter:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    def complete(self, request):
        return LLMResponse(content=self.outputs.pop(0))


def test_diagnostics_distinguish_malformed_and_schema_mismatch_without_raw_content() -> None:
    capture = CapturingAdapter(FakeAdapter(("not json", '{"action_id":"npc_turn"}')))
    request = type("Request", (), {"response_schema": {"title": "GameNPCTurnProposal"}})()
    capture.complete(request)
    capture.complete(request)
    report = diagnose_captured_responses(model_name="fake", capture=capture)
    assert report.attempts[0].stage is StructuredFailureStage.MALFORMED_JSON
    assert report.attempts[1].stage is StructuredFailureStage.SCHEMA_MISMATCH
    assert report.attempts[1].top_level_json_keys == ("action_id",)
    assert {item.path for item in report.attempts[1].validation_issues} == {
        ("goal_update",), ("plan_update",), ("decision",), ("action_id",)
    }
    assert "not json" not in report.model_dump_json()

