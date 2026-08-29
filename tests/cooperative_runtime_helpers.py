from pathlib import Path

from xuanyi_npc.application.multicase import CaseCatalog, CampaignRuleSet, MultiCaseEpisodeService
from xuanyi_npc.storage import JsonStateStore


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"


class FixedPlayerIds:
    def new_player_id(self) -> str:
        return "player_cooperative_test"


class SequentialSessionIds:
    def __init__(self) -> None:
        self._next = 0

    def new_session_id(self) -> str:
        self._next += 1
        return f"session_cooperative_test_{self._next}"


def build_service(state_dir: Path) -> MultiCaseEpisodeService:
    catalog = CaseCatalog(ROOT / "cases")
    rules = CampaignRuleSet.load(ROOT / "campaign" / "cross_episode_rules_v2.json", catalog)
    return MultiCaseEpisodeService(
        state_store=JsonStateStore(state_dir),
        case_catalog=catalog,
        player_id_factory=FixedPlayerIds(),
        session_id_factory=SequentialSessionIds(),
        campaign_rules=rules,
    )
