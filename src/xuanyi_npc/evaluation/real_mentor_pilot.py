"""CLI gate and orchestration hooks for the separately authorized R6 v2 pilot."""

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xuanyi_npc.resources.runtime import read_runtime_text

V1_STOP_RECORD = "v1_stopped_before_network"


def build_parser():
    parser = argparse.ArgumentParser(prog="xuanyi-real-mentor-pilot")
    parser.add_argument("--confirm-paid-run", action="store_true")
    parser.add_argument("--budget-cny", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit:
        return 2
    if not args.confirm_paid_run:
        print("拒绝运行：真实Pilot必须显式提供 --confirm-paid-run。")
        return 2
    try:
        budget = Decimal(args.budget_cny)
    except InvalidOperation:
        print("拒绝运行：预算格式无效。")
        return 2
    if budget != Decimal("0.05"):
        print("拒绝运行：预算必须精确等于冻结值 0.05 CNY。")
        return 2
    # The v2 freeze adds the immutable manifest consumed here. Until it exists,
    # infrastructure can be tested without allowing a provider request.
    try:
        read_runtime_text("acceptance/r6_real_mentor_pilot_v2.json")
    except FileNotFoundError:
        print("拒绝运行：Pilot v2 尚未冻结。")
        return 3
    from xuanyi_npc.evaluation.real_mentor_runner import run_paid_pilot
    return run_paid_pilot(output=args.output, budget=budget)


if __name__ == "__main__":
    raise SystemExit(main())
