# 玄医师承型智能 NPC

这是一个道家志怪背景的师承型智能 NPC 工程。项目目标是让道医 NPC 能够记忆玩家行为、判断能力与师徒关系、自适应安排教学和考核，并在确定性条件满足后开放传承。

项目中的病例、医术、异常现象和处置方式均为架空设定，不提供现实诊断、处方或剂量。

## 当前状态

当前已完成 **M2a：Fake LLM Agent Harness 与安全闭环**。整个 M2 尚未完成。

已经包含：

- 七个核心领域对象及其输入校验；
- 一个“旧纸伞与失约书生”技术验证病例；
- 玩家状态与病例会话状态的 JSON 保存和读取接口；
- 调查、诊断、处置与基础评分引擎；
- 明确的技能、线索、证据和会话状态错误；
- 不调用大模型的完整病例回放；
- 从领域事件重建病例会话的状态重放器；
- V0、V1、V2 共用的 `EpisodeResult`；
- 权限过滤后的 `PlayerView` 与 `CaseObservation`；
- 不允许关键状态或永久记忆写入的安全 `AgentAction`；
- 明确且经过配置校验的 V0、V1、V2 能力边界；
- 可替换的 `LLMAdapter` 与只读输入的 `DoctorAgent`；
- 只使用最近有限轮对话和固定教学顺序的 V0 Prompt；
- `AgentAction` 格式错误时的一次修复重试与确定性降级；
- 将工具建议转换为领域命令、再交给病例引擎校验的应用层；
- 使用脚本化 Fake LLM 跑通并记录完整 Episode；
- 面向 Agent 的公开诊断候选、调查说明和处置说明；
- 未知诊断候选由规则层拒绝，错误候选可正常提交并按确定性规则计分；
- 全新 Python 3.12 虚拟环境中的安装、测试和 Demo 复现记录；
- 领域模型、规则边界和持久化测试。

**M2b 尚待完成**：真实 LLM 适配、3 条 dev 场景、小型 Pilot，以及真实超时、Token 和延迟验证。在 M2b 完成前，不把整个 M2 标为完成，也不进入 M3。

当前尚未接入真实 LLM 供应商，也不包含 MCP、长期记忆检索、数据库或交互界面。现有结果只能证明结构化 Agent 编排、规则隔离和 Fake LLM 安全闭环可运行，不能证明真实模型的工具选择或病例完成能力。

## 设计边界

- 大模型未来只负责语言、教学策略和结构化行动建议。
- 病例真相、状态数值、权限、技能解锁和最终状态修改由确定性规则负责。
- Agent 输出必须通过 Pydantic 校验，再由规则层决定是否执行。
- V0 Agent 只接收权限过滤后的只读视图、最近对话和固定课程。
- 所有病例状态变化都通过领域命令和事件记录，以支持追踪和回放。

## 目录

```text
src/xuanyi_npc/domain/   核心领域对象
src/xuanyi_npc/agents/   LLM 协议、DoctorAgent 与 Fake LLM
src/xuanyi_npc/application/ Agent 权限过滤视图
src/xuanyi_npc/config/   V0、V1、V2 能力配置
src/xuanyi_npc/engine/   确定性病例引擎
src/xuanyi_npc/evaluation/ 统一 Episode 结果
src/xuanyi_npc/storage/  JSON 状态存储
data/cases/              结构化病例定义
docs/                    架构决策记录
tests/                   自动化测试
```

当前执行状态以 `docs/ROADMAP.md` 为唯一路线来源；架构约束见 `docs/DECISIONS.md`，历史和当前可复现性验证见 `docs/VERIFICATION.md`。

## 本地运行

要求 Python 3.11 或更高版本。

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest
```

在未安装项目包时，也可以直接在仓库根目录运行 `python -m pytest`；pytest 配置会加载 `src` 目录。

安装完成后，可以运行一次固定的正确病例路线：

```bash
xuanyi-case-demo
```

也可以使用：

```bash
python -m xuanyi_npc.demo_case
```

演示会依次执行观察、询问、验物、观炁、诊断和处置，最后显示可解释的评分构成。全过程不调用大模型。

M2a 的 Agent 闭环使用 Fake LLM 自动验证，不需要 API 密钥：

```bash
python -m pytest tests/test_doctor_agent.py tests/test_v0_episode_runner.py
```

## 当前限制

- JSON 存储目前只用于验证状态接口，尚未处理多进程并发。
- `LLMAdapter` 目前只有测试用 Fake 实现，尚未验证真实供应商的超时、限流、结构化输出兼容性、延迟、Token 或成本；这些属于 M2b。
- M1 只更新病例会话，不更新玩家能力、关系或长期记忆。
- 评分暂时只计算关键线索、诊断、处置和危险处置惩罚；提示扣分将在教学阶段接入。
- 演示是固定路线回放，还不是交互式游戏界面。
- V0 的 M2a Harness 已实现，但完整 M2 仍等待 M2b；V1、V2 当前只有配置与共享契约。
- 三个正式版本始终启用 `AgentContextFilter`；不安全提示词对照只允许在隔离的 A4 安全消融中运行。
- V1 只规划基础向量 Top-K 长期记忆和固定课程；多因素记忆排序、自适应教学与 Reflection 属于 V2。
- 长期记忆、自适应教学和 Reflection 明确不属于当前 V0 实现。
- 当前 V0 的固定课程只按步骤编号推进，不基于玩家表现动态改变。
- 当前没有评测成功率、延迟或成本数据；这些指标只能由后续真实评测生成。
- 下一阶段只能是 M2b；MCP（M3）及以后里程碑均未开始。
