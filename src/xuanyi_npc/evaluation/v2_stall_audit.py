"""Recompute V2 stall evidence from immutable run artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def classify_task(artifact: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    events = artifact["events"]
    commits = [item for item in events if item["event_type"] == "world_committed"]
    attempts = [item for item in events if item["event_type"] == "tool_attempted"]
    diagnosis_turns = [
        item["turn"] for item in commits
        if item["data"].get("tool") == "submit_diagnosis"
    ]
    treatment_committed = any(
        item["data"].get("tool") == "execute_treatment" for item in commits
    )
    completed = artifact["terminal_snapshot"].get("terminal_status") == "completed"
    provider_error = (artifact.get("failure_code") or "").startswith("deepseek_provider")
    if completed:
        category = "completed"
    elif provider_error:
        category = "provider_error"
    elif diagnosis_turns and not treatment_committed:
        category = "diagnosis_committed_no_treatment"
    elif not diagnosis_turns:
        category = "no_diagnosis_commit"
    else:
        category = "other"
    first_diagnosis = min(diagnosis_turns) if diagnosis_turns else None
    later_attempts = [item for item in attempts if first_diagnosis and item["turn"] > first_diagnosis]
    return category, {
        "run_id": artifact["run_id"],
        "scenario_id": artifact["scenario_id"],
        "category": category,
        "first_diagnosis_commit_turn": first_diagnosis,
        "post_diagnosis_tool_attempt_count": len(later_attempts),
        "failure_code": artifact.get("failure_code"),
    }


def classify_memory_diagnosis(artifact: dict[str, Any]) -> dict[str, Any]:
    """Triangulate old M diagnosis evidence without trusting missing commit.tool."""
    events = artifact["events"]
    attempts = [
        item for item in events
        if item["event_type"] == "tool_attempted"
        and item["data"].get("tool") == "submit_diagnosis"
    ]
    controlled_commits = [
        item for item in events
        if item["event_type"] == "world_committed"
        and item["data"].get("controlled") is True
    ]
    confirmations = [
        item for item in events
        if item["event_type"] == "confirmation_received"
        and item["data"].get("valid") is True
    ]
    matched = []
    for attempt in attempts:
        for commit in controlled_commits:
            if commit.get("turn") != attempt.get("turn"):
                continue
            confirmation = next((
                item for item in confirmations
                if item.get("turn") == commit.get("turn")
                and item["data"].get("action_digest")
                == commit["data"].get("action_digest")
            ), None)
            if confirmation is not None:
                matched.append(commit)
    final_diagnosis = artifact["terminal_snapshot"].get("submitted_diagnosis_id")
    if final_diagnosis and len(matched) == 1:
        status = "CONFIRMED"
        confirmed_count = 1
    elif final_diagnosis or matched or any(
        item["data"].get("controlled") is True
        and not any(attempt.get("turn") == item.get("turn") for attempt in attempts)
        for item in controlled_commits
    ):
        status = "UNKNOWN"
        confirmed_count = 0
    else:
        status = "NO_COMMIT_EVIDENCE"
        confirmed_count = 0
    return {
        "run_id": artifact["run_id"],
        "scenario_id": artifact["scenario_id"],
        "condition": artifact.get("condition"),
        "final_submitted_diagnosis_id": final_diagnosis,
        "diagnosis_tool_attempt_count": len(attempts),
        "confirmed_diagnosis_commit_count": confirmed_count,
        "diagnosis_commit_evidence_status": status,
        "matched_commit_turns": sorted({item.get("turn") for item in matched}),
    }


def audit(task_roots: list[Path], memory_root: Path) -> dict[str, Any]:
    task_paths = sorted(
        path for root in task_roots for path in root.glob("runs/*/artifact.json")
    )
    task_rows = []
    counts: dict[str, int] = {}
    for path in task_paths:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        category, row = classify_task(artifact)
        row["artifact_path"] = str(path.resolve())
        task_rows.append(row)
        counts[category] = counts.get(category, 0) + 1
    memory_paths = sorted(memory_root.glob("runs/*/artifact.json"))
    memory_treatment_attempts = 0
    memory_rows = []
    for path in memory_paths:
        artifact = json.loads(path.read_text(encoding="utf-8"))
        row = classify_memory_diagnosis(artifact)
        row["artifact_path"] = str(path.resolve())
        memory_rows.append(row)
        memory_treatment_attempts += sum(
            item["event_type"] == "tool_attempted"
            and item["data"].get("tool") == "execute_treatment"
            for item in artifact["events"]
        )
    return {
        "task_run_count": len(task_rows),
        "task_unique_run_count": len({item["run_id"] for item in task_rows}),
        "task_categories": counts,
        "task_runs": task_rows,
        "memory_run_count": len(memory_paths),
        "memory_execute_treatment_attempt_count": memory_treatment_attempts,
        "memory_final_diagnosis_run_count": sum(
            bool(item["final_submitted_diagnosis_id"]) for item in memory_rows
        ),
        "memory_diagnosis_tool_attempt_count": sum(
            item["diagnosis_tool_attempt_count"] for item in memory_rows
        ),
        "memory_diagnosis_tool_attempt_run_count": sum(
            item["diagnosis_tool_attempt_count"] > 0 for item in memory_rows
        ),
        "memory_confirmed_diagnosis_commit_count": sum(
            item["confirmed_diagnosis_commit_count"] for item in memory_rows
        ),
        "memory_unknown_diagnosis_commit_run_count": sum(
            item["diagnosis_commit_evidence_status"] == "UNKNOWN"
            for item in memory_rows
        ),
        "memory_no_commit_evidence_run_count": sum(
            item["diagnosis_commit_evidence_status"] == "NO_COMMIT_EVIDENCE"
            for item in memory_rows
        ),
        "memory_attempt_without_commit_run_count": sum(
            item["diagnosis_commit_evidence_status"] == "NO_COMMIT_EVIDENCE"
            and item["diagnosis_tool_attempt_count"] > 0
            for item in memory_rows
        ),
        "memory_no_diagnosis_attempt_run_count": sum(
            item["diagnosis_tool_attempt_count"] == 0 for item in memory_rows
        ),
        "memory_diagnosis_evidence_rows": memory_rows,
    }


def render_markdown(result: dict[str, Any]) -> str:
    counts = result["task_categories"]
    lines = [
        "# V2 停滞证据重算",
        "",
        "本报告只读取 2026-09-18 的不可变真实模型 artifact；未重评分、未改写旧成绩。",
        "",
        "## 汇总",
        "",
        f"- T：{result['task_run_count']} 条，唯一 run_id {result['task_unique_run_count']} 条。",
        f"- 已提交诊断但未治疗：{counts.get('diagnosis_committed_no_treatment', 0)}。",
        f"- 未提交诊断：{counts.get('no_diagnosis_commit', 0)}。",
        f"- 供应商错误：{counts.get('provider_error', 0)}。",
        f"- 完成：{counts.get('completed', 0)}。",
        f"- M：{result['memory_run_count']} 条；最终已有诊断 {result['memory_final_diagnosis_run_count']} 条。",
        f"- M 诊断工具尝试：{result['memory_diagnosis_tool_attempt_count']} 次，分布于 {result['memory_diagnosis_tool_attempt_run_count']} 条运行。",
        f"- M 交叉证据确认的诊断提交：{result['memory_confirmed_diagnosis_commit_count']} 次；诊断提交证据 UNKNOWN：{result['memory_unknown_diagnosis_commit_run_count']} 条运行。",
        f"- M 没有诊断提交证据：{result['memory_no_commit_evidence_run_count']} 条运行；其中工具尝试与提交必须分开计数。",
        f"  - 其中 {result['memory_attempt_without_commit_run_count']} 条尝试过诊断但未形成可确认提交，{result['memory_no_diagnosis_attempt_run_count']} 条没有诊断尝试。",
        f"- M execute_treatment 工具尝试：{result['memory_execute_treatment_attempt_count']} 次。",
        "- 更正结论：M 并非全部在诊断前停滞；最终已有诊断且提交证据可确认的运行，应归入诊断后无治疗工具尝试。",
        "",
        "## 逐运行证据",
        "",
        "|run|scenario|分类|首次诊断提交回合|诊断后工具尝试|artifact|",
        "|---|---|---|---:|---:|---|",
    ]
    for row in result["task_runs"]:
        turn = row["first_diagnosis_commit_turn"]
        lines.append(
            f"|{row['run_id']}|{row['scenario_id']}|{row['category']}|"
            f"{turn if turn is not None else '—'}|{row['post_diagnosis_tool_attempt_count']}|"
            f"`{row['artifact_path']}`|"
        )
    lines += [
        "",
        "## M 诊断证据交叉核验",
        "",
        "旧 M 的 `world_committed.data.tool` 缺失，不能单独用该字段分类。CONFIRMED 要求：权威终态已有诊断、同回合存在 `submit_diagnosis` 尝试与 controlled commit，并有 digest 匹配的有效确认。",
        "",
        "|run|condition|最终诊断|诊断尝试|确认提交|状态|提交回合|artifact|",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    for row in result["memory_diagnosis_evidence_rows"]:
        lines.append(
            f"|{row['run_id']}|{row['condition']}|"
            f"{'是' if row['final_submitted_diagnosis_id'] else '否'}|"
            f"{row['diagnosis_tool_attempt_count']}|"
            f"{row['confirmed_diagnosis_commit_count']}|"
            f"{row['diagnosis_commit_evidence_status']}|"
            f"{','.join(str(item) for item in row['matched_commit_turns']) or '—'}|"
            f"`{row['artifact_path']}`|"
        )
    lines += [
        "",
        "## 证据边界",
        "",
        "- 稀疏旧 Trace 能证明模型调用、工具尝试和世界提交是否出现。",
        "- 它没有保存完整初次/修复提案及校验错误，因此不能区分主动 RESPOND 与校验失败 fallback。",
        "- 上述未知项必须由新版 diagnostic Trace 的新运行回答，不能从旧记录反推。",
        "",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-root", type=Path, action="append", required=True)
    parser.add_argument("--memory-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit(args.task_root, args.memory_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(render_markdown(result))
    compact = {
        key: value for key, value in result.items()
        if key not in {"task_runs", "memory_diagnosis_evidence_rows"}
    }
    print(json.dumps(compact, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
