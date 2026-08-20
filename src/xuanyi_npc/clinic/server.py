"""Loopback-only standard-library HTTP experience for the six-case clinic."""

from __future__ import annotations

import argparse
import html
import secrets
import re
import sys
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from pydantic import ValidationError

from xuanyi_npc.agents import DeterministicFakeMentor
from xuanyi_npc.application.clinic import ClinicActionInput, ClinicContributionInput, ClinicError, ClinicService
from xuanyi_npc.domain.cooperation import PlayerContributionType
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalStatus,
    AgentGoalType,
    AgentPlanStatus,
    PlanEvaluationOutcome,
    PlanStepStatus,
)
from xuanyi_npc.application.clinic_mentor import ClinicMentorMode, ClinicMentorRuntime
from xuanyi_npc.application.multicase import CaseCatalog, SystemEpisodeClock
from xuanyi_npc.resources.runtime import materialized_clinic_resources
from xuanyi_npc.resources.runtime import read_runtime_text
from xuanyi_npc.storage import JsonStateStore, StateNotFoundError
from xuanyi_npc.application.public_presentation import PUBLIC_PRESENTATION
from xuanyi_npc.application.player_experience import mentor_reply, propose_investigation
from xuanyi_npc.application.case_mentor import case_participants


STYLE = """
:root{color-scheme:light;--ink:#26352f;--jade:#426b5a;--paper:#f6f0df;--card:#fffaf0;--line:#cbbf9e}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
header,main{max-width:980px;margin:auto;padding:1rem}header{border-bottom:1px solid var(--line)}
h1,h2{font-family:serif;color:#294f40}nav a,a{color:var(--jade)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem;margin:.7rem 0}.case-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.mentor{border-left:5px solid var(--jade)}
button{background:var(--jade);color:white;border:0;border-radius:6px;padding:.55rem .9rem}input,select,textarea{max-width:100%;width:100%;padding:.45rem;border:1px solid var(--line)}
.notice{border-left:4px solid #9a7338;padding:.6rem;background:#fff8dc}.error{color:#8b2d2d}small{color:#58665f}
.case-workspace{display:grid;grid-template-columns:minmax(220px,1fr) minmax(300px,1.4fr) minmax(240px,1fr);gap:1rem;align-items:start}.progress-done{color:var(--jade)}
.chat{max-width:820px;height:min(60vh,560px);min-height:400px;margin:1rem auto;display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:16px;background:rgba(255,255,255,.42)}
.chat>p{margin:.55rem .8rem .25rem}.chat-log{flex:1;min-height:0;overflow-y:auto;padding:.25rem .75rem .45rem;scrollbar-gutter:stable}
.bubble{width:fit-content;max-width:70%;padding:.38rem .72rem;border-radius:12px;margin:.28rem 0;background:#fff;border:1px solid var(--line);overflow-wrap:anywhere}
.bubble strong{font-size:.82rem}.bubble p{margin:.12rem 0 0;line-height:1.42}.bubble.player{margin-left:auto;background:#dff2e8}.bubble.mentor_private{margin-right:auto;border-left:4px solid #7656a8;background:#f2ecff}.bubble.case_character{margin-right:auto}
.bubble.system,.bubble.clue,.bubble.rejection{width:auto;max-width:70%;margin:.3rem auto;padding:.3rem .65rem;text-align:center;border-radius:8px;background:#fff5d7}.bubble.rejection{background:#fff0eb}
.composer{position:sticky;z-index:2;bottom:0;display:flex;gap:.5rem;align-items:center;margin:0;padding:.55rem .75rem;background:var(--paper);border-top:1px solid var(--line);box-shadow:0 -5px 14px rgba(38,32,22,.06)}.composer input[name=message]{flex:1;min-width:0;margin:0}.composer button{width:auto;flex:0 0 auto;margin:0;white-space:nowrap}.drawers{max-width:900px;margin:auto}.private-mark{color:#7656a8;font-size:.78rem}
@media(max-width:640px){.chat{height:55dvh;min-height:390px;margin:.55rem -.35rem;border-radius:12px}.chat-log{padding:.2rem .45rem .35rem}.bubble{max-width:72%;padding:.32rem .6rem;margin:.22rem 0}.bubble.system,.bubble.clue,.bubble.rejection{max-width:72%;margin:.24rem auto}.composer{padding:.45rem}.composer button{padding:.65rem .8rem}}
@media(max-width:700px){.case-grid,.case-workspace{grid-template-columns:1fr}header,main{padding:.75rem}.card{overflow-wrap:anywhere}}
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(title)} · 问道医途</title><style>{STYLE}</style></head><body><header><h1>问道医途 · 玄医馆</h1><p class="notice">全部病案与玄术均为架空游戏内容，不构成现实医疗建议。</p></header><main>{body}</main></body></html>"""
    return document.encode("utf-8")


GOAL_TYPE_LABELS = {
    AgentGoalType.RESOLVE_CASE: "完成病例",
    AgentGoalType.GATHER_EVIDENCE: "收集证据",
    AgentGoalType.VALIDATE_HYPOTHESIS: "验证判断",
    AgentGoalType.FORM_DIAGNOSIS: "形成辨证",
    AgentGoalType.SELECT_TREATMENT: "选择处置",
    AgentGoalType.DISCUSS_RISK: "协商风险",
}
GOAL_STATUS_LABELS = {
    AgentGoalStatus.ACTIVE: "进行中",
    AgentGoalStatus.COMPLETED: "已完成",
    AgentGoalStatus.BLOCKED: "暂时受阻",
    AgentGoalStatus.ABANDONED: "已结束",
}
PLAN_STEP_LABELS = {
    PlanStepStatus.COMPLETED: ("✓", "已完成"),
    PlanStepStatus.ACTIVE: ("→", "当前"),
    PlanStepStatus.PENDING: ("○", "待进行"),
    PlanStepStatus.OBSOLETE: ("↷", "已调整"),
    PlanStepStatus.BLOCKED: ("!", "暂不可执行"),
}
PLAN_EVALUATION_LABELS = {
    PlanEvaluationOutcome.KEEP_PLAN: "继续计划",
    PlanEvaluationOutcome.REVISE_PLAN: "计划调整",
    PlanEvaluationOutcome.COMPLETE_GOAL: "目标完成",
    PlanEvaluationOutcome.ABANDON_PLAN: "计划结束",
}


def build_clinic_service(state_dir: Path, resources, mentor_runtime=None) -> ClinicService:
    return ClinicService(
        store=JsonStateStore(state_dir), base_catalog=CaseCatalog(resources.case_dir),
        campaign_path=resources.campaign_rules, clock=SystemEpisodeClock(), mentor_runtime=mentor_runtime,
        mentor_agent_factory=DeterministicFakeMentor,
    )


class ClinicHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, service: ClinicService):
        host, _ = address
        if host != "127.0.0.1":
            raise ValueError("xuanyi-clinic only binds to 127.0.0.1")
        self.clinic_service = service
        self.operation_results: dict[str, str] = {}
        super().__init__(address, ClinicRequestHandler)


class ClinicRequestHandler(BaseHTTPRequestHandler):
    server: ClinicHTTPServer

    def log_message(self, format, *args):
        return

    def _send(self, status: int, payload: bytes, content_type="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(payload)

    def _redirect(self, location: str):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _query(self):
        return {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items() if values}

    def _form(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ClinicError("invalid_form", "表单长度无效。")
        if size < 0 or size > 32768:
            raise ClinicError("invalid_form", "表单过大。")
        return {key: values[0] for key, values in parse_qs(self.rfile.read(size).decode("utf-8"), keep_blank_values=True).items() if values}

    def _token(self):
        return "op_" + secrets.token_hex(12)

    def _player_id(self, values):
        value = values.get("player_id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
            raise ClinicError("player_required", "请选择或创建弟子。")
        return value

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            query = self._query()
            if parsed.path == "/":
                self._start()
            elif parsed.path == "/clinic":
                self._home(self._player_id(query))
            elif parsed.path == "/welcome":
                self._welcome(self._player_id(query))
            elif parsed.path == "/foundation":
                self._foundation(self._player_id(query))
            elif parsed.path == "/cases":
                self._cases(self._player_id(query), query.get("case_id"), query.get("session_id"))
            elif parsed.path == "/teaching":
                self._teaching(self._player_id(query))
            elif parsed.path == "/exam":
                self._exam(self._player_id(query))
            elif parsed.path == "/inheritance":
                self._inheritance(self._player_id(query))
            elif parsed.path == "/assessment":
                self._assessment(self._player_id(query))
            elif parsed.path == "/static/clinic.css":
                self._send(200, read_runtime_text("clinic/clinic.css").encode(), "text/css; charset=utf-8")
            elif parsed.path == "/static/clinic.js":
                self._send(200, read_runtime_text("clinic/clinic.js").encode(), "text/javascript; charset=utf-8")
            elif parsed.path == "/health":
                self._send(200, b'{"status":"ok"}', "application/json")
            else:
                self._error(404, "页面不存在。")
        except (ClinicError, ValidationError, ValueError) as exc:
            self._error(400, str(exc))
        except Exception:
            self._error(500, "医馆暂时无法处理请求，已保留最后一次成功进度。")

    def do_POST(self):
        try:
            path = urlparse(self.path).path
            form = self._form()
            token = form.get("operation_id", "")
            if not token.startswith("op_"):
                raise ClinicError("operation_required", "操作令牌无效，请刷新页面后重试。")
            if token in self.server.operation_results:
                self._redirect(self.server.operation_results[token])
                return
            if path == "/players":
                view = self.server.clinic_service.create_player(form.get("display_name", ""))
                location = "/welcome?" + urlencode({"player_id": view.player_summary.player_id})
            elif path == "/welcome/complete":
                player_id = self._player_id(form)
                location = "/foundation?" + urlencode({"player_id": player_id})
            elif path == "/foundation/complete":
                player_id=self._player_id(form)
                self.server.clinic_service.complete_foundation_exercise(player_id,form.get("exercise_id",""),form.get("action_id",""))
                location="/foundation?"+urlencode({"player_id":player_id})
            elif path == "/mentor/ask":
                player_id=self._player_id(form)
                location="/teaching?"+urlencode({"player_id":player_id,"mentor_message":mentor_reply(form.get("text",""))})
            elif path in {"/cases/natural", "/cases/cooperate"}:
                player_id=self._player_id(form);case_id=form.get("case_id","");session_id=form.get("session_id","")
                result=self.server.clinic_service.submit_player_contribution(ClinicContributionInput(
                    player_id=player_id,case_id=case_id,session_id=session_id,
                    operation_id=token,text=form.get("text",""),
                    contribution_type=PlayerContributionType(form.get("contribution_type","suggestion")),
                ))
                location="/cases?"+urlencode(self._cooperative_query(player_id,case_id,session_id,result))
            elif path == "/cases/cooperate/respond":
                player_id=self._player_id(form);case_id=form.get("case_id","");session_id=form.get("session_id","")
                approved=form.get("response")=="approve"
                result=self.server.clinic_service.submit_player_contribution(ClinicContributionInput(
                    player_id=player_id,case_id=case_id,session_id=session_id,operation_id=token,
                    text=("我批准这项行动，请你依据最新状态再次判断。" if approved else "我不同意这项行动，请提出其他方案。"),
                    contribution_type=(PlayerContributionType.APPROVAL if approved else PlayerContributionType.REJECTION),
                    responds_to_decision_id=form.get("decision_id") or None,
                    pending_confirmation_id=form.get("confirmation_id") or None,
                ))
                location="/cases?"+urlencode(self._cooperative_query(player_id,case_id,session_id,result))
            elif path == "/cases/mentor":
                player_id=self._player_id(form);case_id=form.get("case_id","");session_id=form.get("session_id","")
                reply,_=self.server.clinic_service.mentor_case_message(player_id,case_id,session_id,form.get("text",""))
                location="/cases?"+urlencode({"player_id":player_id,"case_id":case_id,"session_id":session_id,"mentor_notice":reply.message})
            elif path == "/cases/chat":
                player_id=self._player_id(form);case_id=form.get("case_id","");session_id=form.get("session_id","")
                manual=form.get("interaction_mode")=="manual"
                self.server.clinic_service.case_chat_message(player_id,case_id,session_id,token,form.get("message", ""),allow_mentor=manual)
                values={"player_id":player_id,"case_id":case_id,"session_id":session_id}
                if manual: values["mode"]="manual"
                location="/cases?"+urlencode(values)
            elif path == "/cases/start":
                player_id = self._player_id(form)
                result = self.server.clinic_service.start_case(player_id, form.get("case_id", ""), cooperative=True)
                location = "/cases?" + urlencode({"player_id": player_id, "case_id": result.case_id, "session_id": result.session_id})
            elif path == "/cases/action":
                request = ClinicActionInput(
                    player_id=self._player_id(form), case_id=form.get("case_id", ""), session_id=form.get("session_id", ""),
                    operation_id=token, action_type=form.get("action_type", ""), selection_id=form.get("selection_id", ""),
                    evidence_clue_ids=tuple(item for item in form.get("evidence_clue_ids", "").split(",") if item),
                )
                if request.action_type=="treatment":
                    session=self.server.clinic_service.store.load_case_session(request.session_id)
                    pending,_=self.server.clinic_service.mentor_intervention(request.player_id,request.case_id,request.session_id,"risky_treatment_pending",event_key=f"{request.selection_id}_{session.revision}")
                    if pending is not None:
                        location="/cases?"+urlencode({"player_id":request.player_id,"case_id":request.case_id,"session_id":request.session_id,"notice":"师父已提醒风险；请阅读传音后再次确认。"})
                        self.server.operation_results[token]=location;self._redirect(location);return
                result = self.server.clinic_service.submit_case_action(request)
                location = "/cases?" + urlencode({"player_id": request.player_id, "case_id": request.case_id, "session_id": request.session_id})
            elif path == "/inheritance/request":
                player_id = self._player_id(form)
                applied = self.server.clinic_service.inheritance.request(player_id)
                values = {"player_id": player_id}
                if self.server.clinic_service.mentor_status["mode"] == "deepseek":
                    request_id = "inheritance_grant_1" if applied.granted else "inheritance_refusal_1"
                    explained = self.server.clinic_service.mentor_expression(player_id, request_id)
                    values.update({"mentor_message": explained.message, "mentor_notice": explained.notice or ""})
                location = "/inheritance?" + urlencode(values)
            elif path == "/mentor/explain":
                if self.server.clinic_service.mentor_status["mode"] != "deepseek":
                    raise ClinicError("mentor_mode_local", "当前使用本地确定性导师。")
                player_id = self._player_id(form)
                result = self.server.clinic_service.mentor_expression(player_id, form.get("request_id", ""))
                location = "/teaching?" + urlencode({"player_id": player_id, "mentor_message": result.message, "mentor_notice": result.notice or ""})
            elif path == "/remediations":
                player_id = self._player_id(form)
                teaching = self.server.clinic_service.teaching_service(player_id)
                teaching.plan_service.attempt_remediation(
                    player_id=player_id, remediation_id=form.get("remediation_id", ""),
                    option_id=form.get("option_id", ""), request_id=token,
                )
                location = "/teaching?" + urlencode({"player_id": player_id})
            elif path == "/exam/start":
                player_id = self._player_id(form)
                self.server.clinic_service.exams.start(player_id, request_id=token)
                location = "/exam?" + urlencode({"player_id": player_id})
            elif path == "/exam/answer":
                player_id = self._player_id(form)
                self.server.clinic_service.exams.record_answer(
                    player_id=player_id, exam_session_id=form.get("exam_session_id", ""),
                    question_id=form.get("question_id", ""),
                    selected_option_ids=(form.get("option_id", ""),),
                )
                location = "/exam?" + urlencode({"player_id": player_id})
            elif path == "/exam/submit":
                player_id = self._player_id(form)
                submitted=self.server.clinic_service.exams.submit(
                    player_id=player_id, exam_session_id=form.get("exam_session_id", ""),
                )
                public=self.server.clinic_service.exams.public_result(player_id,form.get("exam_session_id",""))
                values={"player_id":player_id}
                if not public.passed and self.server.clinic_service.mentor_status["mode"] == "deepseek":
                    explained = self.server.clinic_service.mentor_expression(player_id, "exam_failure_explanation_1")
                    values.update({"mentor_message": explained.message, "mentor_notice": explained.notice or ""})
                location = "/exam?" + urlencode(values)
            elif path == "/quit":
                location = "/"
            else:
                raise ClinicError("route_not_found", "该操作不存在。")
            self.server.operation_results[token] = location
            self._redirect(location)
        except (ClinicError, ValidationError, ValueError) as exc:
            self._error(400, str(exc))
        except Exception:
            self._error(500, "操作未完成；已保留最后一次成功进度。")

    @staticmethod
    def _cooperative_query(player_id,case_id,session_id,result):
        evaluation=result.decision.proposal.contribution_evaluation
        trace=result.memory_usage_trace
        values={"player_id":player_id,"case_id":case_id,"session_id":session_id,
                "npc_reply":result.decision.proposal.action.dialogue,
                "npc_action":result.decision.proposal.capability.value,
                "npc_tool_public":result.selected_public_target or "",
                "npc_rationale":result.public_rationale,
                "runtime_kind":result.runtime_kind.value,
                "debug_tool_name":result.selected_tool.value if result.selected_tool is not None else "",
                "environment_feedback":result.environment_message or "",
                "contribution_id":result.turn_id,
                "goal_changed":"1" if result.goal_changed else "",
                "plan_changed":"1" if result.plan_changed else "",
                "plan_evaluation_outcome":result.plan_evaluation_outcome or "",
                "plan_change_reason":result.public_plan_change_reason or "",
                "memory_retrieval_status":result.memory_retrieval_status.value if result.memory_retrieval_status is not None else "",
                "memory_retrieval_id":result.memory_retrieval_id or "",
                "memory_selected_count":str(result.selected_memory_count),
                "memory_public_effect":result.public_memory_effect_summary or "",
                "reflection_triggered":"1" if result.reflection_triggered else "",
                "reflection_trigger_type":result.reflection_trigger_type.value if result.reflection_trigger_type else "",
                "reflection_trigger_id":result.reflection_trigger_id or "",
                "reflection_status":result.reflection_status.value if result.reflection_status else "",
                "reflection_proposal_status":result.reflection_proposal_status.value if result.reflection_proposal_status else "",
                "reflection_candidate_ids":",".join(result.reflection_candidate_ids),
                "reflection_written_memory_ids":",".join(result.reflection_written_memory_ids),
                "reflection_write_outcomes":",".join(result.reflection_write_outcomes),
                "reflection_rejection_reasons":",".join(result.reflection_rejection_reasons),
                "reflection_provenance_ref_ids":",".join(result.reflection_provenance_ref_ids),
                "public_consolidation_summary":result.public_consolidation_summary or ""}
        if trace is not None:
            values.update({
                "memory_candidate_ids":",".join(trace.candidate_memory_ids),
                "memory_selected_ids":",".join(trace.selected_memory_ids),
                "memory_declared_used_ids":",".join(trace.declared_used_memory_ids),
                "memory_accepted_used_ids":",".join(trace.accepted_used_memory_ids),
                "memory_rejected_ids":",".join(trace.rejected_memory_ids),
                "memory_attribution_status":trace.attribution_status.value,
                "memory_influence_types":",".join(trace.influence_types),
            })
        if evaluation is not None:
            values.update({"suggestion_disposition":evaluation.disposition.value,
                           "suggestion_explanation":evaluation.explanation})
        if result.pending_action is not None:
            values.update({"confirmation_id":result.pending_action.confirmation_id,
                           "decision_id":result.pending_action.decision_id,
                           "authority_mode":result.pending_action.authority_mode.value})
        return values

    def _nav(self, player_id):
        q = urlencode({"player_id": player_id})
        return f'<nav><a href="/clinic?{q}">医馆主页</a> · <a href="/teaching?{q}">导师教学</a> · <a href="/cases?{q}">病例</a> · <a href="/exam?{q}">考试</a> · <a href="/inheritance?{q}">传承</a> · <a href="/assessment?{q}">师评</a></nav>'

    def _welcome(self, player_id):
        player=self.server.clinic_service.home(player_id).player_summary
        mentor=self.server.clinic_service.mentor_status
        runtime=(f'<section class="card"><h3>导师运行</h3><p>模式：真实DeepSeek</p><p>已用费用：{_esc(mentor["used_cost"])} CNY</p><form method="post" action="/mentor/explain"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="request_id" value="initial_lesson_hint_1"><input type="hidden" name="operation_id" value="{self._token()}"><button>请导师说明初课与提示</button></form></section>' if mentor["mode"]=="deepseek" else '')
        body=f'''<h2>首次入馆</h2><section class="card"><h3>系统旁白</h3><p>你是玄医馆新收的弟子。这里收治的并非寻常病痛，而是人与契、物、炁息交缠所成的异象。你需要亲自询问、查验、辨明因果，再决定如何处置。</p></section><section class="card mentor"><h3>师父</h3><p>你来了。医馆今日已有数案候诊。先别急着下结论，记住：问清来由，核对证据，再谈施治。</p></section><form method="post" action="/welcome/complete"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>记下教诲，前往选案</button></form>'''
        body=f'<p>入馆弟子：{_esc(player.display_name)}</p>'+runtime+body
        self._send(200,_page("首次入馆",body))

    def _start(self):
        players = self.server.clinic_service.list_players()
        restored = "".join(f'<li><a href="/clinic?player_id={_esc(item.player_id)}">{_esc(item.display_name)}</a></li>' for item in players) or "<li>尚无弟子存档</li>"
        body = f"""<h2>进入医馆</h2><div class="grid"><section class="card"><h3>创建弟子</h3><form method="post" action="/players"><label>弟子名 <input name="display_name" maxlength="40" required></label><input type="hidden" name="operation_id" value="{self._token()}"><button>创建并进入</button></form></section><section class="card"><h3>恢复弟子</h3><ul>{restored}</ul></section></div><p>无需输入工具名、JSON、Session ID 或内部规则；页面会把自然语言选择转换为严格应用命令。</p>"""
        self._send(200, _page("开始", body))

    def _home(self, player_id):
        view = self.server.clinic_service.home(player_id)
        ability = "".join(f"<li><strong>{_esc(item['name'])}</strong>：{item['proficiency']} · {_esc(item['level_name'])} · {'已解锁' if item['unlocked'] else '未习得'}<br><small>{_esc(item['level_description'])}</small></li>" for item in view.abilities)
        cases = "".join(f"<li>{_esc(item.title)}：{_esc(PUBLIC_PRESENTATION.name('case_status', item.status, fallback='状态已更新'))}</li>" for item in view.visible_cases)
        mentor = self.server.clinic_service.mentor_status
        runtime = ""
        if mentor["mode"] == "deepseek":
            runtime = f'''<section class="card"><h3>导师运行</h3><p>模式：真实DeepSeek</p><p>状态：{_esc('可用' if mentor['available'] else '已切换安全模式')}</p><p>已用费用：{_esc(mentor['used_cost'])} CNY · 剩余：{_esc(mentor['remaining_budget'])} CNY</p><p>fallback：{_esc('是' if mentor['fallback_active'] else '否')}</p></section>'''
        recommendation = PUBLIC_PRESENTATION.recommendation_name(view.current_recommendation.kind, view.current_recommendation.recommendation_id)
        stage = PUBLIC_PRESENTATION.name("stage", view.teaching_stage, fallback="当前修习阶段")
        permissions = "、".join(PUBLIC_PRESENTATION.name("permission", item, fallback="已开放内容") for item in view.permissions)
        exam_status = PUBLIC_PRESENTATION.name("exam_status", view.exam_status, fallback="考试状态已更新")
        inheritance_status = PUBLIC_PRESENTATION.name("inheritance_status", view.inheritance_status, fallback="传承状态已更新")
        body = f'''{self._nav(player_id)}<h2>{_esc(view.player_summary.display_name)}的医馆</h2>{runtime}<div class="grid"><section class="card"><h3>导师与课程</h3><p>{_esc(view.mentor_summary)}</p><p>阶段：{_esc(stage)}</p><p>当前建议：{_esc(recommendation)}</p><p><a href="/foundation?player_id={_esc(player_id)}">入门教学</a></p></section><section class="card"><h3>七项能力</h3><ul>{ability}</ul></section><section class="card"><h3>关系</h3><p>亲近 {_esc(view.relationship['affinity'])} · 信任 {_esc(view.relationship['trust'])} · 认可 {_esc(view.relationship['recognition'])}</p></section><section class="card"><h3>六病例</h3><ul>{cases}</ul></section><section class="card"><h3>考试与传承</h3><p>考试：{_esc(exam_status)}</p><p>传承：{_esc(inheritance_status)}</p><p>权限：{_esc(permissions)}</p></section></div>'''
        self._send(200, _page("医馆", body))

    def _foundation(self,player_id):
        state=self.server.clinic_service.store.load_apprenticeship(player_id)
        policy=self.server.clinic_service.base_service.progression_policy
        cards=[]
        prior_complete=True
        for item in policy.config.foundation_exercises:
            ability=state.abilities[item.ability_id]
            if ability.unlocked:
                action='<strong>已完成 · 基础熟练度 '+str(ability.proficiency)+'</strong>'
            elif not prior_complete:
                action='<button disabled>请先完成上一项练习</button>'
            else:
                action=f'<form method="post" action="/foundation/complete"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="exercise_id" value="{_esc(item.exercise_id)}"><input type="hidden" name="action_id" value="{_esc(item.required_action_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>完成结构化练习</button></form>'
            cards.append(f'<section class="card"><h3>{_esc(item.title)}</h3><p>{_esc(item.public_goal)}</p>{action}</section>')
            prior_complete=prior_complete and ability.unlocked
        done=all(x.unlocked for x in state.abilities.values())
        tail=(f'<p><a href="/cases?player_id={_esc(player_id)}">七项入门完成，前往选案</a></p>' if done else '<p>练习结果由规则验证；导师说明不会直接解锁能力。</p>')
        self._send(200,_page("入门教学",self._nav(player_id)+'<h2>七项能力入门</h2><div class="grid">'+''.join(cards)+'</div>'+tail))

    def _cases(self, player_id, case_id=None, session_id=None):
        service = self.server.clinic_service._service(player_id)
        if not case_id:
            view = self.server.clinic_service.home(player_id)
            labels={"not_started":"未开始","active":"调查中","completed":"已完成"}
            cards = "".join(f'<section class="card"><h3>{_esc(item.title)}</h3><p>{_esc(item.synopsis)}</p><p><strong>难度：</strong>异象案</p><p class="status">状态：{_esc(labels.get(item.status,item.status))}</p>{"<p class=\"recommended\">师父推荐</p>" if item.recommended else ""}<form method="post" action="/cases/start"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(item.case_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>{"继续调查" if item.status=="active" else "接案"}</button></form></section>' for item in view.visible_cases)
            self._send(200, _page("六案大厅", self._nav(player_id) + '<h2>六病例选案大厅</h2><p>推荐仅供参考，六案均可选择。</p><div class="case-grid">' + cards + "</div>"))
            return
        if not session_id:
            raise ClinicError("session_required", "缺少病例进度。")
        result,guide,guide_stages,current_stage,dialogue,abilities = self.server.clinic_service.case_experience(player_id, case_id, session_id)
        observation = result.observation
        if observation is None:
            raise ClinicError("case_unavailable", "病例公开状态不可用。")
        clues = "".join(f"<li>{_esc(item.description)}</li>" for item in observation.discovered_clues) or "<li>尚未发现</li>"
        actions = "".join(f'<form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="investigation"><input type="hidden" name="selection_id" value="{_esc(item.investigation_id)}"><button>{_esc(item.public_description)}</button></form>' for item in observation.available_investigations)
        diagnoses = "".join(f'<option value="{_esc(item.diagnosis_id)}">{_esc(item.public_description)}</option>' for item in observation.diagnosis_candidates)
        notice=self._query().get("notice","")
        body = f'''{self._nav(player_id)}<h2>{_esc(observation.title)}</h2><p>{_esc(observation.synopsis)}</p>{f'<p class="notice">{_esc(notice)}</p>' if notice else ''}<section class="card"><h3>自然语言调查</h3><form method="post" action="/cases/natural"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><textarea name="text" rows="3" required placeholder="例如：询问乘客虚弱出现的先后顺序"></textarea><button>执行调查提案</button></form><small>文本先转换为行动提案，病例规则会再次校验能力、熟练度与前置证据。</small></section><section class="card"><h3>线索簿</h3><ul>{clues}</ul></section><details class="card"><summary>无障碍／模型不可用时的降级调查入口</summary>{actions or '<p>暂无</p>'}</details>'''
        stage_html="".join(f'<li class="{"progress-done" if done else ""}">{"✓" if done else "○"} {_esc(stage.title)}<p>{_esc(stage.public_purpose)}</p><small>参考问法（不会自动执行）：{_esc("；".join(stage.suggested_questions))}</small></li>' for stage,done in guide_stages)
        mentor_history="".join(f'<p><strong>{"你" if turn.role=="player" else "师父"}：</strong>{_esc(turn.text)}</p>' for turn in dialogue.recent_mentor_turns)
        ability_html="".join(f'<li>{_esc(item.name)} · {item.proficiency} · {"可用" if item.executable else _esc(item.reason)}</li>' for item in abilities)
        mentor_notice=self._query().get("mentor_notice","")
        embedded=f'''<p><strong>本案学习目标：</strong>{_esc(guide.learning_goal)}</p><div class="case-workspace"><section class="card"><h3>病例专属调查提纲</h3><ul>{stage_html}</ul></section><section class="card"><h3>病例人物对话与调查</h3><p>在下方自然语言调查框中说明交谈对象、问题或检查目标。</p></section><aside><section class="card mentor"><h3>病例内请教师父</h3>{mentor_history}{f'<p class="notice">{_esc(mentor_notice)}</p>' if mentor_notice else ''}<form method="post" action="/cases/mentor"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><textarea name="text" rows="3" required placeholder="请教师父调查方法或证据整理"></textarea><button>请教师父指点</button></form></section><section class="card"><h3>当前能力和行动限制</h3><ul>{ability_html}</ul><small>服务端会在每次行动时重新校验。</small></section></aside></div>'''
        body=body.replace(f'<h2>{_esc(observation.title)}</h2>',f'<h2>{_esc(observation.title)}</h2>'+embedded)
        manual_mode=self._query().get("mode")=="manual"
        participants=case_participants(case_id);names={x.participant_id:x.display_name for x in participants}|{"player":"你","mentor":"师父"}
        bubbles="".join(f'<article class="bubble {_esc(msg.message_type)}"><strong>{_esc(names.get(msg.speaker_id,"系统"))}</strong>{"<span class=\"private-mark\"> · 师徒传音</span>" if msg.message_type=="mentor_private" else ""}<p>{_esc(msg.public_text)}</p></article>' for msg in dialogue.recent_messages) or '<p class="notice">尚未开始交谈。默认接收者为当前求医者；输入 @ 可切换人物或师父。</p>'
        options=('<option value="@师父 "></option>' if manual_mode else '')+''.join(f'<option value="@{_esc(x.display_name)} "></option>' for x in participants)
        current=names.get(dialogue.current_target,"请选择")
        chat=f'''<section class="chat"><p>当前交谈对象：<strong>{_esc(current)}</strong></p><div class="chat-log">{bubbles}</div><form class="composer" method="post" action="/cases/chat"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="interaction_mode" value="{'manual' if manual_mode else 'cooperative'}"><input type="hidden" name="operation_id" value="{self._token()}"><textarea name="message" rows="3" list="case-recipients" required placeholder="{'向角色说话，或输入 @师父' if manual_mode else '向病例角色说话；NPC 协作请使用上方协作框'}"></textarea><datalist id="case-recipients">{options}</datalist><button>发送</button></form></section>'''
        chat=chat.replace('<textarea name="message" rows="3" list="case-recipients"','<input name="message" list="case-recipients"').replace('</textarea><datalist','><datalist')
        drawers=f'''<section class="drawers"><details class="card"><summary>调查提纲与进度</summary><ul>{stage_html}</ul></details><details class="card"><summary>已发现线索</summary><ul>{clues}</ul></details><details class="card"><summary>能力与技法</summary><ul>{ability_html}</ul></details><details class="card"><summary>病例参与者</summary><ul>{''.join(f'<li>{_esc(x.display_name)}</li>' for x in participants)}</ul></details><details class="card"><summary>辨证与处置</summary><p>达到规则要求后，下方将显示可提交入口。</p></details></section>'''
        query=self._query();npc_reply=query.get("npc_reply","");disposition=query.get("suggestion_disposition","")
        suggestion_explanation=query.get("suggestion_explanation","");npc_action=query.get("npc_action","")
        environment_feedback=query.get("environment_feedback","");confirmation_id=query.get("confirmation_id","")
        decision_id=query.get("decision_id","");authority_mode=query.get("authority_mode","")
        npc_tool_public=query.get("npc_tool_public","");npc_rationale=query.get("npc_rationale","")
        runtime_kind=query.get("runtime_kind","");debug_tool_name=query.get("debug_tool_name","")
        goal_changed=query.get("goal_changed","")=="1";plan_changed=query.get("plan_changed","")=="1"
        contribution_id=query.get("contribution_id","")
        memory_public_effect=query.get("memory_public_effect","")
        memory_accepted_ids=query.get("memory_accepted_used_ids","")
        memory_effect_html=(f'<p class="notice"><strong>过往经验：</strong>{_esc(memory_public_effect)}</p>' if memory_public_effect and memory_accepted_ids else "")
        memory_debug_html=(
            f'<p>memory retrieval status：{_esc(query.get("memory_retrieval_status","") or "none")}</p>'
            f'<p>retrieval ID：{_esc(query.get("memory_retrieval_id","") or "none")}</p>'
            f'<p>candidate count：{len([x for x in query.get("memory_candidate_ids","").split(",") if x])}</p>'
            f'<p>selected count：{_esc(query.get("memory_selected_count","0"))}</p>'
            f'<p>candidate memory IDs：{_esc(query.get("memory_candidate_ids",""))}</p>'
            f'<p>selected memory IDs：{_esc(query.get("memory_selected_ids",""))}</p>'
            f'<p>declared used memory IDs：{_esc(query.get("memory_declared_used_ids",""))}</p>'
            f'<p>accepted used memory IDs：{_esc(query.get("memory_accepted_used_ids",""))}</p>'
            f'<p>rejected memory IDs：{_esc(query.get("memory_rejected_ids",""))}</p>'
            f'<p>attribution status：{_esc(query.get("memory_attribution_status",""))}</p>'
            f'<p>influence types：{_esc(query.get("memory_influence_types",""))}</p>'
        )
        reflection_written_ids=query.get("reflection_written_memory_ids","")
        reflection_learning_html=(
            f'<p class="notice"><strong>经验沉淀：</strong>{_esc(query.get("public_consolidation_summary",""))}</p>'
            if reflection_written_ids and query.get("public_consolidation_summary","")
            else ""
        )
        reflection_debug_html=(
            f'<p>reflection trigger type：{_esc(query.get("reflection_trigger_type","") or "none")}</p>'
            f'<p>reflection trigger ID：{_esc(query.get("reflection_trigger_id","") or "none")}</p>'
            f'<p>reflection status：{_esc(query.get("reflection_status","") or "none")}</p>'
            f'<p>proposal status：{_esc(query.get("reflection_proposal_status","") or "none")}</p>'
            f'<p>candidate IDs：{_esc(query.get("reflection_candidate_ids",""))}</p>'
            f'<p>write outcomes：{_esc(query.get("reflection_write_outcomes",""))}</p>'
            f'<p>written memory IDs：{_esc(reflection_written_ids)}</p>'
            f'<p>rejection reasons：{_esc(query.get("reflection_rejection_reasons",""))}</p>'
            f'<p>provenance refs：{_esc(query.get("reflection_provenance_ref_ids",""))}</p>'
        )
        planning_card=""
        if not manual_mode:
            try:
                agent_state=self.server.clinic_service.store.load_cooperative_agent_state(
                    session_id,player_id=player_id,case_id=case_id
                )
            except StateNotFoundError:
                agent_state=None
            if agent_state is not None:
                goal=agent_state.current_goal;plan=agent_state.current_plan
                goal_type=GOAL_TYPE_LABELS[goal.goal_type];goal_status=GOAL_STATUS_LABELS[goal.status]
                plan_items="";current_step="";plan_debug="<p>plan：none</p>"
                if plan is not None:
                    for step in plan.steps:
                        icon,label=PLAN_STEP_LABELS[step.status]
                        plan_items+=f'<li class="plan-step plan-{_esc(step.status.value)}"><strong>{_esc(icon)} {_esc(label)}：</strong>{_esc(step.public_summary)}</li>'
                        if step.status is PlanStepStatus.ACTIVE:
                            current_step=step.public_summary
                    plan_debug=f'<p>plan ID：{_esc(plan.plan_id)}</p><p>plan revision：{plan.revision}</p><p>current step ID：{_esc(plan.steps[plan.current_step_index].step_id)}</p>'
                evaluation=agent_state.last_plan_evaluation
                evaluation_html="";evaluation_debug="<p>evaluation：none</p>"
                if evaluation is not None:
                    evaluation_label=PLAN_EVALUATION_LABELS[evaluation.outcome]
                    if evaluation.outcome is PlanEvaluationOutcome.COMPLETE_GOAL:
                        evaluation_html='<p class="notice"><strong>当前目标已完成。</strong></p>'
                    else:
                        evaluation_html=f'<p><strong>计划状态：</strong>{_esc(evaluation_label)}</p><p><strong>原因：</strong>{_esc(evaluation.public_summary)}</p>'
                    evaluation_debug=f'<p>evaluation outcome：{_esc(evaluation.outcome.value)}</p><p>evaluation reason：{_esc(evaluation.reason_code.value)}</p><p>observation revision：{evaluation.observation_revision_after}</p>'
                player_changed=(goal_changed and goal.source_contribution_id==contribution_id) or (plan_changed and plan is not None and plan.source_contribution_id==contribution_id)
                changed_html='<p class="notice">NPC 根据你的建议调整了调查计划。</p>' if player_changed else ''
                memory_plan_html='<p class="notice">NPC 根据过往经验调整了调查计划。</p>' if memory_public_effect and memory_accepted_ids and plan_changed else ''
                planning_card=f'''<section class="card npc-thinking"><h3>NPC 当前思路</h3><p><strong>当前目标：</strong>{_esc(goal.public_description)}</p><p><strong>方向：</strong>{_esc(goal_type)} · <strong>状态：</strong>{_esc(goal_status)}</p>{f'<h4>当前计划</h4><ul>{plan_items}</ul>' if plan_items else '<p>当前计划尚待形成。</p>'}{f'<p class="notice"><strong>NPC 当前准备：</strong>{_esc(current_step)}</p>' if current_step else ''}{changed_html}{memory_plan_html}{evaluation_html}<details><summary>开发信息</summary><p>goal ID：{_esc(goal.goal_id)}</p><p>goal revision：{goal.revision}</p>{plan_debug}{evaluation_debug}<p>runtime：{_esc(runtime_kind or 'unknown')}</p>{memory_debug_html}</details></section>'''
        cooperative_result=""
        if npc_reply or disposition or environment_feedback:
            cooperative_result=f'''<section class="card"><h3>NPC 协作结果</h3>{f'<p><strong>建议评价：</strong>{_esc(disposition)} · {_esc(suggestion_explanation)}</p>' if disposition else ''}{f'<p><strong>NPC 回应：</strong>{_esc(npc_reply)}</p>' if npc_reply else ''}{memory_effect_html}{reflection_learning_html}{f'<p><strong>采取行动：</strong>{_esc(npc_tool_public)}</p>' if npc_tool_public else ''}{f'<p><strong>行动依据：</strong>{_esc(npc_rationale)}</p>' if npc_rationale else ''}{f'<p><strong>环境反馈：</strong>{_esc(environment_feedback)}</p>' if environment_feedback else ''}<details><summary>开发信息</summary><p>runtime：{_esc(runtime_kind or 'unknown')}</p><p>capability：{_esc(npc_action)}</p><p>raw tool：{_esc(debug_tool_name or 'none')}</p>{memory_debug_html}{reflection_debug_html}</details></section>'''
        confirmation=""
        if confirmation_id and decision_id:
            label="同意诊断提议" if authority_mode=="proposal_only" else "确认高风险处置"
            hidden=f'<input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="confirmation_id" value="{_esc(confirmation_id)}"><input type="hidden" name="decision_id" value="{_esc(decision_id)}">'
            confirmation=f'''<section class="card notice"><h3>需要玩家协商</h3><p>该行动尚未执行。NPC 会在你回应后依据最新病例状态再次判断。</p><form method="post" action="/cases/cooperate/respond">{hidden}<input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="response" value="approve"><button>{label}</button></form><form method="post" action="/cases/cooperate/respond">{hidden}<input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="response" value="reject"><button>拒绝并要求替代方案</button></form></section>'''
        cooperative_form=(f'''<section class="card"><h3>与 NPC 协作</h3><form method="post" action="/cases/cooperate"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><select name="contribution_type"><option value="suggestion">建议调查方向</option><option value="hypothesis">提出假设</option><option value="challenge">质疑 NPC</option><option value="evidence_interpretation">解释证据</option><option value="question">询问判断</option></select><textarea name="text" rows="3" required placeholder="表达你的假设或建议；NPC 会独立评价并决定具体行动。"></textarea><button>与 NPC 讨论并推进</button></form><small>你的输入是建议或判断，不会由页面直接转换为工具调用。cooperative 模式不启用独立师父 Agent。</small><p><a href="/cases?{urlencode({"player_id":player_id,"case_id":case_id,"session_id":session_id,"mode":"manual"})}">进入 legacy manual / teaching 模式</a></p></section>''' if not manual_mode else f'<section class="card"><h3>Manual / teaching 模式</h3><p>当前保留旧师父教学与手动行动入口。</p><a href="/cases?{urlencode({"player_id":player_id,"case_id":case_id,"session_id":session_id})}">返回 cooperative 模式</a></section>')
        body=f'''{self._nav(player_id)}<h2>{_esc(observation.title)}</h2><p>{_esc(observation.synopsis)}</p>{cooperative_form}{planning_card}{cooperative_result}{confirmation}{chat}{drawers}'''
        if observation.can_submit_diagnosis:
            evidence = ",".join(item.clue_id for item in observation.discovered_clues)
            body += f'<details class="card"><summary>Manual / baseline：直接提交辨证</summary><form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="diagnosis"><input type="hidden" name="evidence_clue_ids" value="{_esc(evidence)}"><select name="selection_id">{diagnoses}</select><button>提交辨证</button></form></details>'
        treatments = "".join(f'<form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="treatment"><input type="hidden" name="selection_id" value="{_esc(item.treatment_id)}"><button>{_esc(item.public_description)}</button></form>' for item in observation.available_treatments)
        if treatments:
            body += '<details class="card"><summary>Manual / baseline：直接选择处置</summary>' + treatments + '</details>'
        self._send(200, _page("病例", body))

    def _exam(self, player_id):
        view = self.server.clinic_service.home(player_id)
        attempts = sorted((item for item in self.server.clinic_service.store.list_exam_sessions() if item.player_id == player_id), key=lambda item: item.attempt_number)
        active = next((item for item in attempts if item.result is None), None)
        query=self._query();message=query.get("mentor_message","");notice=query.get("mentor_notice","")
        public_exam_status=PUBLIC_PRESENTATION.name("exam_status",view.exam_status,fallback="考试状态已更新")
        body = self._nav(player_id) + f"<h2>玄医入门综合考</h2><p>当前状态：{_esc(public_exam_status)}</p><p>考试由固定规则评分，不由导师代答。</p>"+(f'<p class="notice">{_esc(notice)}</p>' if notice else '')+(f'<section class="card"><h3>导师解释</h3><p>{_esc(message)}</p></section>' if message else '')
        if attempts and attempts[-1].result is not None:
            result = attempts[-1].result
            remediation = "、".join(PUBLIC_PRESENTATION.name("remediation", item) for item in result.required_remediation_ids) or "无"
            body += f'<section class="card"><h3>公开结果</h3><p>{"通过" if result.passed else "未通过"} · {result.total_score} 分</p><p>补课：{_esc(remediation)}</p></section>'
        if active is None and view.exam_status == "eligible":
            body += self._post_button("/exam/start", player_id, "开始考试")
        elif active is not None:
            questions = self.server.clinic_service.exams.public_questions(player_id)
            for question in questions:
                if question.question_id in active.submitted_answers:
                    continue
                options = "".join(f'<label><input type="radio" name="option_id" value="{_esc(item["option_id"])}" required>{_esc(item["public_text"])}</label><br>' for item in question.options)
                body += f'<section class="card"><p>{_esc(question.public_scenario)}</p><form method="post" action="/exam/answer"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="exam_session_id" value="{_esc(active.exam_session_id)}"><input type="hidden" name="question_id" value="{_esc(question.question_id)}"><input type="hidden" name="operation_id" value="{self._token()}">{options}<button>确认本题</button></form></section>'
            if len(active.submitted_answers) == len(questions):
                body += f'<form method="post" action="/exam/submit"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="exam_session_id" value="{_esc(active.exam_session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>提交整场考试</button></form>'
        self._send(200, _page("考试", body))

    def _teaching(self, player_id):
        teaching = self.server.clinic_service.teaching_service(player_id)
        plan = teaching.plan_service.ensure(player_id)
        query=self._query();message=query.get("mentor_message","");notice=query.get("mentor_notice","")
        rendered=(f'<p class="notice">{_esc(notice)}</p>' if notice else '')+(f'<section class="card"><h3>导师说明</h3><p>{_esc(message)}</p></section>' if message else '')
        body = self._nav(player_id) + f'''<h2>请教师父</h2><section class="card mentor"><form method="post" action="/mentor/ask"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><textarea name="text" rows="3" required placeholder="询问玩法、能力、当前建议或调查原则"></textarea><button>请教</button></form></section><p>师父不会泄露隐藏线索、正确辨证或处置，也不会替你执行行动。</p>'''+rendered
        real_mode = self.server.clinic_service.mentor_status["mode"] == "deepseek"
        if real_mode:
            body += f'<form method="post" action="/mentor/explain"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="request_id" value="initial_lesson_hint_1"><input type="hidden" name="operation_id" value="{self._token()}"><button>请导师说明初课与提示</button></form>'
        for remediation_id in (plan.current_recommendation.recommendation_id,):
            if remediation_id not in teaching.curriculum.remediations:
                continue
            item = teaching.curriculum.remediations[remediation_id]
            options = "".join(f'<button name="option_id" value="{_esc(option.option_id)}">{_esc(option.public_text)}</button>' for option in item.answer_options)
            body += f'<section class="card"><h3>{_esc(item.title)}</h3><p>{_esc(item.structured_question)}</p><form method="post" action="/remediations"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="remediation_id" value="{_esc(remediation_id)}"><input type="hidden" name="operation_id" value="{self._token()}">{options}</form></section>'
            if real_mode and remediation_id == "remediate_diagnostic_reasoning_v1":
                body += f'<form method="post" action="/mentor/explain"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="request_id" value="wrong_diagnosis_remediation_1"><input type="hidden" name="operation_id" value="{self._token()}"><button>请导师解释本次辨证补课</button></form>'
        sessions = [item for item in self.server.clinic_service.store.list_teaching_sessions() if item.player_id == player_id]
        body += '<section class="card"><h3>课程记录</h3><ul>' + ("".join(f'<li>{_esc(PUBLIC_PRESENTATION.name("lesson",item.lesson_id))} · {_esc(PUBLIC_PRESENTATION.name("phase",item.phase.value))} · 提示 {len(item.used_hint_ids)}/2</li>' for item in sessions) or '<li>尚无课程记录</li>') + '</ul></section>'
        self._send(200, _page("导师教学", body))

    def _assessment(self, player_id):
        sessions = [item for item in self.server.clinic_service.store.list_teaching_sessions() if item.player_id == player_id and item.assessment is not None]
        cards = "".join(f'<section class="card"><h3>{_esc(PUBLIC_PRESENTATION.name("lesson",item.lesson_id))}</h3><p>{_esc(PUBLIC_PRESENTATION.sanitize_legacy_text(item.mentor_review.message) if item.mentor_review else "结构化师评已形成")}</p><p>改进方向：{_esc("、".join(PUBLIC_PRESENTATION.name("ability",value.value) for value in item.assessment.improvement_abilities) or "无")}</p></section>' for item in sessions)
        self._send(200, _page("师评", self._nav(player_id) + '<h2>成长与师徒历程</h2>' + (cards or '<p>完成病例后将在此显示师评。</p>')))

    def _post_button(self, path, player_id, label):
        return f'<form method="post" action="{path}"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>{_esc(label)}</button></form>'

    def _inheritance(self, player_id):
        result = self.server.clinic_service.inheritance.policy.decide(player_id)
        reasons = "、".join(result.missing_requirement_categories) or "公开条件已满足"
        query=self._query();message=query.get("mentor_message","");notice=query.get("mentor_notice","")
        body = self._nav(player_id) + f'<h2>传承</h2><p>当前资格：{_esc(reasons)}</p>'+(f'<p class="notice">{_esc(notice)}</p>' if notice else '')+(f'<section class="card"><h3>导师解释</h3><p>{_esc(message)}</p></section>' if message else '')+f'<form method="post" action="/inheritance/request"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>申请“溯契还因”</button></form>'
        self._send(200, _page("传承", body))

    def _error(self, status, message):
        self._send(status, _page("安全错误", f'<h2 class="error">无法完成</h2><p>{_esc(message)}</p><p><a href="/">返回开始页</a></p>'))


def build_parser():
    parser = argparse.ArgumentParser(prog="xuanyi-clinic", description="启动仅绑定 127.0.0.1 的本地玄医馆。")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--mentor-mode",choices=("off","fake","deepseek"),default="fake")
    parser.add_argument("--confirm-paid-run",action="store_true")
    parser.add_argument("--budget-cny")
    parser.add_argument("--dry-run",action="store_true")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.dry_run:
        if args.mentor_mode!="deepseek": print("dry-run：本地确定性导师；loopback=127.0.0.1；网络调用=0");return 0
        try: budget=Decimal(args.budget_cny or "")
        except InvalidOperation: print("启动失败：预算格式无效。",file=sys.stderr);return 2
        if budget<=0 or budget>Decimal("0.05"): print("启动失败：预算必须大于0且不超过0.05 CNY。",file=sys.stderr);return 2
        print(f"dry-run：model=deepseek-v4-flash；thinking=disabled；pricing=deepseek_v4_flash_mentor_pricing_2026_08_13；budget={budget}；interactions=初课提示,错误诊断补课,考试失败,传承拒绝,传承授予；fallback=确定性；storage=state-dir本地脱敏账本；loopback=127.0.0.1；网络调用=0")
        return 0
    if args.state_dir is None or not args.state_dir.is_dir():
        print("启动失败：存档目录必须已经存在。", file=sys.stderr)
        return 2
    mode=ClinicMentorMode(args.mentor_mode);runtime=None
    if mode is ClinicMentorMode.DEEPSEEK:
        if not args.confirm_paid_run: print("启动失败：真实导师必须显式确认付费运行。",file=sys.stderr);return 2
        try: budget=Decimal(args.budget_cny or "")
        except InvalidOperation: print("启动失败：预算格式无效。",file=sys.stderr);return 2
        if budget<=0 or budget>Decimal("0.05"): print("启动失败：预算必须大于0且不超过0.05 CNY。",file=sys.stderr);return 2
        from dotenv import dotenv_values
        from pydantic import SecretStr
        from xuanyi_npc.evaluation.real_mentor_transport import RealMentorDeepSeekTransport,load_mentor_pilot_pricing
        from xuanyi_npc.application.clinic_mentor import ClinicMentorBudgetGuard
        pricing=load_mentor_pilot_pricing(Path(__file__).parents[1]/"resources/pilot/deepseek_v4_flash_mentor_pricing_2026-08-13.json")
        key=(dotenv_values(Path.cwd()/".env",encoding="utf-8",interpolate=False).get("DEEPSEEK_API_KEY") or "").strip()
        if not key: print("启动失败：真实导师凭据不可用。",file=sys.stderr);return 2
        transport=RealMentorDeepSeekTransport(SecretStr(key),ClinicMentorBudgetGuard(budget,pricing),timeout_seconds=30)
        runtime=ClinicMentorRuntime(mode,args.state_dir,transport,budget)
    elif mode is ClinicMentorMode.OFF: runtime=ClinicMentorRuntime(mode,args.state_dir)
    with materialized_clinic_resources() as resources:
        service = build_clinic_service(args.state_dir, resources,runtime)
        server = ClinicHTTPServer((args.host, args.port), service)
        host, port = server.server_address
        print(f"玄医馆已启动：http://{host}:{port}", flush=True)
        try:
            server.serve_forever(poll_interval=0.1)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
