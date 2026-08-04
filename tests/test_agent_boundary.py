from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from xuanyi_npc.application import AgentContextFilter, CaseObservation, PlayerView
from xuanyi_npc.config import (
    AgentVariant,
    AgentVariantConfig,
    ContextStrategy,
    CurriculumStrategy,
    MemoryRetrievalStrategy,
    ReflectionStrategy,
    V0_CONFIG,
    V1_CONFIG,
    V2_CONFIG,
)
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseDefinition,
    CaseSessionState,
    ExecuteTreatmentCommand,
    InvestigationCommand,
    PlayerState,
    SubmitDiagnosisCommand,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.engine import CaseEngine


FIXED_TIME = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)


def test_player_view_only_contains_unlocked_skills(player_state: PlayerState) -> None:
    view = AgentContextFilter().player_view(player_state)
    serialized = view.model_dump_json()
    skill_ids = {skill.skill_id for skill in view.available_skills}

    assert "observe_qi" not in skill_ids
    assert "prerequisite_ids" not in serialized
    assert "affinity" not in serialized
    assert "trust" not in serialized
    assert "recognition" not in serialized


def test_initial_case_observation_hides_truth_and_future_clues(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    session = CaseSessionState(
        session_id="session_safe_view",
        case_id=case_definition.case_id,
        player_id=qualified_player_state.player_id,
    )
    observation = AgentContextFilter().case_observation(
        case_definition,
        qualified_player_state,
        session,
    )
    serialized = observation.model_dump_json()
    available_ids = {
        item.investigation_id for item in observation.available_investigations
    }
    candidate_ids = {
        item.diagnosis_id for item in observation.diagnosis_candidates
    }

    assert available_ids == {
        "ask_about_memory",
        "inspect_umbrella",
        "observe_scholar",
    }
    assert observation.discovered_clues == ()
    assert observation.available_treatments == ()
    assert candidate_ids == {
        "evil_spirit_attack",
        "exam_exhaustion",
        "rain_vow_breach",
    }
    assert all(
        candidate.public_description
        for candidate in observation.diagnosis_candidates
    )
    assert all(
        set(candidate.model_dump()) == {"diagnosis_id", "public_description"}
        for candidate in observation.diagnosis_candidates
    )
    assert all(
        option.public_description
        for option in observation.available_investigations
    )
    assert case_definition.root_cause not in serialized
    assert "root_cause" not in serialized
    assert "causal_chain" not in serialized
    assert "hidden_information" not in serialized
    assert "valid_diagnosis_ids" not in serialized
    assert "is_correct" not in serialized
    assert "diagnosis_correct" not in serialized
    assert "scoring" not in serialized
    assert "required_clue_ids" not in serialized
    assert "minimum_skill_level" not in serialized
    assert "broken_promise" not in serialized
    assert "ask_about_promise" not in serialized


def test_case_observation_reveals_only_currently_available_actions(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = CaseSessionState(
        session_id="session_progressive_view",
        case_id=case_definition.case_id,
        player_id=qualified_player_state.player_id,
    )
    investigation = next(
        item
        for item in case_definition.investigations
        if item.investigation_id == "inspect_umbrella"
    )
    session = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        InvestigationCommand(
            investigation_id=investigation.investigation_id,
            action_type=investigation.action_type,
            target_id=investigation.target_id,
            occurred_at=FIXED_TIME,
        ),
    ).session
    observation = AgentContextFilter().case_observation(
        case_definition,
        qualified_player_state,
        session,
    )

    assert "observe_contract_trace" in {
        item.investigation_id for item in observation.available_investigations
    }
    assert {clue.clue_id for clue in observation.discovered_clues} == {
        "cold_window_draft",
        "umbrella_night_water",
    }


def test_treatment_view_hides_outcome_and_hidden_requirements(
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    engine = CaseEngine()
    session = CaseSessionState(
        session_id="session_treatment_view",
        case_id=case_definition.case_id,
        player_id=qualified_player_state.player_id,
    )
    umbrella = next(
        item
        for item in case_definition.investigations
        if item.investigation_id == "inspect_umbrella"
    )
    session = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        InvestigationCommand(
            investigation_id=umbrella.investigation_id,
            action_type=umbrella.action_type,
            target_id=umbrella.target_id,
            occurred_at=FIXED_TIME,
        ),
    ).session
    session = engine.execute(
        case_definition,
        qualified_player_state,
        session,
        SubmitDiagnosisCommand(
            diagnosis_id="evil_spirit_attack",
            occurred_at=FIXED_TIME,
        ),
    ).session
    observation = AgentContextFilter().case_observation(
        case_definition,
        qualified_player_state,
        session,
    )
    serialized = observation.model_dump_json()

    assert {item.treatment_id for item in observation.available_treatments} == {
        "burn_old_umbrella",
        "seal_old_umbrella",
    }
    assert all(
        treatment.public_description
        for treatment in observation.available_treatments
    )
    assert "outcome" not in serialized
    assert "resolved" not in serialized
    assert "worsened" not in serialized
    assert "required_clue_ids" not in serialized
    assert "return_token_and_fulfill_vow" not in serialized


def test_views_and_agent_action_round_trip(
    case_definition: CaseDefinition,
    player_state: PlayerState,
) -> None:
    context_filter = AgentContextFilter()
    player_view = context_filter.player_view(player_state)
    case_view = context_filter.case_observation(
        case_definition,
        player_state,
        CaseSessionState(
            session_id="session_round_trip_view",
            case_id=case_definition.case_id,
            player_id=player_state.player_id,
        ),
    )
    action = AgentAction(
        action_id="agent_action_observe",
        action_type=AgentActionType.USE_TOOL,
        dialogue="先察其形。",
        tool_call=ToolCallRequest(
            name=ToolName.OBSERVE_PATIENT,
            arguments={"investigation_id": "observe_scholar"},
        ),
        confidence=0.9,
    )

    assert PlayerView.model_validate_json(player_view.model_dump_json()) == player_view
    assert CaseObservation.model_validate_json(case_view.model_dump_json()) == case_view
    assert AgentAction.model_validate_json(action.model_dump_json()) == action


@pytest.mark.parametrize(
    "model, extra_field",
    [
        (
            AgentAction(
                action_id="agent_action_safe",
                action_type=AgentActionType.RESPOND,
                dialogue="继续观察。",
                confidence=0.8,
            ),
            ("world_truth", "伪造真相"),
        ),
        (
            PlayerView(
                player_id="player_safe_view",
                display_name="学徒",
                teaching_stage="novice",
            ),
            ("trust", 100),
        ),
    ],
)
def test_agent_boundary_rejects_unknown_fields(
    model: AgentAction | PlayerView,
    extra_field: tuple[str, object],
) -> None:
    data = model.model_dump(mode="json")
    data[extra_field[0]] = extra_field[1]

    with pytest.raises(ValidationError):
        type(model).model_validate(data)


def test_named_variant_boundaries_are_explicit() -> None:
    assert V0_CONFIG.variant is AgentVariant.V0
    assert V0_CONFIG.agent_context_filter is True
    assert V0_CONFIG.context_strategy is ContextStrategy.SHORT_TERM
    assert V0_CONFIG.memory_retrieval_strategy is MemoryRetrievalStrategy.NONE
    assert V0_CONFIG.curriculum_strategy is CurriculumStrategy.FIXED
    assert V0_CONFIG.reflection_strategy is ReflectionStrategy.DISABLED
    assert V0_CONFIG.long_term_memory_enabled is False
    assert V0_CONFIG.adaptive_teaching_enabled is False
    assert V0_CONFIG.reflection_enabled is False

    assert V1_CONFIG.long_term_memory_enabled is True
    assert V1_CONFIG.agent_context_filter is True
    assert (
        V1_CONFIG.memory_retrieval_strategy
        is MemoryRetrievalStrategy.VECTOR_TOP_K
    )
    assert V1_CONFIG.adaptive_teaching_enabled is False
    assert V1_CONFIG.reflection_enabled is False

    assert V2_CONFIG.long_term_memory_enabled is True
    assert V2_CONFIG.agent_context_filter is True
    assert (
        V2_CONFIG.memory_retrieval_strategy
        is MemoryRetrievalStrategy.MULTI_FACTOR
    )
    assert V2_CONFIG.adaptive_teaching_enabled is True
    assert V2_CONFIG.reflection_enabled is True


def test_v0_cannot_silently_enable_future_capabilities() -> None:
    with pytest.raises(ValidationError, match="v0 boundary"):
        AgentVariantConfig(
            variant=AgentVariant.V0,
            agent_context_filter=True,
            context_strategy=ContextStrategy.PERSISTENT_MEMORY,
            memory_retrieval_strategy=MemoryRetrievalStrategy.MULTI_FACTOR,
            curriculum_strategy=CurriculumStrategy.ADAPTIVE,
            reflection_strategy=ReflectionStrategy.ENABLED,
            structured_actions=True,
            basic_tool_calls=True,
        )


def test_product_variant_cannot_disable_context_filter() -> None:
    with pytest.raises(ValidationError, match="AgentContextFilter"):
        AgentVariantConfig(
            variant=AgentVariant.V0,
            agent_context_filter=False,
            context_strategy=ContextStrategy.SHORT_TERM,
            memory_retrieval_strategy=MemoryRetrievalStrategy.NONE,
            curriculum_strategy=CurriculumStrategy.FIXED,
            reflection_strategy=ReflectionStrategy.DISABLED,
            structured_actions=True,
            basic_tool_calls=True,
        )
