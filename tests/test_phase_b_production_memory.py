from pathlib import Path

import pytest

from xuanyi_npc.application import (
    BasicCosineMemoryRetriever,
    GameNPCMemoryProjectionPolicy,
    GameNPCMemoryRetrievalConfig,
    GameNPCMemoryRetrievalService,
    MemoryIndexService,
    V1MemoryCoordinator,
)
from xuanyi_npc.application.clinic import ClinicService
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.application.multicase import SubmitActionInput
from xuanyi_npc.clinic import server as clinic_server
from xuanyi_npc.memory import (
    DeterministicFakeEmbedding,
    DeterministicMemoryProjector,
    MemoryRetrievalConfig,
)
from xuanyi_npc.domain import AgentAction, AgentActionType
from xuanyi_npc.domain.planning_contract import PlanUpdateKind, PlanUpdateProposal
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository
from tests.r1_helpers import FixedClock, FixedPlayerIds, FixedSessionIds
from tests.test_phase_a_production_wiring import contribution, proposal_for
from tests.memory_helpers import reference_case_results


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"


class PlanningAgent:
    def __init__(self):
        self.inputs = []

    def propose_turn(self, value):
        self.inputs.append(value)
        return proposal_for(value.case_observation, value.turn_id)

    def repair_action_contract(self, value, prior, feedback):
        raise AssertionError("valid proposal must not be repaired")

    def action_contract_fallback(self, prior):
        raise AssertionError("valid proposal must not fall back")


class FailingIndex:
    def index_player(self, *, player_id):
        del player_id
        raise RuntimeError("injected index failure")


class KeepExistingPlanAgent(PlanningAgent):
    def propose_turn(self, value):
        self.inputs.append(value)
        proposal = proposal_for(value.case_observation, value.turn_id)
        return proposal.model_copy(update={
            "plan_update": PlanUpdateProposal(
                update=PlanUpdateKind.KEEP,
                public_rationale="继续当前公开计划。",
            )
        })


def memory_clinic(tmp_path, *, index_override=None):
    store = JsonStateStore(tmp_path / "state")
    repository = SQLiteMemoryRepository(tmp_path / "state" / "memories.sqlite3")
    repository.initialize()
    adapter = DeterministicFakeEmbedding()  # Explicit test-only embedding.
    index = index_override or MemoryIndexService(repository=repository, adapter=adapter)
    retrieval = GameNPCMemoryRetrievalService(
        retriever=BasicCosineMemoryRetriever(repository=repository, adapter=adapter),
        retrieval_config=MemoryRetrievalConfig(
            top_k=8,
            min_similarity=-1.0,
            embedding_space_id=adapter.embedding_space_id,
            query_template_version="memory_query_v1",
        ),
        projection_policy=GameNPCMemoryProjectionPolicy(repository=repository),
        projection_config=GameNPCMemoryRetrievalConfig(min_relevance=-1.0),
    )
    agent = PlanningAgent()
    clinic = ClinicService(
        store=store,
        base_catalog=CaseCatalog(ROOT / "cases"),
        campaign_path=ROOT / "campaign" / "cross_episode_rules_v2.json",
        clock=FixedClock(),
        player_id_factory=FixedPlayerIds(),
        session_id_factory=FixedSessionIds(),
        game_npc_agent=agent,
        cooperative_memory_service=retrieval,
        memory_coordinator=V1MemoryCoordinator(
            state_store=store, memory_repository=repository
        ),
        memory_index_service=index,
        memory_mode="semantic",
    )
    return clinic, repository, adapter, agent


def open_clinic(clinic):
    player_id = clinic.create_player("Phase B 玩家").player_summary.player_id
    opened = clinic.start_case(player_id, "old_paper_umbrella", cooperative=True)
    return player_id, opened


def test_committed_event_writes_memory_and_vector_and_survives_restart(tmp_path):
    clinic, repository, adapter, _ = memory_clinic(tmp_path)
    player_id, opened = open_clinic(clinic)

    result = clinic.submit_player_contribution(contribution(player_id, opened, "memory_write"))

    assert result.memory_commit_status == "complete"
    assert result.written_memory_ids
    memories = repository.list_memories(player_id=player_id, include_inactive=False)
    vectors = repository.list_embeddings(
        player_id=player_id, embedding_space_id=adapter.embedding_space_id
    )
    assert tuple(item.memory_id for item in memories) == result.written_memory_ids
    assert {item.memory_id for item in vectors} == {item.memory_id for item in memories}

    reopened = SQLiteMemoryRepository(tmp_path / "state" / "memories.sqlite3")
    reopened.initialize()
    assert reopened.list_memories(player_id=player_id) == memories
    assert reopened.list_embeddings(
        player_id=player_id, embedding_space_id=adapter.embedding_space_id
    ) == vectors


def test_failed_retrieval_is_safe_and_agent_receives_empty_context(tmp_path):
    clinic, _, _, agent = memory_clinic(tmp_path)
    player_id, opened = open_clinic(clinic)

    class BrokenRetrieval:
        def retrieve(self, **kwargs):
            del kwargs
            raise RuntimeError("injected retrieval failure")

    clinic.cooperative_memory_service = BrokenRetrieval()
    result = clinic.submit_player_contribution(contribution(player_id, opened, "safe_retrieval"))

    assert result.status.value == "action_executed"
    assert result.memory_retrieval_status.value == "failed_safe"
    assert agent.inputs[-1].memory_context is None


def test_world_commit_is_not_rolled_back_when_index_fails(tmp_path):
    clinic, repository, _, _ = memory_clinic(tmp_path, index_override=FailingIndex())
    player_id, opened = open_clinic(clinic)

    result = clinic.submit_player_contribution(contribution(player_id, opened, "index_pending"))

    assert result.status.value == "action_executed"
    assert result.memory_commit_status == "index_pending"
    assert result.memory_commit_error_code == "memory_index_failed"
    assert clinic.store.load_case_session(opened.session_id).revision == 1
    assert repository.list_memories(player_id=player_id)
    assert repository.list_player_embeddings(player_id=player_id) == ()


def test_rejected_action_cannot_create_fact_memory(tmp_path):
    clinic, repository, _, _ = memory_clinic(tmp_path)
    player_id, opened = open_clinic(clinic)

    receipt = clinic._service(player_id).submit_action_with_receipt(SubmitActionInput(
        player_id=player_id,
        case_id=opened.case_id,
        session_id=opened.session_id,
        action=AgentAction(
            action_id="rejected_talk",
            action_type=AgentActionType.RESPOND,
            dialogue="这只是一个未执行 proposal。",
            confidence=0.5,
        ),
    ))

    assert receipt.result.ok is False
    assert receipt.events == ()
    assert receipt.memory_commit_status == "disabled"
    assert repository.list_memories(player_id=player_id) == ()


def test_same_session_is_excluded_but_other_session_can_retrieve(tmp_path):
    clinic, repository, adapter, _ = memory_clinic(tmp_path)
    player_id, opened = open_clinic(clinic)
    written = clinic.submit_player_contribution(contribution(player_id, opened, "scope_write"))
    observation = clinic.resume_case(player_id, opened.case_id, opened.session_id).observation
    service = clinic.cooperative_memory_service

    same = service.retrieve(
        turn_id="same_session", player_id=player_id,
        current_session_id=opened.session_id, observation=observation,
    )
    historical = service.retrieve(
        turn_id="later_session", player_id=player_id,
        current_session_id="different_session", observation=observation,
    )

    assert same.selected_memory_ids == ()
    assert historical.selected_memory_ids == written.written_memory_ids
    assert historical.memories[0].public_summary
    assert repository.list_embeddings(
        player_id=player_id, embedding_space_id=adapter.embedding_space_id
    )


def test_runtime_long_query_retrieves_old_memory_and_excludes_current_session(
    tmp_path, qualified_player_state
):
    clinic, repository, adapter, _ = memory_clinic(tmp_path)
    player_id, opened = open_clinic(clinic)
    first = clinic.submit_player_contribution(
        contribution(player_id, opened, "runtime_current_memory")
    )
    current_memory_id = first.written_memory_ids[0]
    case = clinic.base_catalog.get(opened.case_id)
    player = qualified_player_state.model_copy(update={"player_id": player_id})
    _, historical_results = reference_case_results(
        case, player, session_id="session_phase_b_historical"
    )
    before, result = historical_results[0]
    source, memory = DeterministicMemoryProjector().project_committed_event(
        event=result.events[0], case=case, player=player,
        session=result.session, source_revision=before.revision + 1,
    )
    repository.write_projection(source, memory)
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=player_id
    )
    state = clinic.store.load_cooperative_agent_state(opened.session_id)
    long_text = "公开长上下文" * 250
    long_state = state.model_copy(update={
        "current_goal": state.current_goal.model_copy(
            update={"public_description": "GOAL_SENTINEL" + long_text}
        ),
        "current_plan": state.current_plan.model_copy(update={
            "steps": tuple(
                item.model_copy(update={"public_summary": "CURRENT_STEP_SENTINEL" + long_text})
                for item in state.current_plan.steps
            )
        }),
        "last_plan_evaluation": state.last_plan_evaluation.model_copy(
            update={"public_summary": long_text}
        ),
        "revision": state.revision + 1,
    })
    clinic.store.save_cooperative_agent_state(long_state, expected_revision=state.revision)
    agent = KeepExistingPlanAgent()
    clinic.game_npc_agent = agent

    outcome = clinic.submit_player_contribution(
        contribution(player_id, opened, "runtime_long_query").model_copy(
            update={"text": "PLAYER_INTENT_SENTINEL" + long_text}
        )
    )

    assert outcome.memory_retrieval_status.value != "failed_safe"
    assert outcome.memory_usage_trace.candidate_memory_ids == (memory.memory_id,)
    assert current_memory_id not in outcome.memory_usage_trace.candidate_memory_ids
    assert agent.inputs[0].memory_context.candidate_memory_ids == (memory.memory_id,)


def test_player_scope_prevents_cross_player_retrieval(tmp_path):
    clinic, _, _, _ = memory_clinic(tmp_path)
    player_a, opened = open_clinic(clinic)
    clinic.submit_player_contribution(contribution(player_a, opened, "player_a_write"))
    player_b = clinic.create_player("另一个玩家").player_summary.player_id

    context = clinic.cooperative_memory_service.retrieve(
        turn_id="player_b_turn", player_id=player_b,
        current_session_id="other_session",
        observation=clinic.resume_case(player_a, opened.case_id, opened.session_id).observation,
    )

    assert context.candidate_memory_ids == ()
    assert context.selected_memory_ids == ()


def test_llm_defaults_to_semantic_but_offline_defaults_to_disabled():
    llm = clinic_server.build_parser().parse_args(["--npc-mode", "llm"])
    offline = clinic_server.build_parser().parse_args(["--npc-mode", "offline"])
    assert (llm.memory_mode or ("semantic" if llm.npc_mode == "llm" else "disabled")) == "semantic"
    assert (offline.memory_mode or ("semantic" if offline.npc_mode == "llm" else "disabled")) == "disabled"


def test_semantic_startup_failure_does_not_fall_back_to_fake(tmp_path, monkeypatch):
    args = clinic_server.build_parser().parse_args([
        "--npc-mode", "offline", "--memory-mode", "semantic"
    ])

    def fail_load(self):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(clinic_server.BgeM3LocalEmbeddingAdapter, "load", fail_load)
    with pytest.raises(RuntimeError, match="model unavailable"):
        clinic_server.build_production_memory(
            args, state_dir=tmp_path, store=JsonStateStore(tmp_path)
        )
