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

from xuanyi_npc.agents import (
    DeepSeekAdapterConfig,
    DeepSeekChatAdapter,
    DeepSeekConfigurationError,
    DeterministicCooperativeNPC,
    GameNPCAgent,
)
from xuanyi_npc.application.clinic import ClinicActionInput, ClinicContributionInput, ClinicError, ClinicService
from xuanyi_npc.domain.cooperation import PlayerContributionType
from xuanyi_npc.domain.cooperative_planning import (
    AgentGoalStatus,
    AgentGoalType,
    AgentPlanStatus,
    PlanEvaluationOutcome,
    PlanStepStatus,
)
from xuanyi_npc.application.multicase import CaseCatalog, SystemEpisodeClock
from xuanyi_npc.application.game_npc_memory import (
    GameNPCMemoryProjectionPolicy,
    GameNPCMemoryRetrievalService,
)
from xuanyi_npc.application.memory_coordination import V1MemoryCoordinator
from xuanyi_npc.application.memory_retrieval import BasicCosineMemoryRetriever, MemoryIndexService
from xuanyi_npc.application.reflection import ReflectionProposalGenerator
from xuanyi_npc.application.reflection_lifecycle import ReflectionLifecycleService
from xuanyi_npc.application.reflection_memory import ReflectionMemoryConsolidationService
from xuanyi_npc.memory import (
    BGE_M3_VERIFIED_MANIFEST_SHA256,
    BgeM3LocalEmbeddingAdapter,
    BgeM3LocalEmbeddingConfig,
    MemoryRetrievalConfig,
    bge_m3_embedding_space_id,
)
from xuanyi_npc.resources.runtime import materialized_clinic_resources
from xuanyi_npc.resources.runtime import read_runtime_text
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository, StateNotFoundError
from xuanyi_npc.application.player_experience import propose_investigation
from xuanyi_npc.application.case_dialogue import case_participants


STYLE = """
:root{color-scheme:light;--ink:#26352f;--jade:#426b5a;--paper:#f6f0df;--card:#fffaf0;--line:#cbbf9e}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 system-ui,sans-serif}
header,main{max-width:980px;margin:auto;padding:1rem}header{border-bottom:1px solid var(--line)}
h1,h2{font-family:serif;color:#294f40}nav a,a{color:var(--jade)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:1rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem;margin:.7rem 0}.case-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.partner{border-left:5px solid var(--jade)}
button{background:var(--jade);color:white;border:0;border-radius:6px;padding:.55rem .9rem}input,select,textarea{max-width:100%;width:100%;padding:.45rem;border:1px solid var(--line)}
.notice{border-left:4px solid #9a7338;padding:.6rem;background:#fff8dc}.error{color:#8b2d2d}small{color:#58665f}
.case-workspace{display:grid;grid-template-columns:minmax(220px,1fr) minmax(300px,1.4fr) minmax(240px,1fr);gap:1rem;align-items:start}.progress-done{color:var(--jade)}
.chat{max-width:820px;height:min(60vh,560px);min-height:400px;margin:1rem auto;display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:16px;background:rgba(255,255,255,.42)}
.chat>p{margin:.55rem .8rem .25rem}.chat-log{flex:1;min-height:0;overflow-y:auto;padding:.25rem .75rem .45rem;scrollbar-gutter:stable}
.bubble{width:fit-content;max-width:70%;padding:.38rem .72rem;border-radius:12px;margin:.28rem 0;background:#fff;border:1px solid var(--line);overflow-wrap:anywhere}
.bubble strong{font-size:.82rem}.bubble p{margin:.12rem 0 0;line-height:1.42}.bubble.player{margin-left:auto;background:#dff2e8}.bubble.case_character{margin-right:auto}
.bubble.system,.bubble.clue,.bubble.rejection{width:auto;max-width:70%;margin:.3rem auto;padding:.3rem .65rem;text-align:center;border-radius:8px;background:#fff5d7}.bubble.rejection{background:#fff0eb}
.composer{position:sticky;z-index:2;bottom:0;display:flex;gap:.5rem;align-items:center;margin:0;padding:.55rem .75rem;background:var(--paper);border-top:1px solid var(--line);box-shadow:0 -5px 14px rgba(38,32,22,.06)}.composer input[name=message]{flex:1;min-width:0;margin:0}.composer button{width:auto;flex:0 0 auto;margin:0;white-space:nowrap}.drawers{max-width:900px;margin:auto}.private-mark{color:#7656a8;font-size:.78rem}
@media(max-width:640px){.chat{height:55dvh;min-height:390px;margin:.55rem -.35rem;border-radius:12px}.chat-log{padding:.2rem .45rem .35rem}.bubble{max-width:72%;padding:.32rem .6rem;margin:.22rem 0}.bubble.system,.bubble.clue,.bubble.rejection{max-width:72%;margin:.24rem auto}.composer{padding:.45rem}.composer button{padding:.65rem .8rem}}
@media(max-width:700px){.case-grid,.case-workspace{grid-template-columns:1fr}header,main{padding:.75rem}.card{overflow-wrap:anywhere}}
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(title)} · 异闻行录</title><style>{STYLE}</style></head><body><header><h1>异闻行录 · 志怪异案</h1><p class="notice">全部异案、人物与术法均为架空游戏内容，不对应现实事件或现实医疗建议。</p></header><main>{body}</main></body></html>"""
    return document.encode("utf-8")


GOAL_TYPE_LABELS = {
    AgentGoalType.RESOLVE_CASE: "完成异案",
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


def build_clinic_service(
    state_dir: Path,
    resources,
    *,
    game_npc_agent,
    store=None,
    memory_service=None,
    memory_coordinator=None,
    memory_index_service=None,
    memory_mode="disabled",
    reflection_service=None,
) -> ClinicService:
    service = ClinicService(
        store=store or JsonStateStore(state_dir), base_catalog=CaseCatalog(resources.case_dir),
        campaign_path=resources.campaign_rules, clock=SystemEpisodeClock(),
        game_npc_agent=game_npc_agent,
        cooperative_memory_service=memory_service,
        memory_coordinator=memory_coordinator,
        memory_index_service=memory_index_service,
        memory_mode=memory_mode,
        reflection_service=reflection_service,
    )
    if memory_mode == "semantic":
        for session in service.store.list_case_sessions():
            case = service.base_catalog.get(session.case_id)
            if case is None:
                raise RuntimeError("committed memory source case is unavailable")
            commit = memory_coordinator.reconcile_committed_session(
                case=case,
                player_id=session.player_id,
                session_id=session.session_id,
            )
            if commit.status.value != "complete":
                raise RuntimeError(
                    f"memory reconciliation pending: {commit.error_code}"
                )
        for player in service.store.list_players():
            memory_index_service.index_player(player_id=player.player_id)
            if reflection_service is not None:
                reflection_service.reconcile_pending_indexes(
                    player_id=player.player_id,
                    embedding_space_id=memory_index_service.adapter.embedding_space_id,
                    embedding_dimension=memory_index_service.adapter.dimension,
                )
    return service


def build_game_npc(args):
    """Build the explicitly selected production NPC mode and its owned adapter."""

    if args.npc_mode == "offline":
        return DeterministicCooperativeNPC(), None
    if not args.confirm_paid_agent:
        raise DeepSeekConfigurationError("LLM NPC requires explicit paid-run authorization")
    try:
        budget = Decimal(args.agent_budget_cny or "")
    except InvalidOperation:
        raise DeepSeekConfigurationError("LLM NPC budget is invalid") from None
    if budget <= 0:
        raise DeepSeekConfigurationError("LLM NPC budget must be positive")
    base = DeepSeekAdapterConfig.from_env()
    config = DeepSeekAdapterConfig.model_validate({
        **base.model_dump(),
        "max_output_tokens": max(base.max_output_tokens, 2048),
        "pilot_max_cost_cny": budget,
    })
    adapter = DeepSeekChatAdapter(config)
    try:
        adapter.require_configured_model()
    except Exception:
        adapter.close()
        raise
    return GameNPCAgent(adapter), adapter


def build_production_memory(args, *, state_dir: Path, store: JsonStateStore):
    """Build one shared, persistent semantic-memory pipeline or fail explicitly."""

    mode = args.memory_mode or ("semantic" if args.npc_mode == "llm" else "disabled")
    if mode == "disabled":
        return mode, None, None, None, None
    root = Path(__file__).resolve().parents[3]
    model_dir = args.memory_model_dir or root / "runtime_models" / "bge-m3-142964af7e05"
    manifest = args.memory_model_manifest or root / "tools" / "experiments" / "model_manifests" / "bge_m3_142964af7e05_dense_fp32_verified.json"
    space_id = bge_m3_embedding_space_id(
        device=args.memory_device,
        max_input_length=args.memory_max_input_length,
    )
    adapter = BgeM3LocalEmbeddingAdapter(config=BgeM3LocalEmbeddingConfig(
        model_directory=model_dir,
        manifest_path=manifest,
        manifest_sha256=BGE_M3_VERIFIED_MANIFEST_SHA256,
        device=args.memory_device,
        max_input_length=args.memory_max_input_length,
        batch_size=args.memory_batch_size,
        embedding_space_id=space_id,
    ))
    adapter.load()
    repository = SQLiteMemoryRepository(state_dir / "memories.sqlite3")
    repository.initialize()
    index_service = MemoryIndexService(repository=repository, adapter=adapter)
    retrieval = GameNPCMemoryRetrievalService(
        retriever=BasicCosineMemoryRetriever(repository=repository, adapter=adapter),
        retrieval_config=MemoryRetrievalConfig(
            top_k=8,
            min_similarity=0.35,
            embedding_space_id=space_id,
            query_template_version="memory_query_v1",
        ),
        projection_policy=GameNPCMemoryProjectionPolicy(repository=repository),
    )
    coordinator = V1MemoryCoordinator(state_store=store, memory_repository=repository)
    return mode, retrieval, coordinator, index_service, repository


def build_production_reflection(
    args,
    *,
    game_npc_adapter,
    memory_mode: str,
    memory_repository,
    memory_index_service,
):
    """Build Reflection only when the real LLM and semantic Memory are explicit."""

    if args.npc_mode != "llm":
        return None
    if memory_mode != "semantic":
        return None
    if game_npc_adapter is None:
        raise DeepSeekConfigurationError("Reflection requires the configured Game NPC LLM adapter")
    if memory_repository is None or memory_index_service is None:
        raise RuntimeError("Reflection requires production semantic memory")
    return ReflectionLifecycleService(
        generator=ReflectionProposalGenerator(game_npc_adapter),
        consolidation_service=ReflectionMemoryConsolidationService(
            repository=memory_repository,
            index_service=memory_index_service,
        ),
        receipt_repository=memory_repository,
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
            raise ClinicError("player_required", "请选择或创建玩家档案。")
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
            elif parsed.path == "/cases":
                self._cases(self._player_id(query), query.get("case_id"), query.get("session_id"))
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
            self._error(500, "异案调查入口暂时无法处理请求，已保留最后一次成功进度。")

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
                location = "/cases?" + urlencode({"player_id": player_id})
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
            elif path == "/cases/chat":
                player_id=self._player_id(form);case_id=form.get("case_id","");session_id=form.get("session_id","")
                self.server.clinic_service.case_chat_message(player_id,case_id,session_id,token,form.get("message", ""))
                values={"player_id":player_id,"case_id":case_id,"session_id":session_id}
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
                result = self.server.clinic_service.submit_case_action(request)
                location = "/cases?" + urlencode({"player_id": request.player_id, "case_id": request.case_id, "session_id": request.session_id})
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
                "llm_attempts":str(result.decision.llm_attempts),
                "llm_used_fallback":"1" if result.decision.used_fallback else "",
                "llm_repair_kind":result.decision.repair_kind or "",
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
                "memory_commit_status":result.memory_commit_status or "",
                "memory_commit_error_code":result.memory_commit_error_code or "",
                "memory_written_ids":",".join(result.written_memory_ids),
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
                "reflection_index_status":result.reflection_index_status.value if result.reflection_index_status else "",
                "reflection_error_code":result.reflection_error_code or "",
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
        return f'<nav><a href="/clinic?{q}">调查主页</a> · <a href="/cases?{q}">调查异案</a></nav>'

    def _welcome(self, player_id):
        player=self.server.clinic_service.home(player_id).player_summary
        body=f'''<h2>初次同行</h2><section class="card"><h3>系统旁白</h3><p>你将与一名游侠型自主 NPC 结伴，调查人与契、物、炁息交缠而成的古风志怪异案。你可以提供线索、质疑、建议和判断；同行 NPC 会自主规划并推进调查，重大或不可逆处置仍需要你的明确确认。</p></section><section class="card partner"><h3>调查搭档</h3><p>各地已有数桩异事待查。我们先核对公开证据，再协商判断；我会自行决定下一步准备调查什么，真正的行动结果仍由案件规则裁定。</p></section><form method="post" action="/welcome/complete"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>与搭档同行，前往选案</button></form>'''
        body=f'<p>调查者：{_esc(player.display_name)}</p>'+body
        self._send(200,_page("初次同行",body))

    def _start(self):
        players = self.server.clinic_service.list_players()
        restored = "".join(f'<li><a href="/clinic?player_id={_esc(item.player_id)}">{_esc(item.display_name)}</a></li>' for item in players) or "<li>尚无调查档案</li>"
        body = f"""<h2>进入志怪异案调查</h2><p>你将与一名自主 NPC 组成调查搭档，共同调查异事。</p><div class="grid"><section class="card"><h3>创建玩家档案</h3><form method="post" action="/players"><label>玩家名 <input name="display_name" maxlength="40" required></label><input type="hidden" name="operation_id" value="{self._token()}"><button>创建并进入</button></form></section><section class="card"><h3>恢复调查档案</h3><ul>{restored}</ul></section></div><p>无需输入工具名、JSON、Session ID 或内部规则；页面会把自然语言选择转换为严格应用命令。</p>"""
        self._send(200, _page("开始", body))

    def _home(self, player_id):
        view = self.server.clinic_service.home(player_id)
        labels = {"not_started": "尚未开始", "active": "进行中", "completed": "已完成"}
        cases = "".join(f"<li>{_esc(item.title)}：{_esc(labels.get(item.status, '状态已更新'))}</li>" for item in view.visible_cases)
        body = f'''{self._nav(player_id)}<h2>{_esc(view.player_summary.display_name)}的调查档案</h2><p>你与自主 NPC 组成调查搭档，共同处理志怪异案。</p><section class="card"><h3>可调查异案</h3><ul>{cases}</ul><p><a href="/cases?player_id={_esc(player_id)}">进入异案大厅</a></p></section>'''
        self._send(200, _page("调查主页", body))

    def _cases(self, player_id, case_id=None, session_id=None):
        service = self.server.clinic_service._service(player_id)
        if not case_id:
            view = self.server.clinic_service.home(player_id)
            labels={"not_started":"未开始","active":"调查中","completed":"已完成"}
            cards = "".join(f'<section class="card"><h3>{_esc(item.title)}</h3><p>{_esc(item.synopsis)}</p><p><strong>难度：</strong>异象案</p><p class="status">状态：{_esc(labels.get(item.status,item.status))}</p>{"<p class=\"recommended\">调查建议</p>" if item.recommended else ""}<form method="post" action="/cases/start"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(item.case_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>{"继续调查" if item.status=="active" else "接案"}</button></form></section>' for item in view.visible_cases)
            self._send(200, _page("异案大厅", self._nav(player_id) + '<h2>志怪异案选案大厅</h2><p>同行 NPC 的调查建议仅供参考，六案均可选择。</p><div class="case-grid">' + cards + "</div>"))
            return
        if not session_id:
            raise ClinicError("session_required", "缺少案件进度。")
        result,guide,guide_stages,current_stage,dialogue,abilities = self.server.clinic_service.case_experience(player_id, case_id, session_id)
        observation = result.observation
        if observation is None:
            raise ClinicError("case_unavailable", "案件公开状态不可用。")
        clues = "".join(f"<li>{_esc(item.description)}</li>" for item in observation.discovered_clues) or "<li>尚未发现</li>"
        actions = "".join(f'<form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="investigation"><input type="hidden" name="selection_id" value="{_esc(item.investigation_id)}"><button>{_esc(item.public_description)}</button></form>' for item in observation.available_investigations)
        diagnoses = "".join(f'<option value="{_esc(item.diagnosis_id)}">{_esc(item.public_description)}</option>' for item in observation.diagnosis_candidates)
        notice=self._query().get("notice","")
        body = f'''{self._nav(player_id)}<h2>{_esc(observation.title)}</h2><p>{_esc(observation.synopsis)}</p>{f'<p class="notice">{_esc(notice)}</p>' if notice else ''}<section class="card"><h3>自然语言调查</h3><form method="post" action="/cases/natural"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><textarea name="text" rows="3" required placeholder="例如：询问乘客虚弱出现的先后顺序"></textarea><button>执行调查提案</button></form><small>文本先转换为行动提案，案件规则会再次校验能力、熟练度与前置证据。</small></section><section class="card"><h3>线索簿</h3><ul>{clues}</ul></section><details class="card"><summary>无障碍／模型不可用时的降级调查入口</summary>{actions or '<p>暂无</p>'}</details>'''
        stage_html="".join(f'<li class="{"progress-done" if done else ""}">{"✓" if done else "○"} {_esc(stage.title)}<p>{_esc(stage.public_purpose)}</p><small>参考问法（不会自动执行）：{_esc("；".join(stage.suggested_questions))}</small></li>' for stage,done in guide_stages)
        embedded=f'''<div class="case-workspace"><section class="card"><h3>调查提纲</h3><ul>{stage_html}</ul></section><section class="card"><h3>案中人物对话</h3><p>在下方输入框中说明交谈对象和要核对的事实。</p></section></div>'''
        body=body.replace(f'<h2>{_esc(observation.title)}</h2>',f'<h2>{_esc(observation.title)}</h2>'+embedded)
        participants=case_participants(case_id);names={x.participant_id:x.display_name for x in participants}|{"player":"你"}
        empty_dialogue='<p class="notice">尚未开始交谈。默认交谈对象为当前案中人物；与调查搭档协作请使用上方协作框。</p>'
        bubbles="".join(f'<article class="bubble {_esc(msg.message_type)}"><strong>{_esc(names.get(msg.speaker_id,"系统"))}</strong><p>{_esc(msg.public_text)}</p></article>' for msg in dialogue.recent_messages) or empty_dialogue
        options=''.join(f'<option value="@{_esc(x.display_name)} "></option>' for x in participants)
        current=names.get(dialogue.current_target,"请选择")
        chat=f'''<section class="chat"><p>当前交谈对象：<strong>{_esc(current)}</strong></p><div class="chat-log">{bubbles}</div><form class="composer" method="post" action="/cases/chat"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><textarea name="message" rows="3" list="case-recipients" required placeholder="与案中人物交谈；与调查搭档协作请使用上方协作框"></textarea><datalist id="case-recipients">{options}</datalist><button>发送</button></form></section>'''
        chat=chat.replace('<textarea name="message" rows="3" list="case-recipients"','<input name="message" list="case-recipients"').replace('</textarea><datalist','><datalist')
        drawers=f'''<section class="drawers"><details class="card"><summary>调查提纲与进度</summary><ul>{stage_html}</ul></details><details class="card"><summary>已发现线索</summary><ul>{clues}</ul></details><details class="card"><summary>案中人物</summary><ul>{''.join(f'<li>{_esc(x.display_name)}</li>' for x in participants)}</ul></details><details class="card"><summary>辨证与处置</summary><p>达到规则要求后，下方将显示可提交入口。</p></details></section>'''
        query=self._query();npc_reply=query.get("npc_reply","");disposition=query.get("suggestion_disposition","")
        suggestion_explanation=query.get("suggestion_explanation","");npc_action=query.get("npc_action","")
        environment_feedback=query.get("environment_feedback","");confirmation_id=query.get("confirmation_id","")
        decision_id=query.get("decision_id","");authority_mode=query.get("authority_mode","")
        npc_tool_public=query.get("npc_tool_public","");npc_rationale=query.get("npc_rationale","")
        runtime_kind=query.get("runtime_kind","");debug_tool_name=query.get("debug_tool_name","")
        llm_attempts=query.get("llm_attempts","");llm_used_fallback=query.get("llm_used_fallback","")=="1"
        llm_repair_kind=query.get("llm_repair_kind","")
        if runtime_kind=="deterministic_fallback":
            npc_runtime_notice="离线确定性模式：本轮未调用语言模型。"
        elif llm_used_fallback:
            npc_runtime_notice="LLM 本轮未能产生有效决策，NPC 已安全停步，未执行工具。"
        elif llm_repair_kind:
            npc_runtime_notice="LLM 输出经结构化修复后通过验证。"
        elif runtime_kind=="real_llm":
            npc_runtime_notice="LLM Agent 已完成本轮受约束决策。"
        else:
            npc_runtime_notice="当前 NPC 运行状态未标识。"
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
            f'<p>memory commit status：{_esc(query.get("memory_commit_status","") or "none")}</p>'
            f'<p>memory commit error：{_esc(query.get("memory_commit_error_code","") or "none")}</p>'
            f'<p>written memory IDs：{_esc(query.get("memory_written_ids",""))}</p>'
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
            f'<p>index status：{_esc(query.get("reflection_index_status","") or "none")}</p>'
            f'<p>reflection error：{_esc(query.get("reflection_error_code","") or "none")}</p>'
        )
        manual_mode = False
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
            cooperative_result=f'''<section class="card"><h3>NPC 协作结果</h3><p class="notice"><strong>运行状态：</strong>{_esc(npc_runtime_notice)}</p>{f'<p><strong>建议评价：</strong>{_esc(disposition)} · {_esc(suggestion_explanation)}</p>' if disposition else ''}{f'<p><strong>NPC 回应：</strong>{_esc(npc_reply)}</p>' if npc_reply else ''}{memory_effect_html}{reflection_learning_html}{f'<p><strong>采取行动：</strong>{_esc(npc_tool_public)}</p>' if npc_tool_public else ''}{f'<p><strong>行动依据：</strong>{_esc(npc_rationale)}</p>' if npc_rationale else ''}{f'<p><strong>环境反馈：</strong>{_esc(environment_feedback)}</p>' if environment_feedback else ''}<details><summary>开发信息</summary><p>runtime：{_esc(runtime_kind or 'unknown')}</p><p>LLM attempts：{_esc(llm_attempts or 'none')}</p><p>repair：{_esc(llm_repair_kind or 'none')}</p><p>capability：{_esc(npc_action)}</p><p>raw tool：{_esc(debug_tool_name or 'none')}</p>{memory_debug_html}{reflection_debug_html}</details></section>'''
        confirmation=""
        if confirmation_id and decision_id:
            label="同意诊断提议" if authority_mode=="proposal_only" else "确认高风险处置"
            hidden=f'<input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="confirmation_id" value="{_esc(confirmation_id)}"><input type="hidden" name="decision_id" value="{_esc(decision_id)}">'
            confirmation=f'''<section class="card notice"><h3>需要玩家协商</h3><p>该行动尚未执行。NPC 会在你回应后依据最新案件状态再次判断。</p><form method="post" action="/cases/cooperate/respond">{hidden}<input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="response" value="approve"><button>{label}</button></form><form method="post" action="/cases/cooperate/respond">{hidden}<input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="response" value="reject"><button>拒绝并要求替代方案</button></form></section>'''
        configured_runtime=getattr(self.server.clinic_service.game_npc_agent,"runtime_kind",None)
        memory_mode=self.server.clinic_service.memory_mode
        configured_notice=(
            f"当前调查搭档：LLM GameNPCAgent；长期 Memory {'已启用语义检索' if memory_mode == 'semantic' else '已禁用'}；Reflection {'已启用' if self.server.clinic_service.reflection_service is not None else '未启用'}。"
            if getattr(configured_runtime,"value",None)=="real_llm"
            else f"当前调查搭档：离线确定性 NPC（未调用语言模型）；长期 Memory {'已启用语义检索' if memory_mode == 'semantic' else '已禁用'}。"
        )
        cooperative_form=f'''<section class="card"><h3>与调查搭档协作</h3><p class="notice">{_esc(configured_notice)}</p><form method="post" action="/cases/cooperate"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><select name="contribution_type"><option value="suggestion">建议调查方向</option><option value="hypothesis">提出假设</option><option value="challenge">质疑 NPC</option><option value="evidence_interpretation">解释证据</option><option value="question">询问判断</option></select><textarea name="text" rows="3" required placeholder="表达你的假设或建议；NPC 会独立评价并决定具体行动。"></textarea><button>与 NPC 讨论并推进</button></form><small>你的输入是建议或判断，不会由页面直接转换为工具调用。</small></section>'''
        body=f'''{self._nav(player_id)}<h2>{_esc(observation.title)}</h2><p>{_esc(observation.synopsis)}</p>{cooperative_form}{planning_card}{cooperative_result}{confirmation}{chat}{drawers}'''
        if observation.can_submit_diagnosis:
            evidence = ",".join(item.clue_id for item in observation.discovered_clues)
            body += f'<details class="card"><summary>Manual / baseline：直接提交辨证</summary><form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="diagnosis"><input type="hidden" name="evidence_clue_ids" value="{_esc(evidence)}"><select name="selection_id">{diagnoses}</select><button>提交辨证</button></form></details>'
        treatments = "".join(f'<form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="treatment"><input type="hidden" name="selection_id" value="{_esc(item.treatment_id)}"><button>{_esc(item.public_description)}</button></form>' for item in observation.available_treatments)
        if treatments:
            body += '<details class="card"><summary>Manual / baseline：直接选择处置</summary>' + treatments + '</details>'
        self._send(200, _page("异案", body))

    def _error(self, status, message):
        self._send(status, _page("安全错误", f'<h2 class="error">无法完成</h2><p>{_esc(message)}</p><p><a href="/">返回开始页</a></p>'))


def build_parser():
    parser = argparse.ArgumentParser(prog="yiwen-xinglu", description="启动《异闻行录》本地异案调查入口（仅绑定 127.0.0.1）。")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--host", default="127.0.0.1", choices=("127.0.0.1",))
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--npc-mode",choices=("llm","offline"),default="llm")
    parser.add_argument("--memory-mode", choices=("disabled", "semantic"))
    parser.add_argument("--memory-model-dir", type=Path)
    parser.add_argument("--memory-model-manifest", type=Path)
    parser.add_argument("--memory-device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--memory-max-input-length", type=int, default=512)
    parser.add_argument("--memory-batch-size", type=int, default=8)
    parser.add_argument("--confirm-paid-agent",action="store_true")
    parser.add_argument("--agent-budget-cny")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.state_dir is None or not args.state_dir.is_dir():
        print("启动失败：存档目录必须已经存在。", file=sys.stderr)
        return 2
    try:
        game_npc_agent, game_npc_adapter = build_game_npc(args)
    except Exception as exc:
        code = getattr(exc, "code", type(exc).__name__)
        print(f"启动失败：LLM 调查搭档不可用（{code}）。", file=sys.stderr)
        return 2
    store = JsonStateStore(args.state_dir)
    try:
        memory_mode, memory_service, memory_coordinator, memory_index_service, memory_repository = (
            build_production_memory(args, state_dir=args.state_dir, store=store)
        )
    except Exception as exc:
        if game_npc_adapter is not None:
            game_npc_adapter.close()
        code = getattr(exc, "code", type(exc).__name__)
        print(f"启动失败：长期记忆不可用（{code}）。", file=sys.stderr)
        return 2
    try:
        reflection_service = build_production_reflection(
            args,
            game_npc_adapter=game_npc_adapter,
            memory_mode=memory_mode,
            memory_repository=memory_repository,
            memory_index_service=memory_index_service,
        )
    except Exception as exc:
        if game_npc_adapter is not None:
            game_npc_adapter.close()
        code = getattr(exc, "code", type(exc).__name__)
        print(f"启动失败：Reflection 不可用（{code}）。", file=sys.stderr)
        return 2
    try:
        with materialized_clinic_resources() as resources:
            service = build_clinic_service(
                args.state_dir, resources, game_npc_agent=game_npc_agent,
                store=store,
                memory_service=memory_service,
                memory_coordinator=memory_coordinator,
                memory_index_service=memory_index_service,
                memory_mode=memory_mode,
                reflection_service=reflection_service,
            )
            server = ClinicHTTPServer((args.host, args.port), service)
            host, port = server.server_address
            print(f"《异闻行录》已启动：http://{host}:{port}", flush=True)
            print(f"NPC mode={args.npc_mode}", flush=True)
            print(f"Memory mode={memory_mode}", flush=True)
            print(f"Reflection mode={'enabled' if reflection_service is not None else 'disabled'}", flush=True)
            try:
                server.serve_forever(poll_interval=0.1)
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
    finally:
        if game_npc_adapter is not None:
            game_npc_adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
