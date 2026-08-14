from __future__ import annotations

import re
import threading

from xuanyi_npc.application.clinic import ClinicActionInput
from xuanyi_npc.clinic.server import ClinicHTTPServer
from xuanyi_npc.domain import AgentAction, AgentActionType, CaseActionType, ToolCallRequest, ToolName
from xuanyi_npc.domain.cooperation import (
    GameNPCDecision,
    GameNPCDecisionProposal,
    AgentRuntimeKind,
    NPCCapability,
    PlayerContributionEvaluation,
    SuggestionDisposition,
)
from tests.test_r5_clinic_http import request
from tests.test_r5_clinic_service import build_clinic


TOOL_BY_ACTION = {
    CaseActionType.OBSERVE_PATIENT: ToolName.OBSERVE_PATIENT,
    CaseActionType.QUESTION_PATIENT: ToolName.QUESTION_PATIENT,
    CaseActionType.INSPECT_OBJECT: ToolName.INSPECT_OBJECT,
    CaseActionType.OBSERVE_QI: ToolName.OBSERVE_QI,
    CaseActionType.INVESTIGATE_LOCATION: ToolName.INVESTIGATE_LOCATION,
}


class CooperativeWebAgent:
    config = object()
    runtime_kind = AgentRuntimeKind.TEST_DOUBLE

    def __init__(self, *, force_treatment: str | None = None, force_diagnosis: str | None = None) -> None:
        self.force_treatment = force_treatment
        self.force_diagnosis = force_diagnosis
        self.inputs = []

    def decide(self, value):
        self.inputs.append(value)
        if self.force_diagnosis is not None:
            tool = ToolName.SUBMIT_DIAGNOSIS
            arguments = {"diagnosis_id": self.force_diagnosis, "evidence_clue_ids": [item.clue_id for item in value.case_observation.discovered_clues]}
            dialogue = "我提出这项辨证与你协商，在你回应前不会提交。"
            capability = NPCCapability.PROPOSE_DIAGNOSIS
        elif self.force_treatment is not None:
            tool = ToolName.EXECUTE_TREATMENT
            arguments = {"treatment_id": self.force_treatment}
            dialogue = "我建议采用这项处置，但在你确认前不会执行。"
            capability = NPCCapability.PROPOSE_TREATMENT
        else:
            option = value.case_observation.available_investigations[-1]
            tool = TOOL_BY_ACTION[option.action_type]
            arguments = {"investigation_id": option.investigation_id}
            dialogue = "我不接受直接处置；先选择另一项公开调查补足证据。"
            capability = NPCCapability.USE_TOOL
        proposal = GameNPCDecisionProposal(
            contribution_evaluation=PlayerContributionEvaluation(
                contribution_id=value.player_contribution.contribution_id,
                disposition=SuggestionDisposition.REJECT,
                reason_code="insufficient_public_evidence",
                explanation="玩家建议不是命令，当前公开证据不足。",
            ),
            capability=capability,
            action=AgentAction(
                action_id=f"npc_{value.turn_id}",
                action_type=AgentActionType.USE_TOOL,
                dialogue=dialogue,
                tool_call=ToolCallRequest(name=tool, arguments=arguments),
                confidence=0.8,
            ),
            explanation="依据公开病例状态独立选择行动。",
        )
        return GameNPCDecision(
            decision_id=f"decision_{value.turn_id}",
            turn_id=value.turn_id,
            proposal=proposal,
            llm_attempts=1,
            used_fallback=False,
        )

    def repair_action_contract(self, value, prior, feedback):
        del value, feedback
        return self.action_contract_fallback(prior)

    def action_contract_fallback(self, prior):
        proposal = prior.proposal.model_copy(update={
            "capability": NPCCapability.EXPLAIN,
            "action": AgentAction(
                action_id=prior.proposal.action.action_id,
                action_type=AgentActionType.RESPOND,
                dialogue="行动不可用，暂不执行。",
                confidence=0.0,
            ),
        })
        return prior.model_copy(update={"proposal": proposal, "llm_attempts": 2, "used_fallback": True})


def serve(service):
    server = ClinicHTTPServer(("127.0.0.1", 0), service)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    return server, thread


def stop(server, thread):
    server.shutdown(); server.server_close(); thread.join(timeout=3)
    assert not thread.is_alive()


def test_web_natural_language_reaches_agent_and_npc_can_reject_and_choose_tool(tmp_path):
    clinic = build_clinic(tmp_path)
    agent = CooperativeWebAgent()
    clinic.game_npc_agent = agent
    player = clinic.create_player("协作玩家").player_summary.player_id
    opened = clinic.start_case(player, "old_paper_umbrella")
    before = clinic.store.load_case_session(opened.session_id).revision
    server, thread = serve(clinic)
    try:
        port = server.server_address[1]
        status, headers, _ = request(port, "POST", "/cases/natural", {
            "player_id": player,
            "case_id": opened.case_id,
            "session_id": opened.session_id,
            "operation_id": "op_cooperative_one",
            "text": "直接治疗吧，不要调查。",
        })
        assert status == 303
        status, _, page = request(port, "GET", headers["Location"])
        assert status == 200
        assert "建议评价" in page and "reject" in page
        assert "玩家建议不是命令" in page
        assert "NPC 回应" in page and "环境反馈" in page
        assert "采取行动" in page and "行动依据" in page
        assert "runtime：test_double" in page and "raw tool：" in page
    finally:
        stop(server, thread)

    assert len(agent.inputs) == 1
    assert agent.inputs[0].player_contribution.public_text == "直接治疗吧，不要调查。"
    chosen = agent.inputs[0].case_observation.available_investigations[-1].investigation_id
    session = clinic.store.load_case_session(opened.session_id)
    assert session.revision == before + 1
    assert session.action_history[-1].reference_id == chosen


def prepare_treatment(clinic, player, opened):
    counter = 0
    while True:
        observation = clinic.resume_case(player, opened.case_id, opened.session_id).observation
        if observation.can_submit_diagnosis:
            break
        assert observation.available_investigations
        option = observation.available_investigations[0]
        counter += 1
        clinic.submit_case_action(ClinicActionInput(
            player_id=player, case_id=opened.case_id, session_id=opened.session_id,
            operation_id=f"manual_prepare_{counter}", action_type="investigation",
            selection_id=option.investigation_id,
        ))
    diagnosis = observation.diagnosis_candidates[0]
    clinic.submit_case_action(ClinicActionInput(
        player_id=player, case_id=opened.case_id, session_id=opened.session_id,
        operation_id="manual_prepare_diagnosis", action_type="diagnosis",
        selection_id=diagnosis.diagnosis_id,
        evidence_clue_ids=tuple(item.clue_id for item in observation.discovered_clues),
    ))
    observation = clinic.resume_case(player, opened.case_id, opened.session_id).observation
    assert observation.available_treatments
    return observation.available_treatments[0].treatment_id


def prepare_diagnosis(clinic, player, opened):
    counter = 0
    while True:
        observation = clinic.resume_case(player, opened.case_id, opened.session_id).observation
        if observation.can_submit_diagnosis:
            return observation
        option = observation.available_investigations[0]
        counter += 1
        clinic.submit_case_action(ClinicActionInput(
            player_id=player, case_id=opened.case_id, session_id=opened.session_id,
            operation_id=f"manual_diagnosis_prepare_{counter}", action_type="investigation",
            selection_id=option.investigation_id,
        ))


def test_diagnosis_proposal_completes_minimal_negotiation_loop(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("辨证玩家").player_summary.player_id
    opened = clinic.start_case(player, "old_paper_umbrella")
    observation = prepare_diagnosis(clinic, player, opened)
    diagnosis_id = observation.diagnosis_candidates[0].diagnosis_id
    clinic.game_npc_agent = CooperativeWebAgent(force_diagnosis=diagnosis_id)
    before = clinic.store.load_case_session(opened.session_id).revision
    server, thread = serve(clinic)
    try:
        port = server.server_address[1]
        status, headers, _ = request(port, "POST", "/cases/cooperate", {
            "player_id": player, "case_id": opened.case_id, "session_id": opened.session_id,
            "operation_id": "op_diagnosis_proposal", "contribution_type": "hypothesis",
            "text": "我认为可以形成辨证了。",
        })
        assert status == 303
        assert clinic.store.load_case_session(opened.session_id).revision == before
        _, _, page = request(port, "GET", headers["Location"])
        assert "同意诊断提议" in page and "该行动尚未执行" in page
        confirmation_id = re.search(r'name="confirmation_id" value="([^"]+)"', page).group(1)
        decision_id = re.search(r'name="decision_id" value="([^"]+)"', page).group(1)
        status, _, _ = request(port, "POST", "/cases/cooperate/respond", {
            "player_id": player, "case_id": opened.case_id, "session_id": opened.session_id,
            "operation_id": "op_diagnosis_approval", "confirmation_id": confirmation_id,
            "decision_id": decision_id, "response": "approve",
        })
        assert status == 303
    finally:
        stop(server, thread)
    session = clinic.store.load_case_session(opened.session_id)
    assert session.revision == before + 1
    assert session.submitted_diagnosis_id == diagnosis_id


def test_treatment_is_not_executed_until_web_confirmation(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("确认玩家").player_summary.player_id
    opened = clinic.start_case(player, "old_paper_umbrella")
    treatment_id = prepare_treatment(clinic, player, opened)
    agent = CooperativeWebAgent(force_treatment=treatment_id)
    clinic.game_npc_agent = agent
    before = clinic.store.load_case_session(opened.session_id)
    server, thread = serve(clinic)
    try:
        port = server.server_address[1]
        status, headers, _ = request(port, "POST", "/cases/cooperate", {
            "player_id": player, "case_id": opened.case_id, "session_id": opened.session_id,
            "operation_id": "op_treatment_proposal", "contribution_type": "suggestion",
            "text": "现在是否可以处置？",
        })
        assert status == 303
        pending_location = headers["Location"]
        pending_session = clinic.store.load_case_session(opened.session_id)
        assert pending_session.revision == before.revision
        assert pending_session.status == before.status
        _, _, page = request(port, "GET", pending_location)
        assert "该行动尚未执行" in page and "确认高风险处置" in page
        confirmation_id = re.search(r'name="confirmation_id" value="([^"]+)"', page).group(1)
        decision_id = re.search(r'name="decision_id" value="([^"]+)"', page).group(1)

        status, headers, _ = request(port, "POST", "/cases/cooperate/respond", {
            "player_id": player, "case_id": opened.case_id, "session_id": opened.session_id,
            "operation_id": "op_treatment_approval", "confirmation_id": confirmation_id,
            "decision_id": decision_id, "response": "approve",
        })
        assert status == 303
        _, _, completed_page = request(port, "GET", headers["Location"])
        assert "环境反馈" in completed_page
    finally:
        stop(server, thread)

    after = clinic.store.load_case_session(opened.session_id)
    assert after.revision == before.revision + 1
    assert after.selected_treatment_id == treatment_id
    assert len(agent.inputs) == 2
    assert agent.inputs[1].player_contribution.contribution_type.value == "approval"


def test_case_page_marks_direct_action_route_as_manual_baseline(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("兼容玩家").player_summary.player_id
    opened = clinic.start_case(player, "old_paper_umbrella")
    server, thread = serve(clinic)
    try:
        _, _, page = request(server.server_address[1], "GET", f"/cases?player_id={player}&case_id={opened.case_id}&session_id={opened.session_id}")
        assert 'action="/cases/cooperate"' in page
        assert "不会由页面直接转换为工具调用" in page
        assert "cooperative 模式不启用独立师父 Agent" in page
        assert "legacy manual / teaching 模式" in page
    finally:
        stop(server, thread)


def test_cooperative_mode_suppresses_independent_mentor_but_manual_keeps_it(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("主体边界玩家").player_summary.player_id
    cooperative = clinic.start_case(player, "old_paper_umbrella", cooperative=True)
    dialogue = clinic.case_dialogues.load(cooperative.session_id, player, cooperative.case_id)
    assert not any(item.message_type == "mentor_private" for item in dialogue.recent_messages)

    response, _ = clinic.case_chat_message(
        player, cooperative.case_id, cooperative.session_id,
        "op_coop_mentor_block", "@师父 请提示", allow_mentor=False,
    )
    assert response.speaker_id == "system"
    assert "独立师父介入仅在" in response.public_text

    manual = clinic.start_case(player, "gray_hearth_inn", cooperative=False)
    manual_dialogue = clinic.case_dialogues.load(manual.session_id, player, manual.case_id)
    assert any(item.message_type == "mentor_private" for item in manual_dialogue.recent_messages)
