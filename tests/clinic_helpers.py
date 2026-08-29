import http.client
from pathlib import Path
from urllib.parse import urlencode

from xuanyi_npc.agents import DeterministicCooperativeNPC
from xuanyi_npc.application.clinic import ClinicService
from xuanyi_npc.application.multicase import CaseCatalog
from xuanyi_npc.storage import JsonStateStore
from tests.r1_helpers import FixedClock, FixedPlayerIds, FixedSessionIds


ROOT = Path(__file__).parents[1] / "src" / "xuanyi_npc" / "resources"


def build_clinic(tmp_path):
    return ClinicService(
        store=JsonStateStore(tmp_path),
        base_catalog=CaseCatalog(ROOT / "cases"),
        campaign_path=ROOT / "campaign" / "cross_episode_rules_v2.json",
        clock=FixedClock(),
        player_id_factory=FixedPlayerIds(),
        session_id_factory=FixedSessionIds(),
        game_npc_agent=DeterministicCooperativeNPC(),
    )


def request(port, method, path, fields=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = None if fields is None else urlencode(fields)
    headers = {} if body is None else {"Content-Type": "application/x-www-form-urlencoded"}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read().decode("utf-8")
    response_headers = dict(response.getheaders())
    connection.close()
    return response.status, response_headers, payload
