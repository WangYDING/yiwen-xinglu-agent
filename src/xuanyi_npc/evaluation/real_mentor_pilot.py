"""Offline preparation gate for a future separately authorized paid mentor pilot."""

import argparse
import json
from xuanyi_npc.resources.runtime import read_runtime_text


def build_parser():
    parser = argparse.ArgumentParser(prog="xuanyi-real-mentor-pilot")
    parser.add_argument("--confirm-paid-run", action="store_true")
    parser.add_argument("--model", default="deepseek-chat")
    parser.add_argument("--budget-cny", type=float, default=0.05)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    plan = json.loads(read_runtime_text("acceptance/real_mentor_pilot_v1.json"))
    if not args.confirm_paid_run:
        print("拒绝运行：未来付费Pilot必须显式提供 --confirm-paid-run。")
        return 2
    if args.model != plan["model"] or args.budget_cny != plan["budget_cny"]:
        print("拒绝运行：模型或预算与冻结Pilot方案不一致。")
        return 2
    print("已确认冻结参数；本离线准备版本未启用任何供应商请求，请取得单独执行授权后实现调用边界。")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
