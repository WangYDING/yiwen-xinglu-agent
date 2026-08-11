from pathlib import Path

from xuanyi_npc.agents import DeterministicFakeMentor
from xuanyi_npc.application import (
    CreateTeachingSessionInput,
    MentorTeachingService,
    TeachingRequest,
)
from xuanyi_npc.domain import CaseActionType
from tests.r1_helpers import TOOLS, action, build_service, create_player
from xuanyi_npc.application import StartEpisodeInput, SubmitActionInput


class FixedTeachingIds:
    def __init__(self) -> None:
        self.index = 0

    def new_teaching_session_id(self) -> str:
        self.index += 1
        return f"teaching_r2_{self.index}"


def build_teaching(state_dir: Path):
    case_service, store = build_service(state_dir)
    teaching = MentorTeachingService(
        case_service=case_service,
        mentor_agent=DeterministicFakeMentor(),
        id_factory=FixedTeachingIds(),
    )
    return case_service, teaching, store


def start_teaching(case_service, teaching, player_id):
    started = case_service.start_episode(
        StartEpisodeInput(player_id=player_id, case_id="old_paper_umbrella")
    )
    created = teaching.create(
        CreateTeachingSessionInput(
            player_id=player_id,
            case_session_id=started.session_id,
        )
    )
    assert created.ok
    return started, created.state


def investigate_all(case_service, player_id, session_id):
    case = case_service.case_catalog.get("old_paper_umbrella")
    result = None
    for index, investigation in enumerate(case.investigations, start=1):
        result = case_service.submit_action(
            SubmitActionInput(
                player_id=player_id,
                case_id=case.case_id,
                session_id=session_id,
                action=action(
                    TOOLS[investigation.action_type],
                    {"investigation_id": investigation.investigation_id},
                    index,
                ),
            )
        )
        assert result.ok
    return result
