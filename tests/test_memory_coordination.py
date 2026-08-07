from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from xuanyi_npc.agents import DoctorAgent, ScriptedFakeLLM
from xuanyi_npc.application import V1MemoryCoordinator
from xuanyi_npc.application.v0_runner import V0EpisodeConfig, V0EpisodeRunner
from xuanyi_npc.domain import (
    AgentAction,
    AgentActionType,
    CaseDefinition,
    CaseSessionState,
    PlayerState,
    ToolCallRequest,
    ToolName,
)
from xuanyi_npc.memory import (
    MemoryCommitStatus,
    MemoryStorageError,
    ProjectionWriteDisposition,
)
from xuanyi_npc.mcp_server import FROZEN_MCP_TOOL_NAMES
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository, StorageError

from .memory_helpers import reference_case_results


class FailingJsonStateStore(JsonStateStore):
    def save_case_session(self, state: CaseSessionState) -> Path:
        del state
        raise StorageError("injected state save failure")


class CountingProjectionRepository:
    def __init__(
        self,
        delegate: SQLiteMemoryRepository,
        *,
        fail_first: bool = False,
    ) -> None:
        self.delegate = delegate
        self.fail_first = fail_first
        self.calls = 0

    def write_projection(self, source, memory):
        self.calls += 1
        if self.fail_first:
            self.fail_first = False
            raise MemoryStorageError("injected projection failure")
        return self.delegate.write_projection(source, memory)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 8, 7, 14, 0, tzinfo=timezone.utc)


def one_investigation_action() -> str:
    return AgentAction(
        action_id="agent_step_001",
        action_type=AgentActionType.USE_TOOL,
        dialogue="执行 V0 调查。",
        tool_call=ToolCallRequest(
            name=ToolName.OBSERVE_PATIENT,
            arguments={"investigation_id": "observe_scholar"},
        ),
        confidence=1.0,
    ).model_dump_json()


def test_json_state_save_failure_produces_zero_sqlite_writes(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    memory_repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    memory_repository.initialize()
    counting = CountingProjectionRepository(memory_repository)
    _, results = reference_case_results(case_definition, qualified_player_state)
    before, result = results[0]
    coordinator = V1MemoryCoordinator(
        state_store=FailingJsonStateStore(tmp_path / "state"),
        memory_repository=counting,
    )

    with pytest.raises(StorageError):
        coordinator.commit_engine_result(
            case=case_definition,
            player=qualified_player_state,
            previous_session=before,
            result=result,
        )

    assert counting.calls == 0
    assert memory_repository.table_counts()["memory_events"] == 0
    assert memory_repository.table_counts()["memory_source_receipts"] == 0


def test_projection_failure_returns_pending_after_json_state_is_committed(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    state_store = JsonStateStore(tmp_path / "state")
    state_store.save_player(qualified_player_state)
    memory_repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    memory_repository.initialize()
    failing = CountingProjectionRepository(memory_repository, fail_first=True)
    _, results = reference_case_results(case_definition, qualified_player_state)
    before, result = results[0]
    coordinator = V1MemoryCoordinator(
        state_store=state_store,
        memory_repository=failing,
    )

    commit = coordinator.commit_engine_result(
        case=case_definition,
        player=qualified_player_state,
        previous_session=before,
        result=result,
    )

    assert commit.status is MemoryCommitStatus.MEMORY_PROJECTION_PENDING
    assert commit.error_code == "memory_storage_error"
    assert len(commit.pending_source_event_ids) == 1
    assert state_store.load_case_session(result.session.session_id) == result.session
    assert memory_repository.table_counts()["memory_events"] == 0


def test_explicit_reconciliation_fills_pending_memory_and_is_idempotent(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    state_store = JsonStateStore(tmp_path / "state")
    state_store.save_player(qualified_player_state)
    memory_repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    memory_repository.initialize()
    _, results = reference_case_results(case_definition, qualified_player_state)
    before, result = results[0]
    failing_coordinator = V1MemoryCoordinator(
        state_store=state_store,
        memory_repository=CountingProjectionRepository(
            memory_repository,
            fail_first=True,
        ),
    )
    pending = failing_coordinator.commit_engine_result(
        case=case_definition,
        player=qualified_player_state,
        previous_session=before,
        result=result,
    )
    assert pending.status is MemoryCommitStatus.MEMORY_PROJECTION_PENDING

    coordinator = V1MemoryCoordinator(
        state_store=state_store,
        memory_repository=memory_repository,
    )
    first = coordinator.reconcile_committed_session(
        case=case_definition,
        player_id=qualified_player_state.player_id,
        session_id=result.session.session_id,
    )
    second = coordinator.reconcile_committed_session(
        case=case_definition,
        player_id=qualified_player_state.player_id,
        session_id=result.session.session_id,
    )

    assert first.status is MemoryCommitStatus.COMPLETE
    assert first.projections[0].disposition is ProjectionWriteDisposition.CREATED
    assert second.status is MemoryCommitStatus.COMPLETE
    assert second.projections[0].disposition is ProjectionWriteDisposition.IDEMPOTENT
    assert memory_repository.table_counts()["memory_events"] == 1
    assert memory_repository.table_counts()["memory_source_receipts"] == 1


def test_reconciliation_refuses_missing_public_source_instead_of_inventing_content(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    state_store = JsonStateStore(tmp_path / "state")
    state_store.save_player(qualified_player_state)
    _, results = reference_case_results(case_definition, qualified_player_state)
    committed = results[0][1].session
    state_store.save_case_session(committed)
    case_data = case_definition.model_dump(mode="python")
    case_data["investigations"] = tuple(
        item
        for item in case_data["investigations"]
        if item["investigation_id"] != "observe_scholar"
    )
    changed_case = CaseDefinition.model_validate(case_data)
    memory_repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    memory_repository.initialize()
    coordinator = V1MemoryCoordinator(
        state_store=state_store,
        memory_repository=memory_repository,
    )

    result = coordinator.reconcile_committed_session(
        case=changed_case,
        player_id=qualified_player_state.player_id,
        session_id=committed.session_id,
    )

    assert result.status is MemoryCommitStatus.MEMORY_PROJECTION_PENDING
    assert result.error_code == "invalid_committed_source"
    assert memory_repository.table_counts()["memory_events"] == 0


def test_commit_rejects_an_old_event_masquerading_as_the_new_transition(
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    _, results = reference_case_results(case_definition, qualified_player_state)
    old_event = results[0][1].events[0]
    before, current_result = results[1]
    tampered = current_result.model_copy(update={"events": (old_event,)})
    memory_repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    memory_repository.initialize()
    coordinator = V1MemoryCoordinator(
        state_store=JsonStateStore(tmp_path / "state"),
        memory_repository=memory_repository,
    )

    with pytest.raises(ValueError, match="appended action records"):
        coordinator.commit_engine_result(
            case=case_definition,
            player=qualified_player_state,
            previous_session=before,
            result=tampered,
        )

    assert tuple((tmp_path / "state").rglob("*.json")) == ()
    assert memory_repository.table_counts()["memory_events"] == 0


def test_v0_runner_never_calls_memory_repository(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case_definition: CaseDefinition,
    qualified_player_state: PlayerState,
) -> None:
    def forbidden_repository_construction(*args, **kwargs):
        del args, kwargs
        raise AssertionError("V0 must not construct or access long-term memory")

    monkeypatch.setattr(
        SQLiteMemoryRepository,
        "__init__",
        forbidden_repository_construction,
    )
    fake = ScriptedFakeLLM([one_investigation_action()])
    runner = V0EpisodeRunner(
        DoctorAgent(fake),
        clock=FixedClock(),
        config=V0EpisodeConfig(max_steps=1),
    )
    initial = CaseSessionState(
        session_id="session_v0_no_memory",
        case_id=case_definition.case_id,
        player_id=qualified_player_state.player_id,
    )

    episode = runner.run(
        "episode_v0_no_memory",
        case_definition,
        qualified_player_state,
        initial,
        "执行一项固定课程调查。",
    )

    assert episode.final_session.revision == 1
    assert not (tmp_path / "memory.sqlite3").exists()


def test_agent_and_frozen_mcp_surface_still_have_no_permanent_memory_write() -> None:
    with pytest.raises(ValueError):
        ToolName("record_memory")
    assert "record_memory" not in FROZEN_MCP_TOOL_NAMES
    assert "correct_memory" not in FROZEN_MCP_TOOL_NAMES
    assert "delete_memory" not in FROZEN_MCP_TOOL_NAMES
