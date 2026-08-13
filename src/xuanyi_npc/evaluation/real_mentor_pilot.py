"""Explicit version gate for frozen real mentor Pilots."""

import argparse
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xuanyi_npc.resources.runtime import read_runtime_text

V1_STOP_RECORD = "v1_stopped_before_network"


def build_parser():
    parser = argparse.ArgumentParser(prog="xuanyi-real-mentor-pilot",description="v3: deepseek-v4-flash, thinking disabled, 5 base requests, 0.05 CNY, one repair each; quality failure continues, safety/protocol failures stop.")
    parser.add_argument("--pilot-version", choices=("v3",), required=True)
    parser.add_argument("--confirm-paid-run", action="store_true")
    parser.add_argument("--budget-cny")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
    except SystemExit:
        return 2
    if args.dry_run:
        from xuanyi_npc.evaluation.real_mentor_v3_runner import dry_run_summary
        print(__import__("json").dumps(dry_run_summary(),ensure_ascii=False))
        return 0
    if not args.confirm_paid_run:
        print("拒绝运行：真实Pilot必须显式提供 --confirm-paid-run。")
        return 2
    try:
        budget = Decimal(args.budget_cny or "")
    except InvalidOperation:
        print("拒绝运行：预算格式无效。")
        return 2
    if budget != Decimal("0.05"):
        print("拒绝运行：预算必须精确等于冻结值 0.05 CNY。")
        return 2
    if args.output is None:
        print("拒绝运行：真实Pilot必须指定Git忽略输出目录。")
        return 2
    from xuanyi_npc.evaluation.real_mentor_v3_runner import run_v3
    return run_v3(output=args.output, budget=budget)


if __name__ == "__main__":
    raise SystemExit(main())
