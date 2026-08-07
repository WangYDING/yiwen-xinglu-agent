"""Explicit command-line entry points for DeepSeek discovery and paid Pilot."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from xuanyi_npc.application.deepseek_pilot import (
    DeepSeekPilotRunner,
    PilotRunMode,
    PilotRunStatus,
)

from .deepseek import DeepSeekAdapterError, DeepSeekChatAdapter


def model_discovery_main() -> int:
    """Perform one authenticated, read-only GET /models request."""

    try:
        with DeepSeekChatAdapter.from_env() as adapter:
            discovery = adapter.discover_models()
    except DeepSeekAdapterError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 2
    print(discovery.model_dump_json(indent=2))
    return 0 if discovery.configured_model_available else 3


def paid_pilot_main(argv: list[str] | None = None) -> int:
    """Run the paid Pilot only after an explicit command-line confirmation."""

    parser = argparse.ArgumentParser(
        description="Run the budget-bounded DeepSeek M2b-P1 Pilot.",
    )
    parser.add_argument(
        "--confirm-paid-pilot",
        action="store_true",
        help="Acknowledge that this command sends paid DeepSeek API requests.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Checkpoint JSON path; defaults to results/deepseek_pilot_<UTC>.json.",
    )
    parser.add_argument(
        "--standard-only",
        action="store_true",
        help="Run only pilot_standard_completion_001 once, then stop.",
    )
    args = parser.parse_args(argv)
    if not args.confirm_paid_pilot:
        print(
            "Refusing to start: pass --confirm-paid-pilot only after explicit Pilot authorization.",
            file=sys.stderr,
        )
        return 2

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = args.output or Path("results") / f"deepseek_pilot_{timestamp}.json"
    try:
        with DeepSeekChatAdapter.from_env() as adapter:
            result = DeepSeekPilotRunner(
                adapter,
                run_mode=(
                    PilotRunMode.STANDARD_ONLY
                    if args.standard_only
                    else PilotRunMode.ALL_PROBES
                ),
            ).run(output)
    except DeepSeekAdapterError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        return 3
    print(f"Pilot result saved to {output}")
    print(result.model_dump_json(indent=2))
    return 0 if result.status is PilotRunStatus.COMPLETED else 4


def main(argv: list[str] | None = None) -> int:
    """Support accurate ``python -m`` commands from an uninstalled checkout."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in {"models", "pilot"}:
        print("Usage: python -m xuanyi_npc.agents.deepseek_cli {models|pilot}")
        return 2
    command, *remaining = arguments
    if command == "models":
        if remaining:
            print("The models command does not accept arguments.", file=sys.stderr)
            return 2
        return model_discovery_main()
    return paid_pilot_main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
