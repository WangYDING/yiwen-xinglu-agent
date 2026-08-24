import re
import subprocess
import sys
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


def start_server(state_dir):
    process = subprocess.Popen(
        [sys.executable, "-m", "xuanyi_npc.clinic.server", "--state-dir", str(state_dir), "--npc-mode", "offline"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    line = process.stdout.readline().strip()
    assert line.startswith("《异闻行录》已启动：http://127.0.0.1:"), (line, process.stderr.read())
    return process, line.split("：", 1)[1]


def get(url):
    return urlopen(url, timeout=5).read().decode("utf-8")


def post(url, fields):
    request = Request(url, data=urlencode(fields).encode(), method="POST")
    return urlopen(request, timeout=5).geturl()


def stop(process):
    process.terminate()
    process.wait(timeout=5)
    assert process.returncode is not None


def test_two_real_http_processes_restore_same_player_and_active_case(tmp_path):
    state = tmp_path / "state"; state.mkdir()
    first, first_url = start_server(state)
    try:
        start = get(first_url)
        token = re.search(r'name="operation_id" value="([^"]+)', start).group(1)
        location = post(first_url + "/players", {"display_name": "两进程弟子", "operation_id": token})
        player_id = parse_qs(urlparse(location).query)["player_id"][0]
        cases = get(first_url + "/cases?" + urlencode({"player_id": player_id}))
        form = re.search(r'<form method="post" action="/cases/start">.*?name="case_id" value="lantern_alley_conflicting_testimony".*?name="operation_id" value="([^"]+)', cases, re.S)
        assert form
        case_location = post(first_url + "/cases/start", {"player_id": player_id, "case_id": "lantern_alley_conflicting_testimony", "operation_id": form.group(1)})
    finally:
        stop(first)
    second, second_url = start_server(state)
    try:
        parsed = urlparse(case_location)
        restored = get(second_url + parsed.path + "?" + parsed.query)
        assert "双灯巷与相悖证词" in restored
    finally:
        stop(second)
