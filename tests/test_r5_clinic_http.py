import http.client
import re
import threading
from pathlib import Path
from urllib.parse import urlencode, urlparse

import pytest

from xuanyi_npc.clinic.server import ClinicHTTPServer
from tests.test_r5_clinic_service import build_clinic


def request(port, method, path, fields=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = None if fields is None else urlencode(fields)
    headers = {} if body is None else {"Content-Type": "application/x-www-form-urlencoded"}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read().decode("utf-8")
    headers = dict(response.getheaders())
    connection.close()
    return response.status, headers, payload


@pytest.fixture
def clinic_http(tmp_path):
    server = ClinicHTTPServer(("127.0.0.1", 0), build_clinic(tmp_path))
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    yield server.server_address[1], server
    server.shutdown(); server.server_close(); thread.join(timeout=3)
    assert not thread.is_alive()


def test_start_page_escapes_player_name_and_never_returns_traceback(clinic_http):
    port, server = clinic_http
    status, _, page = request(port, "GET", "/")
    token = re.search(r'name="operation_id" value="([^"]+)', page).group(1)
    status, headers, _ = request(port, "POST", "/players", {"display_name": "<script>alert(1)</script>", "operation_id": token})
    assert status == 303
    status, _, home = request(port, "GET", headers["Location"])
    assert "&lt;script&gt;" in home and "<script>alert" not in home
    assert "Traceback" not in home and "API Key" not in home


def test_primary_entry_presents_cooperative_investigation_relationship(clinic_http):
    port, _ = clinic_http
    status, _, start = request(port, "GET", "/")
    assert status == 200
    assert "异闻行录 · 志怪异案" in start
    assert "全部异案、人物与术法均为架空游戏内容" in start
    assert "问道医途" not in start and "全部病案" not in start
    assert "创建玩家档案" in start and "恢复调查档案" in start
    assert "自主 NPC" in start and "调查搭档" in start
    assert "创建弟子" not in start and "恢复弟子" not in start

    token = re.search(r'name="operation_id" value="([^"]+)', start).group(1)
    status, headers, _ = request(
        port,
        "POST",
        "/players",
        {"display_name": "同行者", "operation_id": token},
    )
    assert status == 303
    status, _, welcome = request(port, "GET", headers["Location"])
    assert status == 200
    assert "初次同行" in welcome and "游侠型自主 NPC" in welcome
    assert "调查搭档" in welcome and "与搭档同行，前往选案" in welcome
    assert "新收的弟子" not in welcome and "记下教诲" not in welcome


def test_home_navigation_and_retained_mentor_copy_have_clear_priority(clinic_http):
    port, server = clinic_http
    player_id = server.clinic_service.create_player("异案调查者").player_summary.player_id

    status, _, home = request(port, "GET", f"/clinic?player_id={player_id}")
    assert status == 200
    assert "调查档案" in home and "调查搭档与可选修习" in home
    assert "调查异案" in home and "教学 / 请教（可选）" in home
    assert "可调查异案" in home and "可选修习与传承" in home
    assert "导师与课程" not in home and "成长与师徒历程" not in home

    status, _, cases = request(port, "GET", f"/cases?player_id={player_id}")
    assert status == 200
    assert "志怪异案选案大厅" in cases and "调查建议" in cases
    assert "师父推荐" not in cases

    status, _, teaching = request(port, "GET", f"/teaching?player_id={player_id}")
    assert status == 200
    assert "教学 / 请教（保留支线）" in teaching
    assert "retained Mentor teaching" in teaching
    assert "不代表当前 Cooperative GameNPC 的主关系" in teaching

    status, _, assessment = request(port, "GET", f"/assessment?player_id={player_id}")
    assert status == 200
    assert "调查记录与阶段反馈" in assessment
    assert "成长与师徒历程" not in assessment


def test_post_refresh_is_idempotent_and_unknown_ids_are_safe(clinic_http):
    port, server = clinic_http
    _, _, page = request(port, "GET", "/")
    token = re.search(r'name="operation_id" value="([^"]+)', page).group(1)
    fields = {"display_name": "幂等弟子", "operation_id": token}
    first = request(port, "POST", "/players", fields)
    second = request(port, "POST", "/players", fields)
    assert first[0] == second[0] == 303 and first[1]["Location"] == second[1]["Location"]
    assert len(server.clinic_service.list_players()) == 1
    status, _, page = request(port, "GET", "/clinic?player_id=../../secret")
    assert status == 400 and "Traceback" not in page


def test_server_refuses_non_loopback_binding(tmp_path):
    with pytest.raises(ValueError):
        ClinicHTTPServer(("0.0.0.0", 0), build_clinic(tmp_path))


def test_default_fake_home_keeps_existing_page_surface(clinic_http):
    port, _ = clinic_http
    _, _, start = request(port, "GET", "/")
    token = re.search(r'name="operation_id" value="([^"]+)', start).group(1)
    _, headers, _ = request(port, "POST", "/players", {"display_name": "状态弟子", "operation_id": token})
    _, _, home = request(port, "GET", headers["Location"])
    assert "导师运行" not in home and "fallback" not in home
    assert "/mentor/explain" not in request(port, "GET", headers["Location"].replace("/clinic", "/teaching"))[2]
