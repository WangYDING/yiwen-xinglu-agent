from __future__ import annotations

import re
import threading

from xuanyi_npc.application.clinic import ClinicActionInput, ClinicError
from xuanyi_npc.application.multicase import CreatePlayerInput
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
from xuanyi_npc.storage import SQLiteCooperativeHistoryRepository
from tests.clinic_helpers import build_clinic, request


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


def test_case_lobby_uses_player_facing_statuses_before_a_case_starts(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("选案玩家").player_summary.player_id
    server, thread = serve(clinic)
    try:
        status, _, page = request(
            server.server_address[1], "GET", f"/cases?player_id={player}"
        )
        assert status == 200
        assert "选择一桩异案，与调查搭档共同查明真相" in page
        assert "同行 NPC" not in page
        assert "六案均可选择" not in page
        assert page.count("类型：异象案") == 6
        assert page.count("可接案") == 6
        assert page.count(">接案</button>") == 6
        assert "available" not in page
    finally:
        stop(server, thread)


def test_start_page_disambiguates_legacy_duplicate_names_and_blocks_new_duplicate(tmp_path):
    clinic = build_clinic(tmp_path)
    first = clinic.base_service.create_player(CreatePlayerInput(display_name="001"))
    second = clinic.base_service.create_player(CreatePlayerInput(display_name="001"))
    assert first.ok and first.player_id and second.ok and second.player_id
    opened = clinic.start_case(first.player_id, "gray_hearth_inn")
    server, thread = serve(clinic)
    try:
        port = server.server_address[1]
        status, _, page = request(port, "GET", "/")
        assert status == 200
        assert "001（档案 1）" in page and "001（档案 2）" in page
        assert "正在调查：灰灶客栈与无火炊烟" in page
        assert "尚未接案" in page
        assert f"session_id={opened.session_id}" in page
        assert "JSON" not in page and "Session ID" not in page

        status, headers, _ = request(port, "POST", "/players", {
            "display_name": " 001 ",
            "operation_id": "op_duplicate_player_name",
        })
        assert status == 303
        assert headers["Location"].startswith("/?notice=")
        status, _, duplicate_page = request(port, "GET", headers["Location"])
        assert status == 200
        assert "这个玩家名已经有调查档案" in duplicate_page
        assert len(clinic.list_players()) == 2
    finally:
        stop(server, thread)


def test_player_creation_retries_colliding_id_and_logout_returns_to_start(tmp_path):
    clinic = build_clinic(tmp_path)
    first = clinic.create_player("甲").player_summary

    class CollidingThenUniqueIds:
        def __init__(self):
            self.values = iter((first.player_id, "player_unique_after_collision"))

        def new_player_id(self):
            return next(self.values)

    clinic.base_service.player_id_factory = CollidingThenUniqueIds()
    second = clinic.create_player("乙").player_summary
    assert second.player_id == "player_unique_after_collision"
    assert second.player_id != first.player_id
    assert len({item.player_id for item in clinic.list_players()}) == 2

    server, thread = serve(clinic)
    try:
        port = server.server_address[1]
        status, _, page = request(
            port, "GET", f"/clinic?player_id={second.player_id}"
        )
        assert status == 200
        assert 'action="/quit"' in page
        assert ">退出登录</button>" in page

        status, headers, _ = request(port, "POST", "/quit", {
            "operation_id": "op_logout_player",
        })
        assert status == 303
        assert headers["Location"] == "/"
        status, _, start_page = request(port, "GET", headers["Location"])
        assert status == 200
        assert "创建玩家档案" in start_page
    finally:
        stop(server, thread)


def test_welcome_page_uses_player_facing_language_and_keeps_logout(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("初行玩家").player_summary.player_id
    server, thread = serve(clinic)
    try:
        status, _, page = request(
            server.server_address[1], "GET", f"/welcome?player_id={player}"
        )
        assert status == 200
        assert "同行须知" in page
        assert "独立行动的调查搭档" in page
        assert "以实际调查为准" in page
        assert "系统旁白" not in page
        assert "自主 NPC" not in page
        assert "公开证据" not in page
        assert "案件规则裁定" not in page
        assert 'action="/quit"' in page and "退出登录" in page
    finally:
        stop(server, thread)


def test_duplicate_live_submission_waits_in_case_instead_of_showing_error(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("等待页玩家").player_summary.player_id
    opened = clinic.start_case(player, "gray_hearth_inn")

    def in_progress(_request):
        raise ClinicError("operation_in_progress", "同一协作操作仍在处理中，请稍后重试。")

    clinic.submit_player_contribution = in_progress
    server, thread = serve(clinic)
    token = "op_duplicate_live"
    try:
        port = server.server_address[1]
        status, headers, _ = request(port, "POST", "/cases/cooperate", {
            "player_id": player,
            "case_id": opened.case_id,
            "session_id": opened.session_id,
            "operation_id": token,
            "text": "检查一下大门。",
        })
        assert status == 303
        assert headers["Location"].startswith("/cases/wait?")

        status, _, waiting_page = request(port, "GET", headers["Location"])
        assert status == 200
        assert "调查搭档正在思考" in waiting_page
        assert "不需要重新选择玩家" in waiting_page
        assert "同一协作操作仍在处理中" not in waiting_page
        assert "window.location.reload" in waiting_page

        completed_location = (
            f"/cases?player_id={player}&case_id={opened.case_id}"
            f"&session_id={opened.session_id}#turn-result"
        )
        server.operation_results[token] = completed_location
        status, completed_headers, _ = request(port, "GET", headers["Location"])
        assert status == 303
        assert completed_headers["Location"] == completed_location

        status, _, case_page = request(
            port,
            "GET",
            f"/cases?player_id={player}&case_id={opened.case_id}&session_id={opened.session_id}",
        )
        assert status == 200
        assert "搭档思考中…" in case_page
        assert 'onsubmit="return submitCooperativeForm(this,event)"' in case_page
        assert "event.preventDefault()" in case_page
        assert "调查搭档正在结合现场线索思考" in case_page
        assert "response.url.includes('/cases/wait')" in case_page
        assert "focusLatestCooperativeTurn" in case_page
    finally:
        stop(server, thread)


def test_web_natural_language_reaches_agent_and_npc_can_reject_and_choose_tool(tmp_path):
    clinic = build_clinic(tmp_path)
    clinic.cooperative_record_enabled = True
    clinic.cooperative_history_repository = SQLiteCooperativeHistoryRepository(
        tmp_path / "cooperative_conversation.sqlite3"
    )
    agent = CooperativeWebAgent()
    clinic.game_npc_agent = agent
    player = clinic.create_player("协作玩家").player_summary.player_id
    opened = clinic.start_case(player, "old_paper_umbrella")
    before = clinic.store.load_case_session(opened.session_id).revision
    server, thread = serve(clinic)
    try:
        port = server.server_address[1]
        status, _, lobby_page = request(
            port, "GET", f"/cases?player_id={player}"
        )
        assert status == 200
        assert "你已有一桩异案正在调查" in lobby_page
        assert 'class="card case-card case-card-active"' in lobby_page
        assert "当前调查" in lobby_page
        assert lobby_page.count(
            '<button type="button" disabled>先完成当前案件</button>'
        ) == 5
        assert ">接案</button>" not in lobby_page
        assert "available" not in lobby_page

        initial_url = (
            f"/cases?player_id={player}&case_id={opened.case_id}"
            f"&session_id={opened.session_id}"
        )
        status, _, initial_page = request(port, "GET", initial_url)
        assert status == 200
        assert 'class="card cooperative-card"' in initial_page
        assert 'class="cooperative-log" id="turn-result"' in initial_page
        assert "还没有聊天记录" in initial_page
        assert '<select name="contribution_type">' not in initial_page
        assert 'name="contribution_type"' not in initial_page
        assert "像聊天一样直接输入即可" in initial_page
        assert initial_page.index('id="turn-result"') < initial_page.index(
            'class="cooperative-composer"'
        )

        status, headers, _ = request(port, "POST", "/cases/natural", {
            "player_id": player,
            "case_id": opened.case_id,
            "session_id": opened.session_id,
            "operation_id": "op_cooperative_one",
            "text": "直接治疗吧，不要调查。",
        })
        assert status == 303
        assert headers["Location"].endswith("#turn-result")
        status, _, page = request(port, "GET", headers["Location"])
        assert status == 200
        assert 'class="turn-message turn-message-player"' in page
        assert 'class="turn-message turn-message-partner"' in page
        assert page.count('class="card cooperative-card"') == 1
        assert "还没有聊天记录" not in page
        assert "直接治疗吧，不要调查。" in page
        assert "对你的建议" not in page
        assert 'class="turn-assessment-data" hidden' in page and "未采纳" in page
        assert 'aria-label="查看搭档的判断"' in page
        assert 'id="partner-assessment-modal" hidden' in page
        assert "showPartnerAssessment(this)" in page
        assert "closePartnerAssessment()" in page
        assert "玩家建议不是命令" in page
        assert "调查搭档" in page and "发现新线索" in page
        assert "搭档改为调查" in page
        assert "行动依据" not in page.split("<details>", 1)[0]
        assert "开发信息" not in page
        assert "runtime：test_double" not in page and "raw tool：" not in page

        status, _, restored_page = request(port, "GET", initial_url)
        assert status == 200
        assert "还没有聊天记录" not in restored_page
        assert "直接治疗吧，不要调查。" in restored_page
        assert "我不接受直接处置" in restored_page
        assert 'class="turn-message turn-message-player"' in restored_page
        assert 'class="turn-message turn-message-partner"' in restored_page
        assert "对你的建议" not in restored_page
        assert agent.inputs[0].player_contribution.contribution_type.value == "suggestion"
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
        assert "现场反馈" in completed_page
    finally:
        stop(server, thread)

    after = clinic.store.load_case_session(opened.session_id)
    assert after.revision == before.revision + 1
    assert after.selected_treatment_id == treatment_id
    assert len(agent.inputs) == 2
    assert agent.inputs[0].player_contribution.contribution_type.value == "general_message"
    assert agent.inputs[1].player_contribution.contribution_type.value == "approval"


def test_case_page_exposes_only_cooperative_product_route(tmp_path):
    clinic = build_clinic(tmp_path)
    player = clinic.create_player("兼容玩家").player_summary.player_id
    opened = clinic.start_case(player, "old_paper_umbrella")
    server, thread = serve(clinic)
    try:
        _, _, page = request(server.server_address[1], "GET", f"/cases?player_id={player}&case_id={opened.case_id}&session_id={opened.session_id}")
        assert 'action="/cases/cooperate"' in page
        assert "像聊天一样直接输入即可" in page
        assert 'name="contribution_type"' not in page
        assert 'mode=manual' not in page
        assert "与案中人物交谈" in page
        assert "与调查搭档商议行动请使用上方协作框" in page
        assert "案中人物" in page and "病例参与者" not in page
        assert "当前求医者" not in page and "向病例角色说话" not in page
    finally:
        stop(server, thread)
