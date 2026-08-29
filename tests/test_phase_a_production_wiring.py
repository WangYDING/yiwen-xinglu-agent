from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import threading
from urllib.parse import urlencode

import pytest

from xuanyi_npc.agents import (
    DeepSeekAdapterConfig,
    DeepSeekConfigurationError,
    DeterministicCooperativeNPC,
    GameNPCAgent,
    ScriptedFakeLLM,
)
from xuanyi_npc.application.action_contract import INVESTIGATION_TOOL_BY_ACTION
from xuanyi_npc.application.clinic import ClinicContributionInput, ClinicService
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.application.memory_retrieval import MemoryIndexService
from xuanyi_npc.clinic import server as clinic_server
from xuanyi_npc.clinic.server import ClinicHTTPServer
from xuanyi_npc.domain import AgentAction, AgentActionType, ToolCallRequest
from xuanyi_npc.domain.cooperation import (
    AgentRuntimeKind,
    GameNPCDecisionProposal,
    NPCCapability,
    PlayerContributionEvaluation,
    PlayerContributionType,
    SuggestionDisposition,
)
from xuanyi_npc.domain.cooperative_planning import GoalCondition, GoalConditionType
from xuanyi_npc.domain.planning_contract import (
    GameNPCTurnProposal,
    GoalUpdateKind,
    GoalUpdateProposal,
    PlanDraft,
    PlanStepDraft,
    PlanUpdateKind,
    PlanUpdateProposal,
)
from xuanyi_npc.memory import DeterministicFakeEmbedding
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository
from tests.r1_helpers import FixedClock, FixedPlayerIds, FixedSessionIds
from tests.clinic_helpers import request


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"


def parsed_args(*values: str):
    return clinic_server.build_parser().parse_args(values)


def clinic_at(tmp_path, agent) -> ClinicService:
    return ClinicService(
        store=JsonStateStore(tmp_path),
        base_catalog=CaseCatalog(ROOT / "cases"),
        campaign_path=ROOT / "campaign" / "cross_episode_rules_v2.json",
        clock=FixedClock(),
        player_id_factory=FixedPlayerIds(),
        session_id_factory=FixedSessionIds(),
        game_npc_agent=agent,
    )


def proposal_for(observation, contribution_id: str) -> GameNPCTurnProposal:
    option = observation.available_investigations[0]
    tool = INVESTIGATION_TOOL_BY_ACTION[option.action_type]
    completion = GoalCondition(
        condition_type=GoalConditionType.INVESTIGATION_COMPLETED,
        reference_id=option.investigation_id,
    )
    return GameNPCTurnProposal(
        goal_update=GoalUpdateProposal(
            update=GoalUpdateKind.KEEP,
            public_rationale="继续当前公开取证目标。",
        ),
        plan_update=PlanUpdateProposal(
            update=PlanUpdateKind.CREATE,
            draft=PlanDraft(steps=(
                PlanStepDraft(
                    intent="investigate",
                    capability=NPCCapability.USE_TOOL,
                    suggested_tool=tool,
                    public_target_id=option.investigation_id,
                    public_summary="执行一项公开调查。",
                    completion_signal=completion,
                ),
                PlanStepDraft(
                    intent="discuss_with_player",
                    capability=NPCCapability.EXPLAIN,
                    public_summary="与玩家核对新证据。",
                    completion_signal=GoalCondition(
                        condition_type=GoalConditionType.MINIMUM_CLUE_COUNT,
                        threshold=3,
                    ),
                ),
            )),
            public_rationale="以两步短计划推进调查。",
        ),
        decision=GameNPCDecisionProposal(
            contribution_evaluation=PlayerContributionEvaluation(
                contribution_id=contribution_id,
                disposition=SuggestionDisposition.ACCEPT,
                reason_code="public_investigation",
                explanation="建议与当前公开调查方向一致。",
            ),
            capability=NPCCapability.USE_TOOL,
            action=AgentAction(
                action_id=f"npc_{contribution_id}",
                action_type=AgentActionType.USE_TOOL,
                dialogue="先执行当前计划中的公开调查。",
                tool_call=ToolCallRequest(
                    name=tool,
                    arguments={"investigation_id": option.investigation_id},
                ),
                confidence=0.8,
            ),
            explanation="该行动与当前计划步骤一致。",
        ),
    )


def opened_clinic(tmp_path, agent):
    clinic = clinic_at(tmp_path, agent)
    player_id = clinic.create_player("Phase A 玩家").player_summary.player_id
    opened = clinic.start_case(player_id, "old_paper_umbrella", cooperative=True)
    return clinic, player_id, opened


def contribution(player_id, opened, operation_id="phase_a_turn"):
    return ClinicContributionInput(
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        operation_id=operation_id,
        text="请先执行一项公开调查。",
        contribution_type=PlayerContributionType.SUGGESTION,
    )


def test_offline_mode_explicitly_builds_deterministic_agent():
    agent, adapter = clinic_server.build_game_npc(parsed_args("--npc-mode", "offline"))
    assert isinstance(agent, DeterministicCooperativeNPC)
    assert adapter is None


def test_build_clinic_service_injects_selected_agent(tmp_path):
    agent = DeterministicCooperativeNPC()
    service = clinic_server.build_clinic_service(
        tmp_path,
        SimpleNamespace(
            case_dir=ROOT / "cases",
            campaign_rules=ROOT / "campaign" / "cross_episode_rules_v2.json",
        ),
        game_npc_agent=agent,
    )
    assert service.game_npc_agent is agent


def test_semantic_startup_reconciles_receipts_only_after_player_index(
    tmp_path, qualified_player_state
):
    events = []
    store = JsonStateStore(tmp_path)
    player = qualified_player_state.model_copy(update={"player_id": "player_startup"})
    store.save_player(player)

    class Index:
        adapter = SimpleNamespace(
            embedding_space_id="startup_space",
            dimension=1024,
        )

        def index_player(self, *, player_id):
            events.append(("index", player_id))

    class Reflection:
        def reconcile_pending_indexes(self, **kwargs):
            events.append(("receipt", kwargs))

    clinic_server.build_clinic_service(
        tmp_path,
        SimpleNamespace(
            case_dir=ROOT / "cases",
            campaign_rules=ROOT / "campaign" / "cross_episode_rules_v2.json",
        ),
        game_npc_agent=DeterministicCooperativeNPC(),
        store=store,
        memory_coordinator=SimpleNamespace(),
        memory_index_service=Index(),
        memory_mode="semantic",
        reflection_service=Reflection(),
    )

    assert events == [
        ("index", "player_startup"),
        (
            "receipt",
            {
                "player_id": "player_startup",
                "embedding_space_id": "startup_space",
                "embedding_dimension": 1024,
            },
        ),
    ]


def test_production_reflection_reuses_agent_adapter_repository_and_index(tmp_path):
    class Adapter:
        def complete(self, request):
            raise AssertionError("composition test must not call the model")

    adapter = Adapter()
    repository = SQLiteMemoryRepository(tmp_path / "memories.sqlite3")
    repository.initialize()
    index = MemoryIndexService(
        repository=repository,
        adapter=DeterministicFakeEmbedding(),
    )
    args = parsed_args("--npc-mode", "llm")
    reflection = clinic_server.build_production_reflection(
        args,
        game_npc_adapter=adapter,
        memory_mode="semantic",
        memory_repository=repository,
        memory_index_service=index,
    )
    assert reflection.generator.output.adapter is adapter
    assert reflection.consolidation_service.repository is repository
    assert reflection.consolidation_service.index_service is index
    assert reflection.receipt_repository is repository


def test_clinic_service_rejects_implicit_agent_mode(tmp_path):
    with pytest.raises(ValueError, match="explicit game_npc_agent"):
        ClinicService(
            store=JsonStateStore(tmp_path),
            base_catalog=CaseCatalog(ROOT / "cases"),
            campaign_path=ROOT / "campaign" / "cross_episode_rules_v2.json",
            clock=FixedClock(),
        )


def test_llm_mode_requires_paid_authorization():
    with pytest.raises(DeepSeekConfigurationError, match="paid-run"):
        clinic_server.build_game_npc(parsed_args("--npc-mode", "llm"))


def test_llm_mode_missing_key_is_startup_failure(monkeypatch):
    def missing_key():
        raise DeepSeekConfigurationError("missing key")

    monkeypatch.setattr(clinic_server.DeepSeekAdapterConfig, "from_env", missing_key)
    args = parsed_args(
        "--npc-mode", "llm", "--confirm-paid-agent", "--agent-budget-cny", "1.00"
    )
    with pytest.raises(DeepSeekConfigurationError, match="missing key"):
        clinic_server.build_game_npc(args)


def test_llm_mode_discovers_model_and_uses_planning_token_budget(monkeypatch):
    events = []

    class Adapter:
        def __init__(self, config):
            self.config = config
            events.append(("created", config.max_output_tokens, config.pilot_max_cost_cny))

        def require_configured_model(self):
            events.append(("discovered",))

        def close(self):
            events.append(("closed",))

        def complete(self, request):
            raise AssertionError("startup must not issue Chat")

    monkeypatch.setattr(
        clinic_server.DeepSeekAdapterConfig,
        "from_env",
        lambda: DeepSeekAdapterConfig(
            api_key="secret", max_output_tokens=512, pilot_max_cost_cny=Decimal("1.00")
        ),
    )
    monkeypatch.setattr(clinic_server, "DeepSeekChatAdapter", Adapter)
    args = parsed_args(
        "--npc-mode", "llm", "--confirm-paid-agent", "--agent-budget-cny", "2.00"
    )
    agent, adapter = clinic_server.build_game_npc(args)
    assert isinstance(agent, GameNPCAgent)
    assert adapter.config.max_output_tokens == 2048
    assert adapter.config.pilot_max_cost_cny == Decimal("2.00")
    assert events[-1] == ("discovered",)


def test_llm_mode_model_discovery_failure_closes_adapter(monkeypatch):
    closed = []

    class Adapter:
        def __init__(self, config):
            self.config = config

        def require_configured_model(self):
            raise RuntimeError("discovery failed")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(
        clinic_server.DeepSeekAdapterConfig,
        "from_env",
        lambda: DeepSeekAdapterConfig(api_key="secret", max_output_tokens=2048),
    )
    monkeypatch.setattr(clinic_server, "DeepSeekChatAdapter", Adapter)
    args = parsed_args(
        "--npc-mode", "llm", "--confirm-paid-agent", "--agent-budget-cny", "1.00"
    )
    with pytest.raises(RuntimeError, match="discovery failed"):
        clinic_server.build_game_npc(args)
    assert closed == [True]


def test_server_shutdown_closes_game_npc_adapter(tmp_path, monkeypatch):
    closed = []

    class Adapter:
        def close(self):
            closed.append(True)

    class Server:
        server_address = ("127.0.0.1", 43210)

        def __init__(self, address, service):
            del address, service

        def serve_forever(self, poll_interval):
            assert poll_interval == 0.1

        def server_close(self):
            pass

    monkeypatch.setattr(
        clinic_server,
        "build_game_npc",
        lambda args: (DeterministicCooperativeNPC(), Adapter()),
    )
    monkeypatch.setattr(clinic_server, "build_clinic_service", lambda *args, **kwargs: object())
    monkeypatch.setattr(clinic_server, "ClinicHTTPServer", Server)

    assert clinic_server.main([
        "--state-dir", str(tmp_path), "--npc-mode", "llm",
        "--memory-mode", "disabled",
    ]) == 0
    assert closed == [True]


def test_game_npc_production_turn_persists_plan_and_evaluation(tmp_path):
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    operation_id = "phase_a_llm_success"
    proposal = proposal_for(opened.observation, operation_id)
    clinic.game_npc_agent = GameNPCAgent(ScriptedFakeLLM([proposal.model_dump_json()]))

    result = clinic.submit_player_contribution(contribution(player_id, opened, operation_id))
    state = clinic.store.load_cooperative_agent_state(opened.session_id)
    session = clinic.store.load_case_session(opened.session_id)

    assert result.runtime_kind is AgentRuntimeKind.REAL_LLM
    assert not result.decision.used_fallback
    assert state.current_plan is not None
    assert state.last_plan_evaluation is not None
    assert len(session.action_history) == 1


def test_malformed_llm_output_repairs_then_stops_without_world_mutation(tmp_path):
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    clinic.game_npc_agent = GameNPCAgent(ScriptedFakeLLM(["not json", "still not json"]))

    result = clinic.submit_player_contribution(contribution(player_id, opened, "phase_a_bad_llm"))

    assert result.runtime_kind is AgentRuntimeKind.REAL_LLM
    assert result.decision.used_fallback
    assert result.decision.llm_attempts == 2
    assert result.decision.repair_kind == "format_repair"
    assert result.decision.proposal.action.action_type is AgentActionType.RESPOND
    assert clinic.store.load_case_session(opened.session_id).action_history == ()


def test_malformed_first_output_can_repair_to_valid_llm_turn(tmp_path):
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    operation_id = "phase_a_repaired_llm"
    proposal = proposal_for(opened.observation, operation_id)
    clinic.game_npc_agent = GameNPCAgent(
        ScriptedFakeLLM(["not json", proposal.model_dump_json()])
    )

    result = clinic.submit_player_contribution(
        contribution(player_id, opened, operation_id)
    )

    assert not result.decision.used_fallback
    assert result.decision.llm_attempts == 2
    assert result.decision.repair_kind == "format_repair"
    assert len(clinic.store.load_case_session(opened.session_id).action_history) == 1


def test_query_exposes_distinct_llm_and_offline_statuses(tmp_path):
    offline, player_id, opened = opened_clinic(tmp_path / "offline", DeterministicCooperativeNPC())
    offline_result = offline.submit_player_contribution(contribution(player_id, opened, "offline_turn"))
    offline_query = clinic_server.ClinicRequestHandler._cooperative_query(
        player_id, opened.case_id, opened.session_id, offline_result
    )
    assert offline_query["runtime_kind"] == "deterministic_fallback"
    assert offline_query["llm_used_fallback"] == ""

    llm, llm_player, llm_opened = opened_clinic(tmp_path / "llm", DeterministicCooperativeNPC())
    proposal = proposal_for(llm_opened.observation, "llm_turn")
    llm.game_npc_agent = GameNPCAgent(ScriptedFakeLLM([proposal.model_dump_json()]))
    llm_result = llm.submit_player_contribution(
        contribution(llm_player, llm_opened, "llm_turn")
    )
    llm_query = clinic_server.ClinicRequestHandler._cooperative_query(
        llm_player, llm_opened.case_id, llm_opened.session_id, llm_result
    )
    assert llm_query["runtime_kind"] == "real_llm"
    assert llm_query["llm_attempts"] == "1"


def test_player_page_distinguishes_offline_and_llm_fallback(tmp_path):
    clinic, player_id, opened = opened_clinic(tmp_path, DeterministicCooperativeNPC())
    server = ClinicHTTPServer(("127.0.0.1", 0), clinic)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}
    )
    thread.start()
    try:
        offline = clinic.submit_player_contribution(
            contribution(player_id, opened, "offline_page_turn")
        )
        offline_query = clinic_server.ClinicRequestHandler._cooperative_query(
            player_id, opened.case_id, opened.session_id, offline
        )
        _, _, offline_page = request(
            server.server_address[1], "GET", "/cases?" + urlencode(offline_query)
        )
        assert "离线确定性模式：本轮未调用语言模型" in offline_page
        assert "当前调查搭档：离线确定性 NPC" in offline_page

        clinic.game_npc_agent = GameNPCAgent(
            ScriptedFakeLLM(["not json", "still not json"])
        )
        fallback = clinic.submit_player_contribution(
            contribution(player_id, opened, "fallback_page_turn")
        )
        fallback_query = clinic_server.ClinicRequestHandler._cooperative_query(
            player_id, opened.case_id, opened.session_id, fallback
        )
        _, _, fallback_page = request(
            server.server_address[1], "GET", "/cases?" + urlencode(fallback_query)
        )
        assert "LLM 本轮未能产生有效决策" in fallback_page
        assert "已安全停步，未执行工具" in fallback_page
        assert "当前调查搭档：LLM GameNPCAgent" in fallback_page
        assert "长期 Memory 已禁用；Reflection 未启用" in fallback_page
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
