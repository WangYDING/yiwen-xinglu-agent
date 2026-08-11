import json
import subprocess
import sys
from pathlib import Path

from xuanyi_npc.agents import DeterministicFakeMentor
from xuanyi_npc.application import MentorTeachingService, TeachingRequest
from xuanyi_npc.storage import JsonStateStore, SQLiteMemoryRepository, StorageError
from tests.r1_helpers import build_service, create_player
from tests.r2_helpers import FixedTeachingIds, start_teaching
from tests.test_r2_assessment_outcomes import finish_bound


class ToggleTeachingPlanStore(JsonStateStore):
    fail_teaching_plan = False

    def save_teaching_plan(self, state):
        if self.fail_teaching_plan:
            raise StorageError("injected teaching plan failure")
        return super().save_teaching_plan(state)


class ToggleMemoryRepository(SQLiteMemoryRepository):
    fail_projection = False

    def write_projection(self, source, memory):
        if self.fail_projection:
            raise RuntimeError("injected memory failure")
        return super().write_projection(source, memory)


def build_faultable(root):
    store = ToggleTeachingPlanStore(root)
    service, _ = build_service(root, store=store)
    memory = ToggleMemoryRepository(root / "memories.sqlite3")
    teaching = MentorTeachingService(
        case_service=service,
        mentor_agent=DeterministicFakeMentor(),
        id_factory=FixedTeachingIds(),
        memory_repository=memory,
    )
    return service, teaching, store, memory


def completed_request(service, teaching, store, player_id):
    started, state = start_teaching(service, teaching, player_id)
    finish_bound(
        service,
        store,
        player_id,
        started.session_id,
        "rain_vow_breach",
        "return_token_and_fulfill_vow",
    )
    return TeachingRequest(
        player_id=player_id,
        teaching_session_id=state.teaching_session_id,
    )


def test_teaching_plan_failure_is_pending_and_reconcile_is_idempotent(tmp_path):
    service, teaching, store, _ = build_faultable(tmp_path)
    player_id = create_player(service)
    request = completed_request(service, teaching, store, player_id)
    store.fail_teaching_plan = True
    pending = teaching.observe_case_completion(request)
    assert pending.error_code == "teaching_plan_pending"
    assert pending.state.phase.value == "completed"
    store.fail_teaching_plan = False
    completed = teaching.reconcile(request)
    assert completed.ok
    snapshot = store.load_teaching_plan(player_id).model_dump_json()
    repeated = teaching.reconcile(request)
    assert repeated.ok
    assert store.load_teaching_plan(player_id).model_dump_json() == snapshot


def test_memory_failure_is_pending_and_reconcile_does_not_duplicate_plan(tmp_path):
    service, teaching, store, memory = build_faultable(tmp_path)
    player_id = create_player(service)
    request = completed_request(service, teaching, store, player_id)
    memory.fail_projection = True
    pending = teaching.observe_case_completion(request)
    assert pending.error_code == "memory_projection_pending"
    plan_snapshot = store.load_teaching_plan(player_id).model_dump_json()
    memory.fail_projection = False
    completed = teaching.reconcile(request)
    assert completed.ok
    assert store.load_teaching_plan(player_id).model_dump_json() == plan_snapshot
    ids = [
        item.memory_id for item in memory.list_memories(player_id=player_id)
    ]
    assert ids and len(ids) == len(set(ids))


def test_three_case_plan_and_memory_restore_across_three_processes(tmp_path):
    first_code = r'''import json,sys
from pathlib import Path
from xuanyi_npc.agents import DeterministicFakeMentor
from xuanyi_npc.application import MentorTeachingService
from tests.r1_helpers import build_service,create_player
from tests.test_r3_adaptive_teaching import complete_taught_case
root=Path(sys.argv[1]); service,store=build_service(root); teaching=MentorTeachingService(case_service=service,mentor_agent=DeterministicFakeMentor())
player=create_player(service); complete_taught_case(service,teaching,store,player,'old_paper_umbrella')
(root/'r3_handoff.json').write_text(json.dumps({'player':player}),encoding='utf-8')
assert store.load_teaching_plan(player).current_recommendation.recommendation_id=='provenance_before_intent_v1'
'''
    second_code = r'''import json,sys
from pathlib import Path
from xuanyi_npc.agents import DeterministicFakeMentor
from xuanyi_npc.application import MentorTeachingService
from tests.r1_helpers import build_service
from tests.test_r3_adaptive_teaching import complete_taught_case
root=Path(sys.argv[1]); player=json.loads((root/'r3_handoff.json').read_text(encoding='utf-8'))['player']; service,store=build_service(root); teaching=MentorTeachingService(case_service=service,mentor_agent=DeterministicFakeMentor())
service.session_id_factory=type('Ids',(),{'new_session_id':lambda self:'session_gray_restore'})()
created,_=complete_taught_case(service,teaching,store,player,'gray_hearth_inn'); assert '历史记录显示' in created.mentor_action.message
assert store.load_teaching_plan(player).current_recommendation.recommendation_id=='corroborate_before_handoff_v1'
'''
    third_code = r'''import json,sys
from pathlib import Path
from xuanyi_npc.agents import DeterministicFakeMentor
from xuanyi_npc.application import MentorTeachingService
from tests.r1_helpers import build_service
from tests.test_r3_adaptive_teaching import complete_taught_case
root=Path(sys.argv[1]); player=json.loads((root/'r3_handoff.json').read_text(encoding='utf-8'))['player']; service,store=build_service(root); teaching=MentorTeachingService(case_service=service,mentor_agent=DeterministicFakeMentor())
service.session_id_factory=type('Ids',(),{'new_session_id':lambda self:'session_moon_restore'})()
created,_=complete_taught_case(service,teaching,store,player,'moon_well_echo'); assert '历史记录显示' in created.mentor_action.message
plan=store.load_teaching_plan(player); assert plan.current_recommendation.recommendation_id=='foundation_complete'; assert len(plan.events)==plan.revision
assert len(teaching.memory_repository.list_memories(player_id=player))>=6
'''
    for code in (first_code, second_code, third_code):
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path)],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
