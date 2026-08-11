from xuanyi_npc.agents import DeterministicFakeMentor
from xuanyi_npc.application import MentorTeachingService, TeachingRequest
from tests.r1_helpers import create_player
from tests.r2_helpers import FixedTeachingIds, build_teaching, start_teaching
import subprocess
import sys
from pathlib import Path


def test_service_restart_restores_hint_budget_and_binding(tmp_path):
    case_service, teaching, _ = build_teaching(tmp_path)
    player_id = create_player(case_service)
    started, state = start_teaching(case_service, teaching, player_id)
    request = TeachingRequest(player_id=player_id, teaching_session_id=state.teaching_session_id)
    first = teaching.request_hint(request)
    restarted = MentorTeachingService(
        case_service=case_service,
        mentor_agent=DeterministicFakeMentor(),
        id_factory=FixedTeachingIds(),
    )
    restored = restarted.resume(request)
    assert restored.ok
    assert restored.state.case_session_id == started.session_id
    assert restored.state.lesson_id == "evidence_before_diagnosis_v1"
    assert restored.state.used_hint_ids == ("hint_1",)
    assert restored.state.revision == first.state.revision


def test_two_independent_processes_resume_and_complete_same_teaching_session(tmp_path):
    first_code = r'''import json, sys
from pathlib import Path
from tests.r1_helpers import create_player
from tests.r2_helpers import build_teaching, start_teaching
from xuanyi_npc.application import TeachingRequest
root=Path(sys.argv[1]); service, teaching, store=build_teaching(root)
player=create_player(service); started, state=start_teaching(service, teaching, player)
hint=teaching.request_hint(TeachingRequest(player_id=player, teaching_session_id=state.teaching_session_id))
(root/'handoff.json').write_text(json.dumps({'player':player,'case':started.session_id,'teaching':state.teaching_session_id}), encoding='utf-8')
assert hint.ok and hint.state.used_hint_ids == ('hint_1',)
'''
    second_code = r'''import json, sys
from pathlib import Path
from tests.r2_helpers import build_teaching
from tests.test_r2_assessment_outcomes import finish_bound
from xuanyi_npc.application import TeachingRequest
root=Path(sys.argv[1]); ids=json.loads((root/'handoff.json').read_text(encoding='utf-8'))
service, teaching, store=build_teaching(root); request=TeachingRequest(player_id=ids['player'], teaching_session_id=ids['teaching'])
restored=teaching.resume(request); assert restored.state.used_hint_ids == ('hint_1',)
finish_bound(service, store, ids['player'], ids['case'], 'rain_vow_breach', 'return_token_and_fulfill_vow')
done=teaching.observe_case_completion(request)
assert done.ok and done.state.phase.value == 'completed'
assert len(store.list_teaching_sessions()) == 1
'''
    first = subprocess.run(
        [sys.executable, "-c", first_code, str(tmp_path)],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False,
    )
    assert first.returncode == 0, first.stderr
    second = subprocess.run(
        [sys.executable, "-c", second_code, str(tmp_path)],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False,
    )
    assert second.returncode == 0, second.stderr
