"""Verify an installed wheel from outside its source repository."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import anyio
from mcp import Client, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client

from xuanyi_npc.application import CaseCatalog
from xuanyi_npc.mcp_server import FROZEN_MCP_TOOL_NAMES
from xuanyi_npc.resources.runtime import materialized_runtime_resources


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        upper = name.upper()
        if "DEEPSEEK" in upper or "API_KEY" in upper:
            environment.pop(name, None)
    environment.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "PIP_NO_INDEX": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return environment


def _executable(name: str) -> Path:
    suffix = ".exe" if os.name == "nt" else ""
    path = Path(sys.executable).parent / f"{name}{suffix}"
    if not path.is_file():
        raise RuntimeError(f"installed command missing: {name}")
    return path


def _run(command: list[str], *, cwd: Path, input_text: str | None = None, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
        env=_environment(),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"installed command failed ({command[0]}): {completed.stderr}"
        )
    return completed


async def _verify_stdio(state_dir: Path, cwd: Path) -> tuple[str, ...]:
    parameters = StdioServerParameters(
        command=str(_executable("xuanyi-mcp-stdio")),
        args=["--state-dir", str(state_dir)],
        env=get_default_environment() | _environment(),
        cwd=cwd,
    )
    with anyio.fail_after(30):
        async with Client(
            stdio_client(parameters),
            read_timeout_seconds=15,
        ) as client:
            names = tuple(tool.name for tool in (await client.list_tools()).tools)
            if names != FROZEN_MCP_TOOL_NAMES:
                raise RuntimeError("installed MCP tool contract differs")
            return names


def main() -> int:
    if "torch" in sys.modules or "sentence_transformers" in sys.modules:
        raise RuntimeError("optional embedding stack loaded unexpectedly")
    try:
        import torch  # noqa: F401
    except ModuleNotFoundError:
        pass
    else:
        raise RuntimeError("core wheel environment unexpectedly contains torch")

    with tempfile.TemporaryDirectory(prefix="xuanyi-wheel-verify-") as temporary:
        root = Path(temporary).resolve()
        state = root / "state"
        acceptance_state = root / "acceptance-state"
        state.mkdir()
        acceptance_state.mkdir()

        with materialized_runtime_resources() as resources:
            case_ids = CaseCatalog(resources.case_dir).case_ids()
        if case_ids != (
            "gray_hearth_inn",
            "moon_well_echo",
            "old_paper_umbrella",
        ):
            raise RuntimeError("installed case catalog differs")

        for command_name in (
            "xuanyi-play",
            "xuanyi-mcp-stdio",
            "xuanyi-m5-acceptance",
        ):
            _run([str(_executable(command_name)), "--help"], cwd=root)

        play = _run(
            [str(_executable("xuanyi-play")), "--state-dir", str(state)],
            cwd=root,
            input_text="0\n",
        )
        if "行动模式：manual" not in play.stdout or "语义 shadow：关闭" not in play.stdout:
            raise RuntimeError("installed manual mode did not start safely")

        acceptance_output = root / "acceptance.json"
        acceptance = _run(
            [
                str(_executable("xuanyi-m5-acceptance")),
                "--run-id",
                "wheel_install_acceptance",
                "--state-dir",
                str(acceptance_state),
                "--output",
                str(acceptance_output),
            ],
            cwd=root,
            timeout=240,
        )
        payload: dict[str, Any] = json.loads(acceptance_output.read_text(encoding="utf-8"))
        if payload["status"] != "passed":
            raise RuntimeError("installed M5 acceptance did not pass")
        if payload["historical_evidence"]["verification_mode"] != "public_manifest":
            raise RuntimeError("installed acceptance did not use public evidence")
        if payload["external_use"]["network_requests"] != 0:
            raise RuntimeError("installed acceptance reported network use")

        mcp_tools = anyio.run(_verify_stdio, state, root)
        result = {
            "status": "passed",
            "case_ids": case_ids,
            "commands": [
                "xuanyi-play",
                "xuanyi-mcp-stdio",
                "xuanyi-m5-acceptance",
            ],
            "mcp_tools": mcp_tools,
            "m5_worker_processes": payload["worker_processes"],
            "external_network_requests": 0,
            "torch_installed": False,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
