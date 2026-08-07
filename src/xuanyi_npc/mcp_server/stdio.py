"""Explicit stdio entry point for the M3-P1 subprocess boundary."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from mcp.server import MCPServer

from xuanyi_npc.application import MCPApplicationService
from xuanyi_npc.domain import CaseDefinition
from xuanyi_npc.storage import JsonStateStore

from .server import create_mcp_server


class StdioConfigurationError(ValueError):
    """Raised before transport startup when explicit local paths are unusable."""


@dataclass(frozen=True)
class StdioServerConfig:
    case_dir: Path
    state_dir: Path

    @classmethod
    def load(
        cls,
        *,
        case_dir: Path | str,
        state_dir: Path | str,
    ) -> "StdioServerConfig":
        resolved_cases = Path(case_dir).resolve()
        resolved_state = Path(state_dir).resolve()
        if not resolved_cases.is_dir():
            raise StdioConfigurationError("case directory is unavailable")
        if not resolved_state.is_dir():
            raise StdioConfigurationError("state directory is unavailable")

        case_files = tuple(sorted(resolved_cases.glob("*.json")))
        if not case_files:
            raise StdioConfigurationError("case directory contains no case definitions")
        for case_file in case_files:
            try:
                CaseDefinition.model_validate_json(
                    case_file.read_text(encoding="utf-8")
                )
            except (OSError, ValueError) as exc:
                raise StdioConfigurationError(
                    "case data validation failed"
                ) from exc

        return cls(case_dir=resolved_cases, state_dir=resolved_state)


def create_configured_stdio_server(config: StdioServerConfig) -> MCPServer:
    """Construct the existing MCP server over explicit local dependencies."""

    service = MCPApplicationService(
        state_store=JsonStateStore(config.state_dir),
        case_root=config.case_dir,
    )
    return create_mcp_server(service)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xuanyi-mcp-stdio",
        description="Run the Xuanyi M3-P1 MCP server over stdio.",
    )
    parser.add_argument(
        "--case-dir",
        type=Path,
        required=True,
        help="Directory containing validated case definition JSON files.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        required=True,
        help="Existing directory containing JsonStateStore snapshots.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = StdioServerConfig.load(
            case_dir=args.case_dir,
            state_dir=args.state_dir,
        )
        server = create_configured_stdio_server(config)
    except StdioConfigurationError as exc:
        print(f"MCP stdio configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception:
        print("MCP stdio startup failed safely.", file=sys.stderr)
        return 1

    try:
        server.run("stdio")
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("MCP stdio server stopped after an internal error.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
