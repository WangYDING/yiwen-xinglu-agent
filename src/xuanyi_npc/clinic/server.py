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
from xuanyi_npc.application.clinic import ClinicActionInput, ClinicError, ClinicService
from xuanyi_npc.application.clinic_mentor import ClinicMentorMode, ClinicMentorRuntime
from xuanyi_npc.application.multicase import CaseCatalog, SystemEpisodeClock
from xuanyi_npc.resources.runtime import materialized_clinic_resources
from xuanyi_npc.resources.runtime import read_runtime_text
from xuanyi_npc.storage import JsonStateStore
from xuanyi_npc.application.public_presentation import PUBLIC_PRESENTATION


STYLE = """
:root{color-scheme:light;--ink:#26352f;--jade:#426b5a;--paper:#f6f0df;--card:#fffaf0;--line:#cbbf9e}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
header,main{max-width:980px;margin:auto;padding:1rem}header{border-bottom:1px solid var(--line)}
h1,h2{font-family:serif;color:#294f40}nav a,a{color:var(--jade)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem;margin:.7rem 0}
button{background:var(--jade);color:white;border:0;border-radius:6px;padding:.55rem .9rem}input,select{max-width:100%;padding:.45rem;border:1px solid var(--line)}
.notice{border-left:4px solid #9a7338;padding:.6rem;background:#fff8dc}.error{color:#8b2d2d}small{color:#58665f}
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(title)} · 问道医途</title><style>{STYLE}</style></head><body><header><h1>问道医途 · 玄医馆</h1><p class="notice">全部病案与玄术均为架空游戏内容，不构成现实医疗建议。</p></header><main>{body}</main></body></html>"""
    return document.encode("utf-8")


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
                location = "/clinic?" + urlencode({"player_id": view.player_summary.player_id})
            elif path == "/cases/start":
                player_id = self._player_id(form)
                result = self.server.clinic_service.start_case(player_id, form.get("case_id", ""))
                location = "/cases?" + urlencode({"player_id": player_id, "case_id": result.case_id, "session_id": result.session_id})
            elif path == "/cases/action":
                request = ClinicActionInput(
                    player_id=self._player_id(form), case_id=form.get("case_id", ""), session_id=form.get("session_id", ""),
                    operation_id=token, action_type=form.get("action_type", ""), selection_id=form.get("selection_id", ""),
                    evidence_clue_ids=tuple(item for item in form.get("evidence_clue_ids", "").split(",") if item),
                )
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

    def _nav(self, player_id):
        q = urlencode({"player_id": player_id})
        return f'<nav><a href="/clinic?{q}">医馆主页</a> · <a href="/teaching?{q}">导师教学</a> · <a href="/cases?{q}">病例</a> · <a href="/exam?{q}">考试</a> · <a href="/inheritance?{q}">传承</a> · <a href="/assessment?{q}">师评</a></nav>'

    def _start(self):
        players = self.server.clinic_service.list_players()
        restored = "".join(f'<li><a href="/clinic?player_id={_esc(item.player_id)}">{_esc(item.display_name)}</a></li>' for item in players) or "<li>尚无弟子存档</li>"
        body = f"""<h2>进入医馆</h2><div class="grid"><section class="card"><h3>创建弟子</h3><form method="post" action="/players"><label>弟子名 <input name="display_name" maxlength="40" required></label><input type="hidden" name="operation_id" value="{self._token()}"><button>创建并进入</button></form></section><section class="card"><h3>恢复弟子</h3><ul>{restored}</ul></section></div><p>无需输入工具名、JSON、Session ID 或内部规则；页面会把自然语言选择转换为严格应用命令。</p>"""
        self._send(200, _page("开始", body))

    def _home(self, player_id):
        view = self.server.clinic_service.home(player_id)
        ability = "".join(f"<li>{_esc(item['name'])}：{item['proficiency']}</li>" for item in view.abilities)
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
        body = f'''{self._nav(player_id)}<h2>{_esc(view.player_summary.display_name)}的医馆</h2>{runtime}<div class="grid"><section class="card"><h3>导师与课程</h3><p>{_esc(view.mentor_summary)}</p><p>阶段：{_esc(stage)}</p><p>当前建议：{_esc(recommendation)}</p></section><section class="card"><h3>六项能力</h3><ul>{ability}</ul></section><section class="card"><h3>关系</h3><p>亲近 {_esc(view.relationship['affinity'])} · 信任 {_esc(view.relationship['trust'])} · 认可 {_esc(view.relationship['recognition'])}</p></section><section class="card"><h3>六病例</h3><ul>{cases}</ul></section><section class="card"><h3>考试与传承</h3><p>考试：{_esc(exam_status)}</p><p>传承：{_esc(inheritance_status)}</p><p>权限：{_esc(permissions)}</p></section></div>'''
        self._send(200, _page("医馆", body))

    def _cases(self, player_id, case_id=None, session_id=None):
        service = self.server.clinic_service._service(player_id)
        if not case_id:
            view = self.server.clinic_service.home(player_id)
            cards = "".join(f'<section class="card"><h3>{_esc(item.title)}</h3><p>{_esc(item.synopsis)}</p><form method="post" action="/cases/start"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(item.case_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>开始或恢复</button></form></section>' for item in view.visible_cases)
            self._send(200, _page("病例", self._nav(player_id) + '<h2>可见病例</h2><div class="grid">' + cards + "</div>"))
            return
        if not session_id:
            raise ClinicError("session_required", "缺少病例进度。")
        result = self.server.clinic_service.resume_case(player_id, case_id, session_id)
        observation = result.observation
        if observation is None:
            raise ClinicError("case_unavailable", "病例公开状态不可用。")
        clues = "".join(f"<li>{_esc(item.description)}</li>" for item in observation.discovered_clues) or "<li>尚未发现</li>"
        actions = "".join(f'<form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="investigation"><input type="hidden" name="selection_id" value="{_esc(item.investigation_id)}"><button>{_esc(item.public_description)}</button></form>' for item in observation.available_investigations)
        diagnoses = "".join(f'<option value="{_esc(item.diagnosis_id)}">{_esc(item.public_description)}</option>' for item in observation.diagnosis_candidates)
        body = f'''{self._nav(player_id)}<h2>{_esc(observation.title)}</h2><p>{_esc(observation.synopsis)}</p><section class="card"><h3>已发现线索</h3><ul>{clues}</ul></section><section class="card"><h3>可用调查</h3>{actions or '<p>暂无</p>'}</section>'''
        if observation.can_submit_diagnosis:
            evidence = ",".join(item.clue_id for item in observation.discovered_clues)
            body += f'<section class="card"><h3>提交辨证</h3><form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="diagnosis"><input type="hidden" name="evidence_clue_ids" value="{_esc(evidence)}"><select name="selection_id">{diagnoses}</select><button>提交辨证</button></form></section>'
        treatments = "".join(f'<form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="treatment"><input type="hidden" name="selection_id" value="{_esc(item.treatment_id)}"><button>{_esc(item.public_description)}</button></form>' for item in observation.available_treatments)
        if treatments:
            body += '<section class="card"><h3>可用处置</h3>' + treatments + '</section>'
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
        body = self._nav(player_id) + '<h2>导师教学</h2><p>课程、提示与师评均来自固定公开契约。</p>'+rendered
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
