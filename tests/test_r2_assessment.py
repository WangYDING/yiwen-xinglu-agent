import pytest

from xuanyi_npc.application import AssessmentBuilder, AssessmentSourceError
from tests.r1_helpers import build_service, create_player


def test_assessment_rejects_uncompleted_case(tmp_path):
    service, store = build_service(tmp_path)
    player_id = create_player(service)
    from xuanyi_npc.application import StartEpisodeInput
    started = service.start_episode(StartEpisodeInput(player_id=player_id, case_id="old_paper_umbrella"))
    session = store.load_case_session(started.session_id)
    apprenticeship = store.load_apprenticeship(player_id)
    from xuanyi_npc.domain import LessonDefinition
    from xuanyi_npc.resources.runtime import read_runtime_text
    lesson = LessonDefinition.model_validate_json(
        read_runtime_text("curriculum/evidence_before_diagnosis_v1.json")
    )
    with pytest.raises(AssessmentSourceError):
        AssessmentBuilder().build(
            session=session,
            case=service.case_catalog.get(session.case_id),
            apprenticeship=apprenticeship,
            lesson=lesson,
            used_hint_ids=(),
        )
