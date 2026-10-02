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
.session-nav{display:flex;align-items:center;justify-content:space-between;gap:1rem}.session-nav-links{display:flex;gap:.45rem;align-items:center}.logout-form{margin:0}.logout-button{padding:0;border:0;background:transparent;color:var(--jade);text-decoration:underline;cursor:pointer;font:inherit}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem;margin:.7rem 0}.case-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1rem}.case-card{display:flex;min-height:100%;flex-direction:column}.case-card h3{margin:.25rem 0 .65rem}.case-synopsis{flex:1}.case-card-active{border:2px solid var(--jade);box-shadow:0 5px 16px rgba(38,53,47,.12)}.case-card-completed{background:#f3f0e7}.case-meta{display:flex;gap:.45rem;align-items:center;flex-wrap:wrap;margin:.7rem 0}.status-badge,.case-type,.recommended{display:inline-block;border-radius:999px;padding:.18rem .58rem;font-size:.82rem}.status-badge{background:#ece7d8;color:#4f584f}.case-card-active .status-badge{background:var(--jade);color:white}.case-card-completed .status-badge{background:#dfe7df;color:#385047}.case-type{background:#f5ecd2;color:#6e552d}.recommended{background:#fff1bd;color:#755815}.case-footer{margin-top:auto;padding-top:.45rem}.case-footer form{margin:0}.case-footer button{margin:0}.case-footer button[disabled]{background:#aaa89e;color:#f4f1e8;cursor:not-allowed}
.partner{border-left:5px solid var(--jade)}
button{background:var(--jade);color:white;border:0;border-radius:6px;padding:.55rem .9rem}input,select,textarea{max-width:100%;width:100%;padding:.45rem;border:1px solid var(--line)}
.notice{border-left:4px solid #9a7338;padding:.6rem;background:#fff8dc}.error{color:#8b2d2d}small{color:#58665f}
.case-workspace{display:grid;grid-template-columns:minmax(220px,1fr) minmax(300px,1.4fr) minmax(240px,1fr);gap:1rem;align-items:start}.progress-done{color:var(--jade)}
.chat{max-width:820px;height:min(60vh,560px);min-height:400px;margin:1rem auto;display:flex;flex-direction:column;overflow:hidden;border:1px solid var(--line);border-radius:16px;background:rgba(255,255,255,.42)}
.chat>p{margin:.55rem .8rem .25rem}.chat-log{flex:1;min-height:0;overflow-y:auto;padding:.25rem .75rem .45rem;scrollbar-gutter:stable}
.bubble{width:fit-content;max-width:70%;padding:.38rem .72rem;border-radius:12px;margin:.28rem 0;background:#fff;border:1px solid var(--line);overflow-wrap:anywhere}
.bubble strong{font-size:.82rem}.bubble p{margin:.12rem 0 0;line-height:1.42}.bubble.player{margin-left:auto;background:#dff2e8}.bubble.case_character{margin-right:auto}
.bubble.system,.bubble.clue,.bubble.rejection{width:auto;max-width:70%;margin:.3rem auto;padding:.3rem .65rem;text-align:center;border-radius:8px;background:#fff5d7}.bubble.rejection{background:#fff0eb}
.composer{position:sticky;z-index:2;bottom:0;display:flex;gap:.5rem;align-items:center;margin:0;padding:.55rem .75rem;background:var(--paper);border-top:1px solid var(--line);box-shadow:0 -5px 14px rgba(38,32,22,.06)}.composer input[name=message]{flex:1;min-width:0;margin:0}.composer button{width:auto;flex:0 0 auto;margin:0;white-space:nowrap}.drawers{max-width:900px;margin:auto}.private-mark{color:#7656a8;font-size:.78rem}
.cooperative-turn+.cooperative-turn{margin-top:1.25rem;padding-top:1.25rem;border-top:1px dashed var(--line)}
.cooperative-card{overflow:hidden}.cooperative-log{min-height:220px;max-height:62vh;overflow-y:auto;scroll-margin-top:1rem;margin:.8rem 0 0;padding:.8rem 1rem;border:1px solid var(--line);border-radius:10px;background:#f8f4e9}.cooperative-empty{min-height:188px;display:grid;place-items:center;text-align:center;color:#8a867c}.cooperative-empty p{margin:0}.cooperative-composer{margin-top:.7rem}.cooperative-composer select{margin:0 0 .5rem}.cooperative-input-row{display:flex;gap:.6rem;align-items:flex-end}.cooperative-input-row textarea{flex:1;min-width:0;margin:0}.cooperative-input-row button{width:auto;flex:0 0 auto;margin:0;white-space:nowrap}.cooperative-hint{display:block;margin-top:.55rem}.turn-dialogue{padding:.35rem 0}.turn-message{display:flex;gap:.65rem;align-items:flex-start;margin:.9rem 0}.turn-message-player{justify-content:flex-end}.turn-avatar{width:42px;height:42px;flex:0 0 42px;display:grid;place-items:center;border-radius:10px;background:#d7c7a2;color:#3d3527;font-weight:700;box-shadow:0 1px 2px rgba(38,32,22,.12)}.turn-avatar-button{padding:0;border:0;cursor:pointer}.turn-avatar-button:hover{filter:brightness(.96)}.turn-avatar-button:focus-visible{outline:3px solid #7ea695;outline-offset:2px}.turn-message-player .turn-avatar{background:var(--jade);color:white}.turn-message-body{max-width:72%}.turn-speaker{display:block;font-size:.78rem;color:#66716c;margin:0 .35rem .2rem}.turn-message-player .turn-speaker{text-align:right}.turn-bubble{position:relative;margin:0;padding:.7rem .9rem;border-radius:9px;background:#fff;border:1px solid var(--line);line-height:1.55;overflow-wrap:anywhere}.turn-message-partner .turn-bubble:before{content:"";position:absolute;left:-7px;top:12px;border-width:6px 7px 6px 0;border-style:solid;border-color:transparent var(--line) transparent transparent}.turn-message-player .turn-bubble{background:#cfe8d8;border-color:#a8cbb6}.turn-message-player .turn-bubble:after{content:"";position:absolute;right:-7px;top:12px;border-width:6px 0 6px 7px;border-style:solid;border-color:transparent transparent transparent #a8cbb6}.decision-chip{display:inline-block;padding:.16rem .55rem;border-radius:999px;background:#edf4ef;color:#315848;font-weight:700}.turn-action{padding:.65rem 0}.discovery{border-left:5px solid #9a7338;background:#fff3c9;padding:.8rem 1rem;margin:1rem 0}.discovery h4{margin:0 0 .35rem;color:#6f4d19}.discovery p{margin:0}.next-step{border-left:4px solid var(--jade);background:#edf4ef;padding:.7rem}.plan-details{margin-top:.8rem}
.partner-assessment-modal{position:fixed;z-index:20;inset:0;display:grid;place-items:center;padding:1rem;background:rgba(25,35,30,.42)}.partner-assessment-modal[hidden]{display:none}.partner-assessment-dialog{position:relative;width:min(560px,calc(100vw - 2rem));max-height:min(76vh,620px);overflow:auto;padding:1.25rem 1.35rem;border:1px solid var(--line);border-radius:14px;background:var(--card);box-shadow:0 18px 50px rgba(20,27,24,.25)}.partner-assessment-dialog h3{margin:.1rem 2.5rem 1rem 0}.partner-assessment-body{color:#46564f}.partner-assessment-body .decision-chip{margin-right:.55rem}.partner-assessment-body p{margin:.85rem 0 0}.partner-assessment-close{position:absolute;right:.7rem;top:.6rem;width:2.2rem;height:2.2rem;padding:0;border-radius:50%;font-size:1.35rem;line-height:1;background:transparent;color:var(--ink)}.partner-assessment-close:hover{background:#eee6d4}
.save-list{list-style:none;margin:.6rem 0 0;padding:0;display:grid;gap:.55rem}.save-link{display:block;padding:.7rem .8rem;border:1px solid var(--line);border-radius:8px;background:#fffdf7;text-decoration:none}.save-link:hover{border-color:var(--jade);background:#f7fbf7}.save-link strong,.save-link span{display:block}.save-link span{margin-top:.15rem;color:#66716c;font-size:.9rem}
.cooperative-pending{margin-top:.7rem;padding:.65rem .8rem;border-left:4px solid var(--jade);background:#edf4ef}.cooperative-pending:after{content:"";display:inline-block;width:.8em;height:.8em;margin-left:.55rem;border:2px solid #9ab5aa;border-top-color:var(--jade);border-radius:50%;animation:waiting-spin .8s linear infinite}@keyframes waiting-spin{to{transform:rotate(360deg)}}
@media(max-width:640px){.chat{height:55dvh;min-height:390px;margin:.55rem -.35rem;border-radius:12px}.chat-log{padding:.2rem .45rem .35rem}.bubble{max-width:72%;padding:.32rem .6rem;margin:.22rem 0}.bubble.system,.bubble.clue,.bubble.rejection{max-width:72%;margin:.24rem auto}.composer{padding:.45rem}.composer button{padding:.65rem .8rem}.cooperative-log{min-height:190px;margin-left:-.35rem;margin-right:-.35rem;padding:.6rem}.cooperative-empty{min-height:158px}.cooperative-input-row{display:block}.cooperative-input-row button{width:100%;margin-top:.5rem}.turn-avatar{width:36px;height:36px;flex-basis:36px}.turn-message-body{max-width:82%}}
@media(max-width:700px){.case-grid,.case-workspace{grid-template-columns:1fr}header,main{padding:.75rem}.card{overflow-wrap:anywhere}}
"""


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


_INTERNAL_ID_PATTERN = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")


def _player_copy(value: object, *, action_label: str = "") -> str:
    """Replace implementation identifiers and system jargon in player-facing text."""

    replacement = str(action_label).strip().rstrip("。！？；，,.!?;") or "当前调查行动"
    replacement = replacement.replace("公开痕迹", "现场痕迹")
    text = str(value)
    text = re.sub(
        rf"公开调查项\s+{_INTERNAL_ID_PATTERN.pattern}\s*",
        f"调查方向“{replacement}”",
        text,
    )
    text = _INTERNAL_ID_PATTERN.sub(replacement, text)
    text = text.replace("当前公开调查动作只覆盖", "目前能够调查的方向包括")
    text = text.replace("公开调查动作", "调查方向")
    text = re.sub(
        r"没有针对([^，；。]+)的可用调查入口",
        r"暂时没有直接调查\1的办法",
        text,
    )
    text = re.sub(
        r"([^，；。]+)也不在已公开的异常线索范围内",
        r"现有线索暂未指向\1",
        text,
    )
    return (
        text.replace("公开调查项", "调查方向")
        .replace("公开痕迹", "现场痕迹")
        .replace("。；", "；")
        .replace(".；", "；")
    )


def _page(title: str, body: str) -> bytes:
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_esc(title)} · 异闻行录</title><style>{STYLE}</style></head><body><header><h1>异闻行录 · 志怪异案</h1><p class="notice">全部异案、人物与术法均为架空游戏内容，不对应现实事件或现实医疗建议。</p></header><main>{body}</main><div class="partner-assessment-modal" id="partner-assessment-modal" hidden onclick="if(event.target===this)closePartnerAssessment()"><section class="partner-assessment-dialog" role="dialog" aria-modal="true" aria-labelledby="partner-assessment-title"><button class="partner-assessment-close" type="button" aria-label="关闭" onclick="closePartnerAssessment()">×</button><h3 id="partner-assessment-title">搭档的判断</h3><div class="partner-assessment-body" id="partner-assessment-body"></div></section></div><script>
async function submitCooperativeForm(form,event){{
  event.preventDefault();
  if(form.dataset.submitting==='1') return false;
  form.dataset.submitting='1';
  const button=form.querySelector('button');
  const input=form.querySelector('textarea[name="text"]');
  const log=document.getElementById('turn-result');
  button.disabled=true;
  button.textContent='搭档思考中…';
  const empty=log&&log.querySelector('.cooperative-empty');
  if(empty) empty.remove();
  let pending=null;
  if(log){{
    pending=document.createElement('section');
    pending.className='cooperative-turn';
    const dialogue=document.createElement('div');
    dialogue.className='turn-dialogue';
    const message=document.createElement('article');
    message.className='turn-message turn-message-player';
    const body=document.createElement('div');
    body.className='turn-message-body';
    const speaker=document.createElement('span');
    speaker.className='turn-speaker';speaker.textContent='你';
    const bubble=document.createElement('p');
    bubble.className='turn-bubble';bubble.textContent=input.value;
    const avatar=document.createElement('div');
    avatar.className='turn-avatar';avatar.textContent='你';
    body.append(speaker,bubble);message.append(body,avatar);dialogue.append(message);
    const status=document.createElement('p');
    status.className='cooperative-pending';status.textContent='调查搭档正在结合现场线索思考';
    pending.append(dialogue,status);log.append(pending);log.scrollTop=log.scrollHeight;
  }}
  try{{
    let response=await fetch(form.action,{{method:'POST',body:new FormData(form),credentials:'same-origin'}});
    while(response.url.includes('/cases/wait')){{
      await new Promise(resolve=>setTimeout(resolve,1200));
      response=await fetch(response.url,{{credentials:'same-origin'}});
    }}
    if(!response.ok) throw new Error('request failed');
    const nextDocument=await response.text();
    if(response.url) history.replaceState(null,'',response.url);
    document.open();document.write(nextDocument);document.close();
  }}catch(error){{
    form.dataset.submitting='0';button.disabled=false;button.textContent='重新发送';
    const status=pending&&pending.querySelector('.cooperative-pending');
    if(status) status.textContent='暂时未能取得回答，请检查连接后重新发送。';
  }}
  return false;
}}
function focusLatestCooperativeTurn(){{
  const log=document.getElementById('turn-result');
  if(!log) return;
  const turns=Array.from(log.children).filter(item=>item.classList.contains('cooperative-turn'));
  const latest=turns[turns.length-1];
  if(latest) log.scrollTop=Math.max(0,latest.offsetTop-log.offsetTop-10);
}}
function showPartnerAssessment(button){{
  const turn=button.closest('.cooperative-turn');
  const source=turn&&turn.querySelector('.turn-assessment-data');
  const modal=document.getElementById('partner-assessment-modal');
  const body=document.getElementById('partner-assessment-body');
  if(!source||!modal||!body) return;
  body.innerHTML=source.innerHTML;modal.hidden=false;
  modal.querySelector('.partner-assessment-close').focus();
}}
function closePartnerAssessment(){{
  const modal=document.getElementById('partner-assessment-modal');
  if(modal) modal.hidden=true;
}}
document.addEventListener('keydown',event=>{{if(event.key==='Escape')closePartnerAssessment();}});
requestAnimationFrame(focusLatestCooperativeTurn);
</script></body></html>"""
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
    cooperative_record_enabled=False,
    cooperative_context_v2_enabled=False,
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
        cooperative_record_enabled=cooperative_record_enabled,
        cooperative_context_v2_enabled=cooperative_context_v2_enabled,
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
                self._start(query.get("notice", ""))
            elif parsed.path == "/clinic":
                self._home(self._player_id(query))
            elif parsed.path == "/welcome":
                self._welcome(self._player_id(query))
            elif parsed.path == "/cases":
                self._cases(self._player_id(query), query.get("case_id"), query.get("session_id"))
            elif parsed.path == "/cases/wait":
                self._wait_for_operation(query)
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
        path = ""
        form = {}
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
                player_text=form.get("text","")
                contribution_type=(
                    PlayerContributionType.GENERAL_MESSAGE
                    if path == "/cases/cooperate"
                    else PlayerContributionType.SUGGESTION
                )
                result=self.server.clinic_service.submit_player_contribution(ClinicContributionInput(
                    player_id=player_id,case_id=case_id,session_id=session_id,
                    operation_id=token,text=player_text,
                    contribution_type=contribution_type,
                ))
                location="/cases?"+urlencode(self._cooperative_query(
                    player_id,case_id,session_id,result,player_text=player_text
                ))+"#turn-result"
            elif path == "/cases/cooperate/respond":
                player_id=self._player_id(form);case_id=form.get("case_id","");session_id=form.get("session_id","")
                approved=form.get("response")=="approve"
                player_text=("我批准这项行动，请你依据最新状态再次判断。" if approved else "我不同意这项行动，请提出其他方案。")
                result=self.server.clinic_service.submit_player_contribution(ClinicContributionInput(
                    player_id=player_id,case_id=case_id,session_id=session_id,operation_id=token,
                    text=player_text,
                    contribution_type=(PlayerContributionType.APPROVAL if approved else PlayerContributionType.REJECTION),
                    responds_to_decision_id=form.get("decision_id") or None,
                    pending_confirmation_id=form.get("confirmation_id") or None,
                ))
                location="/cases?"+urlencode(self._cooperative_query(
                    player_id,case_id,session_id,result,player_text=player_text
                ))+"#turn-result"
            elif path == "/cases/chat":
                player_id=self._player_id(form);case_id=form.get("case_id","");session_id=form.get("session_id","")
                self.server.clinic_service.case_chat_message(player_id,case_id,session_id,token,form.get("message", ""))
                values={"player_id":player_id,"case_id":case_id,"session_id":session_id}
                location="/cases?"+urlencode(values)
            elif path == "/cases/start":
                player_id = self._player_id(form)
                result = self.server.clinic_service.start_case(player_id, form.get("case_id", ""), cooperative=True)
                location = "/cases?" + urlencode({"player_id": player_id, "case_id": result.case_id, "session_id": result.session_id})
            elif path == "/cases/resume":
                player_id = self._player_id(form)
                case_id = form.get("case_id", "")
                session_id = form.get("session_id", "")
                result = self.server.clinic_service.resume_case(
                    player_id, case_id, session_id
                )
                location = "/cases?" + urlencode({
                    "player_id": player_id,
                    "case_id": result.case_id,
                    "session_id": result.session_id,
                })
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
        except ClinicError as exc:
            if exc.code == "player_name_exists" and path == "/players":
                self._redirect("/?" + urlencode({"notice": str(exc)}))
                return
            if (
                exc.code == "operation_in_progress"
                and path in {"/cases/natural", "/cases/cooperate", "/cases/cooperate/respond"}
                and form.get("operation_id", "").startswith("op_")
            ):
                wait_query = urlencode({
                    "operation_id": form["operation_id"],
                    "player_id": form.get("player_id", ""),
                    "case_id": form.get("case_id", ""),
                    "session_id": form.get("session_id", ""),
                })
                self._redirect("/cases/wait?" + wait_query)
                return
            self._error(400, str(exc))
        except (ValidationError, ValueError) as exc:
            self._error(400, str(exc))
        except Exception:
            self._error(500, "操作未完成；已保留最后一次成功进度。")

    @staticmethod
    def _cooperative_query(
        player_id,case_id,session_id,result,*,player_text=""
    ):
        evaluation=result.decision.proposal.contribution_evaluation
        trace=result.memory_usage_trace
        values={"player_id":player_id,"case_id":case_id,"session_id":session_id,
                "player_text":player_text,
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
        return f'''<nav class="session-nav"><span class="session-nav-links"><a href="/clinic?{q}">调查主页</a><span aria-hidden="true">·</span><a href="/cases?{q}">调查异案</a></span><form class="logout-form" method="post" action="/quit"><input type="hidden" name="operation_id" value="{self._token()}"><button class="logout-button" type="submit">退出登录</button></form></nav>'''

    def _welcome(self, player_id):
        player=self.server.clinic_service.home(player_id).player_summary
        body=f'''{self._nav(player_id)}<h2>初次同行</h2><section class="card"><h3>同行须知</h3><p>你将与一名独立行动的调查搭档结伴，查访人与契、旧物和炁息交缠而成的志怪异案。你可以提出线索、疑问、建议和判断；搭档会结合现场情况安排调查，重大或不可逆的决定仍会先征得你的明确同意。</p></section><section class="card partner"><h3>调查搭档</h3><p>各地已有数桩异事待查。我们先核对眼前线索，再商量判断和去向。我会说明自己的想法并决定下一步；最终能发现什么，仍要以实际调查为准。</p></section><form method="post" action="/welcome/complete"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>与搭档同行，前往选案</button></form>'''
        body=f'<p>调查者：{_esc(player.display_name)}</p>'+body
        self._send(200,_page("初次同行",body))

    def _start(self, notice=""):
        players = self.server.clinic_service.list_players()
        sessions = self.server.clinic_service.store.list_case_sessions()
        name_counts = {}
        for item in players:
            key = item.display_name.casefold()
            name_counts[key] = name_counts.get(key, 0) + 1
        name_ordinals = {}
        save_items = []
        for item in players:
            key = item.display_name.casefold()
            name_ordinals[key] = name_ordinals.get(key, 0) + 1
            label = item.display_name
            if name_counts[key] > 1:
                label = f"{label}（档案 {name_ordinals[key]}）"
            owned_sessions = tuple(
                session for session in sessions if session.player_id == item.player_id
            )
            active = next(
                (session for session in owned_sessions if session.status.value == "active"),
                None,
            )
            completed_count = sum(
                session.status.value == "completed" for session in owned_sessions
            )
            if active is not None:
                case = self.server.clinic_service.base_catalog.get(active.case_id)
                detail = f"正在调查：{case.title}"
                href = "/cases?" + urlencode({
                    "player_id": item.player_id,
                    "case_id": active.case_id,
                    "session_id": active.session_id,
                })
            elif completed_count:
                detail = f"已完成 {completed_count} 桩异案"
                href = "/clinic?" + urlencode({"player_id": item.player_id})
            else:
                detail = "尚未接案"
                href = "/clinic?" + urlencode({"player_id": item.player_id})
            save_items.append(
                f'<li><a class="save-link" href="{_esc(href)}"><strong>{_esc(label)}</strong><span>{_esc(detail)}</span></a></li>'
            )
        restored = "".join(save_items) or "<li>尚无调查档案</li>"
        notice_html = f'<p class="notice">{_esc(notice)}</p>' if notice else ""
        body = f"""<h2>进入志怪异案调查</h2><p>你将与一名自主 NPC 组成调查搭档，共同调查异事。</p>{notice_html}<div class="grid"><section class="card"><h3>创建玩家档案</h3><form method="post" action="/players"><label>玩家名 <input name="display_name" maxlength="40" required></label><input type="hidden" name="operation_id" value="{self._token()}"><button>创建并进入</button></form></section><section class="card"><h3>恢复调查档案</h3><ul class="save-list">{restored}</ul></section></div><p>直接输入想说的话即可，调查进度会自动保存。</p>"""
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
            active_case_id=next(
                (item.case_id for item in view.visible_cases if item.status == "active"),
                None,
            )
            labels={"available":"可接案","active":"当前调查","completed":"已完成"}
            cards = ""
            for item in view.visible_cases:
                if item.status == "active" and item.active_session_id:
                    action = "/cases/resume"
                    session_input = f'<input type="hidden" name="session_id" value="{_esc(item.active_session_id)}">'
                    button_label = "继续调查"
                    card_modifier = " case-card-active"
                    action_html = f'''<form method="post" action="{action}"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(item.case_id)}">{session_input}<input type="hidden" name="operation_id" value="{self._token()}"><button>{button_label}</button></form>'''
                elif item.status == "completed":
                    card_modifier = " case-card-completed"
                    action_html = '<button type="button" disabled>案件已完成</button>'
                elif active_case_id is not None:
                    card_modifier = " case-card-locked"
                    action_html = '<button type="button" disabled>先完成当前案件</button>'
                else:
                    card_modifier = ""
                    action_html = f'''<form method="post" action="/cases/start"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(item.case_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><button>接案</button></form>'''
                visible_status=(
                    "等待当前案件完成"
                    if item.status == "available" and active_case_id is not None
                    else labels.get(item.status, "状态已更新")
                )
                recommended_html=(
                    '<span class="recommended">搭档建议</span>'
                    if item.recommended and active_case_id is None else ""
                )
                cards += f'''<section class="card case-card{card_modifier}"><h3>{_esc(item.title)}</h3><p class="case-synopsis">{_esc(item.synopsis)}</p><div class="case-meta"><span class="case-type">类型：异象案</span><span class="status-badge">{_esc(visible_status)}</span>{recommended_html}</div><div class="case-footer">{action_html}</div></section>'''
            lobby_intro=(
                "你已有一桩异案正在调查。完成当前案件后，便可接取其他案件。"
                if active_case_id is not None
                else "选择一桩异案，与调查搭档共同查明真相。"
            )
            self._send(200, _page("异案大厅", self._nav(player_id) + f'<h2>志怪异案选案大厅</h2><p>{_esc(lobby_intro)}</p><div class="case-grid">' + cards + "</div>"))
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
        empty_dialogue='<p class="notice">尚未与案中人物交谈。这里用于询问当前案件中的人物；与调查搭档商议行动请使用上方协作框。</p>'
        bubbles="".join(f'<article class="bubble {_esc(msg.message_type)}"><strong>{_esc(names.get(msg.speaker_id,"系统"))}</strong><p>{_esc(msg.public_text)}</p></article>' for msg in dialogue.recent_messages) or empty_dialogue
        options=''.join(f'<option value="@{_esc(x.display_name)} "></option>' for x in participants)
        current=names.get(dialogue.current_target,"请选择")
        chat=f'''<section class="card chat"><h3>与案中人物交谈</h3><p>当前人物：<strong>{_esc(current)}</strong></p><div class="chat-log">{bubbles}</div><form class="composer" method="post" action="/cases/chat"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><textarea name="message" rows="3" list="case-recipients" required placeholder="询问案中人物；例如：@{_esc(current)} 请说说你最后一次见到异常的经过。"></textarea><datalist id="case-recipients">{options}</datalist><button>询问案中人物</button></form></section>'''
        chat=chat.replace('<textarea name="message" rows="3" list="case-recipients"','<input name="message" list="case-recipients"').replace('</textarea><datalist','><datalist')
        drawers=f'''<section class="drawers"><details class="card"><summary>调查提纲与进度</summary><ul>{stage_html}</ul></details><details class="card"><summary>已发现线索</summary><ul>{clues}</ul></details><details class="card"><summary>案中人物</summary><ul>{''.join(f'<li>{_esc(x.display_name)}</li>' for x in participants)}</ul></details><details class="card"><summary>辨证与处置</summary><p>达到规则要求后，下方将显示可提交入口。</p></details></section>'''
        query=self._query();player_text=query.get("player_text","");npc_reply=query.get("npc_reply","");disposition=query.get("suggestion_disposition","")
        suggestion_explanation=query.get("suggestion_explanation","");npc_action=query.get("npc_action","")
        environment_feedback=query.get("environment_feedback","");confirmation_id=query.get("confirmation_id","")
        decision_id=query.get("decision_id","");authority_mode=query.get("authority_mode","")
        npc_tool_public=query.get("npc_tool_public","");npc_rationale=query.get("npc_rationale","")
        runtime_kind=query.get("runtime_kind","");debug_tool_name=query.get("debug_tool_name","")
        llm_attempts=query.get("llm_attempts","");llm_used_fallback=query.get("llm_used_fallback","")=="1"
        llm_repair_kind=query.get("llm_repair_kind","")
        disposition_labels={
            "accept":"已采纳",
            "partial_accept":"部分采纳",
            "reject":"未采纳",
            "request_more_evidence":"需要更多证据",
            "propose_alternative":"提出替代方案",
        }
        disposition_label=disposition_labels.get(disposition,"已回应")
        if runtime_kind=="deterministic_fallback":
            npc_runtime_notice="调查搭档已依据现场线索完成本轮判断。"
        elif llm_used_fallback:
            npc_runtime_notice="调查搭档暂时无法形成可靠判断，已停止本轮行动，现场状态未改变。"
        elif llm_repair_kind:
            npc_runtime_notice="调查搭档已核对并完成本轮判断。"
        elif runtime_kind=="real_llm":
            npc_runtime_notice="调查搭档已完成本轮判断。"
        else:
            npc_runtime_notice="调查搭档已完成本轮处理。"
        goal_changed=query.get("goal_changed","")=="1";plan_changed=query.get("plan_changed","")=="1"
        contribution_id=query.get("contribution_id","")
        memory_public_effect=query.get("memory_public_effect","")
        memory_accepted_ids=query.get("memory_accepted_used_ids","")
        memory_player_copy=memory_public_effect.replace("NPC ","搭档").replace("NPC","搭档")
        memory_effect_html=(f'<p class="notice"><strong>过往经验：</strong>{_esc(memory_player_copy)}</p>' if memory_player_copy and memory_accepted_ids else "")
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
        reflection_learning_html=""
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
                    if evaluation.outcome is PlanEvaluationOutcome.COMPLETE_GOAL:
                        evaluation_html='<p class="notice"><strong>当前调查目标已经完成。</strong></p>'
                    evaluation_debug=f'<p>evaluation outcome：{_esc(evaluation.outcome.value)}</p><p>evaluation reason：{_esc(evaluation.reason_code.value)}</p><p>observation revision：{evaluation.observation_revision_after}</p>'
                player_changed=(goal_changed and goal.source_contribution_id==contribution_id) or (plan_changed and plan is not None and plan.source_contribution_id==contribution_id)
                changed_html='<p class="notice">搭档已根据你的建议更新调查计划。</p>' if player_changed else ''
                memory_plan_html='<p class="notice">搭档参考过往经验调整了调查顺序。</p>' if memory_public_effect and memory_accepted_ids and plan_changed else ''
                full_plan_html=(
                    f'<details class="plan-details"><summary>查看完整计划</summary><ul>{plan_items}</ul></details>'
                    if plan_items else '<p>调查计划尚待形成。</p>'
                )
                planning_card=f'''<section class="card npc-thinking"><h3>搭档的调查计划</h3><p><strong>当前目标：</strong>{_esc(goal.public_description)}</p>{f'<p class="next-step"><strong>下一步：</strong>{_esc(current_step)}</p>' if current_step else ''}{changed_html}{memory_plan_html}{evaluation_html}{full_plan_html}</section>'''
        def render_cooperative_turn(
            *,
            turn_player_text,
            turn_npc_reply,
            turn_disposition,
            turn_explanation,
            turn_action,
            turn_feedback,
            turn_runtime,
            turn_attempts,
            turn_repair,
            turn_capability,
            turn_raw_tool,
            turn_rationale,
            turn_fallback,
            turn_memory_html="",
            turn_reflection_html="",
            turn_debug_html="",
        ):
            player_turn_html=(
                f'<article class="turn-message turn-message-player" aria-label="你说"><div class="turn-message-body"><span class="turn-speaker">你</span><p class="turn-bubble">{_esc(turn_player_text)}</p></div><div class="turn-avatar" aria-hidden="true">你</div></article>'
                if turn_player_text else ""
            )
            partner_avatar=(
                '<button class="turn-avatar turn-avatar-button" type="button" aria-label="查看搭档的判断" aria-haspopup="dialog" onclick="showPartnerAssessment(this)">伴</button>'
                if turn_disposition else '<div class="turn-avatar" aria-hidden="true">伴</div>'
            )
            npc_turn_html=(
                f'<article class="turn-message turn-message-partner" aria-label="调查搭档说">{partner_avatar}<div class="turn-message-body"><span class="turn-speaker">调查搭档</span><p class="turn-bubble">{_esc(_player_copy(turn_npc_reply, action_label=turn_action))}</p></div></article>'
                if turn_npc_reply else ""
            )
            suggestion_player_copy=_player_copy(
                turn_explanation, action_label=turn_action
            )
            turn_disposition_label=disposition_labels.get(
                turn_disposition, "已回应"
            )
            assessment_html=(
                f'<div class="turn-assessment-data" hidden><span class="decision-chip">{_esc(turn_disposition_label)}</span><p>{_esc(suggestion_player_copy)}</p></div>'
                if turn_disposition else ""
            )
            action_heading = {
                "reject": "搭档改为调查：",
                "propose_alternative": "搭档改为调查：",
                "request_more_evidence": "搭档先行调查：",
            }.get(turn_disposition, "采取行动：")
            action_html=(
                f'<p class="turn-action"><strong>{action_heading}</strong>{_esc(_player_copy(turn_action))}</p>'
                if turn_action else ""
            )
            discovery_title=(
                "发现新线索"
                if "发现" in turn_feedback
                else "现场反馈"
            )
            discovery_html=(
                f'<section class="discovery"><h4>{discovery_title}</h4><p>{_esc(_player_copy(turn_feedback))}</p></section>'
                if turn_feedback else ""
            )
            fallback_html=(
                '<p class="notice">调查搭档暂时无法形成可靠判断，已停止本轮行动，现场状态未改变。</p>'
                if turn_fallback else ""
            )
            return f'''<section class="cooperative-turn"><div class="turn-dialogue">{player_turn_html}{npc_turn_html}</div>{assessment_html}{action_html}{discovery_html}{turn_memory_html}{turn_reflection_html}{fallback_html}</section>'''

        cooperative_result=""
        stored_turns=self.server.clinic_service.cooperative_turn_history(
            player_id, case_id, session_id
        )
        if stored_turns:
            rendered_turns=[]
            for stored_contribution, stored_result in stored_turns:
                stored_evaluation=(
                    stored_result.decision.proposal.contribution_evaluation
                )
                stored_trace=stored_result.memory_usage_trace
                stored_memory_html=(
                    f'<p class="notice"><strong>过往经验：</strong>{_esc(stored_result.public_memory_effect_summary.replace("NPC ","搭档").replace("NPC","搭档"))}</p>'
                    if stored_result.public_memory_effect_summary
                    and stored_trace is not None
                    and stored_trace.accepted_used_memory_ids else ""
                )
                stored_reflection_html=""
                rendered_turns.append(render_cooperative_turn(
                    turn_player_text=stored_contribution.public_text,
                    turn_npc_reply=stored_result.decision.proposal.action.dialogue,
                    turn_disposition=(stored_evaluation.disposition.value if stored_evaluation else ""),
                    turn_explanation=(stored_evaluation.explanation if stored_evaluation else ""),
                    turn_action=stored_result.selected_public_target or "",
                    turn_feedback=stored_result.environment_message or "",
                    turn_runtime=stored_result.runtime_kind.value,
                    turn_attempts=str(stored_result.decision.llm_attempts),
                    turn_repair=stored_result.decision.repair_kind or "",
                    turn_capability=stored_result.decision.proposal.capability.value,
                    turn_raw_tool=(stored_result.selected_tool.value if stored_result.selected_tool else ""),
                    turn_rationale=stored_result.public_rationale,
                    turn_fallback=stored_result.decision.used_fallback,
                    turn_memory_html=stored_memory_html,
                    turn_reflection_html=stored_reflection_html,
                ))
            cooperative_result="".join(rendered_turns)
        elif npc_reply or disposition or environment_feedback:
            cooperative_result=render_cooperative_turn(
                turn_player_text=player_text,
                turn_npc_reply=npc_reply,
                turn_disposition=disposition,
                turn_explanation=suggestion_explanation,
                turn_action=npc_tool_public,
                turn_feedback=environment_feedback,
                turn_runtime=runtime_kind,
                turn_attempts=llm_attempts,
                turn_repair=llm_repair_kind,
                turn_capability=npc_action,
                turn_raw_tool=debug_tool_name,
                turn_rationale=npc_rationale,
                turn_fallback=llm_used_fallback,
                turn_memory_html=memory_effect_html,
                turn_reflection_html=reflection_learning_html,
                turn_debug_html=memory_debug_html+reflection_debug_html,
            )
        confirmation=""
        if confirmation_id and decision_id:
            label="同意诊断提议" if authority_mode=="proposal_only" else "确认高风险处置"
            hidden=f'<input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="confirmation_id" value="{_esc(confirmation_id)}"><input type="hidden" name="decision_id" value="{_esc(decision_id)}">'
            confirmation=f'''<section class="card notice"><h3>需要你的决定</h3><p>该行动尚未执行。搭档会在你回应后依据最新案件状态再次判断。</p><form method="post" action="/cases/cooperate/respond">{hidden}<input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="response" value="approve"><button>{label}</button></form><form method="post" action="/cases/cooperate/respond">{hidden}<input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="response" value="reject"><button>拒绝并要求替代方案</button></form></section>'''
        configured_notice="调查搭档已就绪，将独立评估你的建议，并结合已有线索推进调查。"
        cooperative_empty='''<div class="cooperative-empty"><p>还没有聊天记录。<br>在下方告诉调查搭档你的判断或调查方向。</p></div>'''
        cooperative_form=f'''<section class="card cooperative-card"><h3>与调查搭档协作</h3><p class="notice">{_esc(configured_notice)}</p><div class="cooperative-log" id="turn-result" aria-live="polite">{cooperative_result or cooperative_empty}</div><form class="cooperative-composer" method="post" action="/cases/cooperate" onsubmit="return submitCooperativeForm(this,event)"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><div class="cooperative-input-row"><textarea name="text" rows="3" required placeholder="可以聊天、询问案情，或明确说出想调查什么。"></textarea><button>发送</button></div></form><small class="cooperative-hint">像聊天一样直接输入即可。普通聊天和提问不会推进案件；明确提出检查、询问或观察等行动后，搭档才会执行下一步。</small></section>'''
        body=f'''{self._nav(player_id)}<h2>{_esc(observation.title)}</h2><p>{_esc(observation.synopsis)}</p>{cooperative_form}{confirmation}{planning_card}{chat}{drawers}'''
        if observation.can_submit_diagnosis:
            evidence = ",".join(item.clue_id for item in observation.discovered_clues)
            body += f'<details class="card"><summary>Manual / baseline：直接提交辨证</summary><form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="diagnosis"><input type="hidden" name="evidence_clue_ids" value="{_esc(evidence)}"><select name="selection_id">{diagnoses}</select><button>提交辨证</button></form></details>'
        treatments = "".join(f'<form method="post" action="/cases/action"><input type="hidden" name="player_id" value="{_esc(player_id)}"><input type="hidden" name="case_id" value="{_esc(case_id)}"><input type="hidden" name="session_id" value="{_esc(session_id)}"><input type="hidden" name="operation_id" value="{self._token()}"><input type="hidden" name="action_type" value="treatment"><input type="hidden" name="selection_id" value="{_esc(item.treatment_id)}"><button>{_esc(item.public_description)}</button></form>' for item in observation.available_treatments)
        if treatments:
            body += '<details class="card"><summary>Manual / baseline：直接选择处置</summary>' + treatments + '</details>'
        self._send(200, _page("异案", body))

    def _error(self, status, message):
        self._send(status, _page("安全错误", f'<h2 class="error">无法完成</h2><p>{_esc(message)}</p><p><a href="/">返回开始页</a></p>'))

    def _wait_for_operation(self, query):
        token = query.get("operation_id", "")
        if not re.fullmatch(r"op_[A-Za-z0-9_-]{1,120}", token):
            raise ClinicError("operation_required", "操作令牌无效，请返回案件页面重试。")
        player_id = self._player_id(query)
        case_id = query.get("case_id", "")
        session_id = query.get("session_id", "")
        completed_location = self.server.operation_results.get(token)
        if completed_location:
            self._redirect(completed_location)
            return
        case_location = "/cases?" + urlencode({
            "player_id": player_id,
            "case_id": case_id,
            "session_id": session_id,
        })
        body = (
            self._nav(player_id)
            + '<section class="card"><h2>调查搭档正在思考</h2>'
            + '<p class="notice">你的消息已经收到，正在结合现场线索形成回答。请稍候，本页会自动返回案件。</p>'
            + '<p>请不要重复提交，也不需要重新选择玩家。</p>'
            + f'<p><a href="{_esc(case_location)}">立即返回案件</a></p></section>'
            + '<script>setTimeout(function(){window.location.reload()},1500)</script>'
        )
        self._send(200, _page("搭档思考中", body))


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
    parser.add_argument(
        "--cooperative-record",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启用协作回合账本、幂等保护和历史记录（默认启用）",
    )
    parser.add_argument(
        "--cooperative-context-v2",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="启用 CE-2A 协作上下文（默认启用，依赖协作记录）",
    )
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
                cooperative_record_enabled=args.cooperative_record,
                cooperative_context_v2_enabled=args.cooperative_context_v2,
            )
            server = ClinicHTTPServer((args.host, args.port), service)
            host, port = server.server_address
            print(f"《异闻行录》已启动：http://{host}:{port}", flush=True)
            print(f"NPC mode={args.npc_mode}", flush=True)
            print(f"Memory mode={memory_mode}", flush=True)
            print(f"Reflection mode={'enabled' if reflection_service is not None else 'disabled'}", flush=True)
            print(f"Cooperative record={'enabled' if args.cooperative_record else 'disabled'}", flush=True)
            print(f"Cooperative context v2={'enabled' if args.cooperative_context_v2 else 'disabled'}", flush=True)
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
