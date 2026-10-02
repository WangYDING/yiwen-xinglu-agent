"""Recompute a human-readable V2 report exclusively from immutable artifacts."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import statistics

from xuanyi_npc.evaluation.v2_contracts import GradeStatus, V2RunArtifact
from xuanyi_npc.evaluation.v2_graders import strict_success
from xuanyi_npc.evaluation.v2_scenarios import resolve_scenarios


def _load(roots: list[Path]) -> list[V2RunArtifact]:
    paths = [path for root in roots for path in root.glob("runs/*/artifact.json")]
    return [V2RunArtifact.model_validate_json(path.read_text(encoding="utf-8")) for path in sorted(paths)]


def _is_task_success(item):
    return any(g.grader_id == "task_outcome" and g.status is GradeStatus.PASS for g in item.grades)


def render(artifacts: list[V2RunArtifact]) -> str:
    resolved, _ = resolve_scenarios(); specs={item["id"]:item for item in resolved["scenarios"]}
    fixtures=[a for a in artifacts if a.artifact_kind.value=="deterministic_fixture"]
    task=[a for a in artifacts if a.suite=="task" and a.artifact_kind.value=="real_model_trial"]
    memory=[a for a in artifacts if a.suite=="memory_transfer"]
    lines=["# 异闻行录 Agent 评测 V2 报告", "", "## 实验身份", "",
        f"- 真实模型 trial：{len(task)+len(memory)}；固定夹具：{len(fixtures)}。两类结果未合并。",
        f"- 模型：{next((a.model for a in task+memory if a.model), '未运行')}。",
        f"- 旧 V1/E6/E9–E13 结果未覆盖；本报告只读取 V2 不可变 artifact。", "",
        "## T 任务能力（真实模型）", "",
        "|profile|N|任务成功|严格成功|abort|已知费用/元|", "|---|---:|---:|---:|---:|---:|"]
    by_profile=defaultdict(list)
    for a in task: by_profile[specs[a.scenario_id].get("profile","unknown")].append(a)
    for profile,values in sorted(by_profile.items()):
        lines.append(f"|{profile}|{len(values)}|{sum(_is_task_success(a) for a in values)}/{len(values)}|{sum(strict_success(a.grades) for a in values)}/{len(values)}|{sum(a.status=='aborted' for a in values)}|{sum(a.known_cost_cny or 0 for a in values):.4f}|")
    lines += ["", "每场景重复结果：", "", "|场景|病例|profile|成功次数|all-repeats-pass|", "|---|---|---|---:|---|"]
    by_scenario=defaultdict(list)
    for a in task: by_scenario[a.scenario_id].append(a)
    for sid,values in sorted(by_scenario.items()):
        spec=specs[sid]; successes=sum(_is_task_success(a) for a in values)
        lines.append(f"|{sid}|{spec.get('base_case_id','—')}|{spec.get('profile','—')}|{successes}/{len(values)}|{'是' if successes==len(values) and values else '否'}|")
    lines += ["", "## E/R 固定夹具（非模型能力成绩）", "",
              "|场景|套件|结果|原因|", "|---|---|---|---|"]
    for a in sorted(fixtures,key=lambda x:x.scenario_id):
        primary=a.grades[0] if a.grades else None
        lines.append(f"|{a.scenario_id}|{a.suite}|{primary.status.value if primary else 'UNKNOWN'}|{primary.reason_code if primary else 'missing_grade'}|")
    engineering_failures = [
        a.scenario_id for a in fixtures
        if a.suite == "engineering" and a.grades
        and a.grades[0].status in {
            GradeStatus.FAIL, GradeStatus.UNKNOWN, GradeStatus.NOT_READY,
        }
    ]
    lines += ["", "## M 记忆迁移（真实模型目标 episode）", "",
              "|场景/repeat|M0成功|M1成功|M2成功|M1−M0|M2−M1|M2 no_write/失败|", "|---|---:|---:|---:|---:|---:|---|"]
    groups=defaultdict(dict)
    for a in memory: groups[(a.scenario_id,a.repeat_index)][a.condition]=a
    for (sid,repeat),values in sorted(groups.items()):
        scores={c:int(_is_task_success(values[c])) if c in values else None for c in ("M0","M1","M2")}
        def show(v): return "—" if v is None else str(v)
        d10="—" if None in (scores["M0"],scores["M1"]) else str(scores["M1"]-scores["M0"])
        d21="—" if None in (scores["M1"],scores["M2"]) else str(scores["M2"]-scores["M1"])
        m2=values.get("M2"); reflection=next((e for e in (m2.events if m2 else ()) if e.event_type=="reflection_finished"),None)
        rstate="未运行" if m2 is None else (reflection.data.get("status","no_write") if reflection else "未触发")
        lines.append(f"|{sid}/r{repeat}|{show(scores['M0'])}|{show(scores['M1'])}|{show(scores['M2'])}|{d10}|{d21}|{rstate}|")
    exposure_reasons=defaultdict(int)
    for a in memory:
        grade=next((g for g in a.grades if g.grader_id=="memory_exposure"),None)
        if grade: exposure_reasons[(a.scenario_id,a.condition,grade.reason_code)]+=1
    lines += ["", "记忆曝光核对：", ""]
    for (sid,condition,reason),count in sorted(exposure_reasons.items()):
        lines.append(f"- {sid}/{condition}: {reason} × {count}")
    real=task+memory; known=[a.known_cost_cny for a in real if a.known_cost_cny is not None]
    lines += ["", "## 性能与成本", "",
        f"- 按冻结高峰价格估算的真实 trial 费用小计：{sum(known):.4f} 元；usage/费用完整 trial：{len(known)}/{len(real)}。",
        f"- 输入 tokens：{sum(a.input_tokens or 0 for a in real)}；输出 tokens：{sum(a.output_tokens or 0 for a in real)}。",
        f"- 真实 trial 时延中位数：{statistics.median(a.duration_ms for a in real)/1000:.2f}s。" if real else "- 尚无真实 trial。",
        "", "## 安全门与可声称范围", ""]
    critical=[]
    for a in artifacts:
        for g in a.grades:
            if g.grader_id in {"authorization","injection"} and g.status is GradeStatus.FAIL: critical.append((a.scenario_id,g.reason_code))
    incomplete=any(a.status in {"not_ready","invalid"} for a in artifacts)
    gate="FAIL" if critical else ("INCOMPLETE" if incomplete else "PASS")
    lines += [f"- 安全门：**{gate}**。" + (f" 已证实问题：{critical}。" if critical else " 未发现已证实的未授权执行或跨用户暴露。"),
        f"- 工程发布就绪：**{'FAIL' if engineering_failures else 'PASS'}**；失败/未知/未就绪场景：{', '.join(engineering_failures) if engineering_failures else '无'}。安全门通过不等于并发/恢复能力就绪。",
        f"- 供应商失败：{sum((a.failure_code or '').startswith('deepseek_provider') for a in real)}；max-turns 未完成：{sum(a.failure_code=='max_turns_exceeded' for a in real)}。",
        "- E/R 只有实际调用生产组件且为 PASS 的夹具可作为对应层级证据；scorer-only 合成轨迹不得表述为生产机制或模型智能通过。",
        "- 当前六病例均为仓库已暴露资源，不称作未知 holdout；重复次数是探索性重复，不作显著性声明。",
        "- 任务或记忆无提升均按原始结果报告；没有为了成绩修改 Agent、病例或 grader。", ""]
    return "\n".join(lines)


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--artifact-root",type=Path,action="append",required=True);p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv); text=render(_load(args.artifact_root)); args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists(): raise FileExistsError(args.output)
    args.output.write_text(text,encoding="utf-8",newline="\n");print(args.output);return 0


if __name__=="__main__":raise SystemExit(main())
