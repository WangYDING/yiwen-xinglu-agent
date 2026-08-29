import os
from pathlib import Path

import pytest


_SRC = str(Path(__file__).parents[1] / "src")
os.environ["PYTHONPATH"] = _SRC + os.pathsep + os.environ.get("PYTHONPATH", "")

from xuanyi_npc.domain import (
    CaseDefinition,
    PlayerState,
    SkillState,
)


CASE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "xuanyi_npc"
    / "resources"
    / "cases"
    / "old_paper_umbrella.json"
)


@pytest.fixture()
def case_definition() -> CaseDefinition:
    return CaseDefinition.model_validate_json(CASE_PATH.read_text(encoding="utf-8"))


@pytest.fixture()
def player_state() -> PlayerState:
    return PlayerState(
        player_id="player_apprentice",
        display_name="无名学徒",
        skills={
            "observe_form": SkillState(
                skill_id="observe_form",
                proficiency=25,
                unlocked=True,
            ),
            "ask_cause": SkillState(
                skill_id="ask_cause",
                proficiency=20,
                unlocked=True,
            ),
            "inspect_object": SkillState(
                skill_id="inspect_object",
                proficiency=15,
                unlocked=True,
                prerequisite_ids={"observe_form"},
            ),
            "observe_qi": SkillState(
                skill_id="observe_qi",
                proficiency=0,
                unlocked=False,
                prerequisite_ids={"observe_form", "inspect_object"},
            ),
        },
    )


@pytest.fixture()
def qualified_player_state(player_state: PlayerState) -> PlayerState:
    data = player_state.model_dump(mode="python")
    data["skills"]["observe_qi"]["unlocked"] = True
    data["skills"]["observe_qi"]["proficiency"] = 25
    return PlayerState.model_validate(data)
