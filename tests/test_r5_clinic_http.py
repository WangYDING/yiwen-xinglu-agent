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
