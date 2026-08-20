from xuanyi_npc.application import (
    BasicCosineMemoryRetriever,
    GameNPCMemoryProjectionPolicy,
    GameNPCMemoryRetrievalConfig,
    GameNPCMemoryRetrievalService,
    MemoryIndexService,
)
from xuanyi_npc.application.cooperative_runtime import CooperativeRuntime, CooperativeTurnInput
from xuanyi_npc.memory import DeterministicFakeEmbedding, MemoryRetrievalConfig

from .test_m3_cooperative_runtime_memory import (
    MemoryAwarePlanningAgent,
    RuntimeMemoryService,
    contribution,
    opened_case,
)
from .test_m4_reflection_lifecycle import (
    ScriptedAdapter,
    lifecycle_service,
    lifecycle_trigger,
    public_inputs,
    repository_at,
)


def test_experience_reflect_remember_retrieve_changes_legal_tool_priority(tmp_path):
    baseline_service, baseline_player, baseline_opened = opened_case(tmp_path / "baseline")
    future_service, future_player, future_opened = opened_case(tmp_path / "future")

    repository = repository_at(tmp_path / "memory")
    trigger = lifecycle_trigger()
    outcome, assessment, reflection = public_inputs(trigger)
    lifecycle = lifecycle_service(
        repository, ScriptedAdapter(reflection.model_dump_json())
    ).process(
        trigger=trigger,
        player_id=future_player,
        tool_outcomes=(outcome,),
        assessments=(assessment,),
    )
    assert len(lifecycle.written_memory_ids) == 1

    adapter = DeterministicFakeEmbedding()
    MemoryIndexService(repository=repository, adapter=adapter).index_player(
        player_id=future_player
    )
    retrieval = GameNPCMemoryRetrievalService(
        retriever=BasicCosineMemoryRetriever(repository=repository, adapter=adapter),
        retrieval_config=MemoryRetrievalConfig(
            top_k=10,
            min_similarity=-1.0,
            embedding_space_id=adapter.embedding_space_id,
            query_template_version="memory_query_v1",
        ),
        projection_policy=GameNPCMemoryProjectionPolicy(repository=repository),
        projection_config=GameNPCMemoryRetrievalConfig(min_relevance=-1.0),
    )

    baseline = CooperativeRuntime(
        service=baseline_service,
        agent=MemoryAwarePlanningAgent(mode="second_tool_when_memory"),
        memory_service=RuntimeMemoryService(),
    ).handle(
        CooperativeTurnInput(
            contribution=contribution(
                baseline_player, baseline_opened.session_id, "turn_ab_baseline"
            )
        )
    )
    influenced = CooperativeRuntime(
        service=future_service,
        agent=MemoryAwarePlanningAgent(mode="second_tool_when_memory"),
        memory_service=retrieval,
    ).handle(
        CooperativeTurnInput(
            contribution=contribution(
                future_player, future_opened.session_id, "turn_ab_memory"
            )
        )
    )
    assert baseline.selected_tool != influenced.selected_tool
    assert influenced.memory_usage_trace.accepted_used_memory_ids == (
        lifecycle.written_memory_ids[0],
    )
    assert influenced.memory_usage_trace.tool_priority_influenced is True
    assert baseline.authority_mode == influenced.authority_mode
    assert len(
        future_service.state_store.load_case_session(
            future_opened.session_id
        ).action_history
    ) == 1


def test_rejected_reflection_does_not_pollute_future_behavior(tmp_path):
    service_a, player_a, opened_a = opened_case(tmp_path / "control_a")
    service_b, player_b, opened_b = opened_case(tmp_path / "control_b")
    baseline = CooperativeRuntime(
        service=service_a,
        agent=MemoryAwarePlanningAgent(mode="irrelevant"),
        memory_service=RuntimeMemoryService(),
    ).handle(
        CooperativeTurnInput(
            contribution=contribution(player_a, opened_a.session_id, "turn_control_a")
        )
    )
    no_pollution = CooperativeRuntime(
        service=service_b,
        agent=MemoryAwarePlanningAgent(mode="irrelevant"),
        memory_service=RuntimeMemoryService(),
    ).handle(
        CooperativeTurnInput(
            contribution=contribution(player_b, opened_b.session_id, "turn_control_b")
        )
    )
    assert no_pollution.selected_tool == baseline.selected_tool
    assert no_pollution.memory_usage_trace.accepted_used_memory_ids == ()
