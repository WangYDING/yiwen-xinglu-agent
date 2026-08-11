from xuanyi_npc.application.structured_memory import StructuredTeachingMemoryProjector
from xuanyi_npc.storage import SQLiteMemoryRepository
from tests.r1_helpers import FixedClock


def test_only_public_committed_r4_summaries_are_projected(tmp_path):
    repository = SQLiteMemoryRepository(tmp_path / "memory.sqlite3")
    repository.initialize()
    projector = StructuredTeachingMemoryProjector(repository)
    memory_id = projector.project_r4_event(
        player_id="player_r4_memory", source_session_id="exam_session_public",
        source_sequence=9, source_revision=9, occurred_at=FixedClock().now(),
        event_kind="exam", source_reference_id="exam_attempt_public",
        public_summary="正式考试已经通过。", reason_code="exam_passed_public",
    )
    record = repository.get_memory(player_id="player_r4_memory", memory_id=memory_id)
    assert "正式考试已经通过" in record.content
    assert "correct_option" not in record.model_dump_json()
    assert "minimum_proficiency" not in record.model_dump_json()
