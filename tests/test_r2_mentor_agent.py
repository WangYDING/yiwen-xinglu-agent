import json

from xuanyi_npc.agents import MentorAgent, ScriptedFakeLLM
from xuanyi_npc.application import TeachingRequest
from tests.r1_helpers import create_player
from tests.r2_helpers import build_teaching, start_teaching


def test_illegal_case_tool_repairs_once_then_falls_back_without_state_write(tmp_path):
    case_service, bootstrap, store = build_teaching(tmp_path)
    player_id = create_player(case_service)
    started, state = start_teaching(case_service, bootstrap, player_id)
    invalid_tool = json.dumps(
        {"action_type": "observe_patient", "message": "我替你查看", "hint_id": None,
         "referenced_public_evidence_ids": [], "referenced_ability_ids": [],
         "referenced_relationship_dimensions": []},
        ensure_ascii=False,
    )
    write_attempt = json.dumps(
        {"action_type": "give_hint", "message": "改能力", "hint_id": "hint_1",
         "ability_delta": 99, "referenced_public_evidence_ids": [],
         "referenced_ability_ids": [], "referenced_relationship_dimensions": []},
        ensure_ascii=False,
    )
    adapter = ScriptedFakeLLM((invalid_tool, write_attempt))
    teaching = bootstrap.__class__(
        case_service=case_service,
        mentor_agent=MentorAgent(adapter),
        id_factory=bootstrap.id_factory,
    )
    path = tmp_path / "teaching_sessions" / f"{state.teaching_session_id}.json"
    case_path = tmp_path / "case_sessions" / f"{started.session_id}.json"
    growth_path = tmp_path / "apprenticeships" / f"{player_id}.json"
    before = (path.read_bytes(), case_path.read_bytes(), growth_path.read_bytes())
    result = teaching.request_hint(
        TeachingRequest(player_id=player_id, teaching_session_id=state.teaching_session_id)
    )
    assert not result.ok and result.error_code == "mentor_action_rejected"
    assert len(adapter.requests) == 2
    assert before == (path.read_bytes(), case_path.read_bytes(), growth_path.read_bytes())


def test_unknown_hint_and_undiscovered_evidence_are_rejected(tmp_path):
    case_service, bootstrap, _ = build_teaching(tmp_path)
    player_id = create_player(case_service)
    _, state = start_teaching(case_service, bootstrap, player_id)
    invalid = json.dumps(
        {"action_type": "give_hint", "message": "提示", "hint_id": "hint_unknown",
         "referenced_public_evidence_ids": ["hidden_wooden_token"],
         "referenced_ability_ids": [], "referenced_relationship_dimensions": []},
        ensure_ascii=False,
    )
    agent = MentorAgent(ScriptedFakeLLM((invalid, invalid)))
    teaching = bootstrap.__class__(case_service=case_service, mentor_agent=agent)
    result = teaching.request_hint(
        TeachingRequest(player_id=player_id, teaching_session_id=state.teaching_session_id)
    )
    assert not result.ok and result.state.revision == state.revision
