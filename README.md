# 玄医师承型智能 NPC

这是一个道家志怪背景的师承型智能 NPC 工程。项目目标是让道医 NPC 能够记忆玩家行为、判断能力与师徒关系、自适应安排教学和考核，并在确定性条件满足后开放传承。

项目中的病例、医术、异常现象和处置方式均为架空设定，不提供现实诊断、处方或剂量。

## 当前状态

当前已完成 **M2a：Fake LLM Agent Harness 与安全闭环**、**M2b-P0：供应商无关 dev 场景与确定性评测器**，以及 **M2b-P1a：DeepSeek Adapter 与离线预检**。2026-08-06 已完成真实模型发现和一次诊断性 Pilot；2026-08-07 完成了根因分析、评测契约分离和 `v0.2.1` 严格 0.10 CNY 付费复核。该复核在首个 Chat 60 秒超时后安全停止，未自动重跑；M2b-P1b 仍保持“进行中”，不得据此推进 M3。

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
- 3 条严格 Schema 的 dev 场景，以及每条场景的参考轨迹和明确错误轨迹；
- 以统一 `EpisodeResult` 为输入的确定性评测器和单命令运行入口；
- 与 P0 Fake 故障注入分离的 3 条真实模型正向行为探针，以及首轮脱敏动作轨迹的离线重评入口；
- DeepSeek V4 Flash 的直接 HTTP Adapter、只读模型发现和明确供应商错误；
- 日期化人民币价格快照、供应商无关用量记录和请求发送前的 1 元 Pilot 严格预算门禁；
- 只使用伪 HTTP 响应的 DeepSeek Adapter 与 Pilot 离线测试；
- 面向 Agent 的公开诊断候选、调查说明和处置说明；
- 未知诊断候选由规则层拒绝，错误候选可正常提交并按确定性规则计分；
- 已完成调查从可用视图消失，伪造重复调查被明确拒绝且不产生事件；
- 全新 Python 3.12 虚拟环境中的安装、测试和 Demo 复现记录；
- 领域模型、规则边界和持久化测试。

**当前停在 M2b-P1b 收口**：当前 Key 已通过一次只读 `/models` 验证并确认可见 `deepseek-v4-flash`。后续任何付费运行都需新的单独授权；在 P1b 完成前，不把整个 M2 标为完成，也不进入 M3。

当前真实记录包括一次独立模型发现，以及一次诊断性 Pilot 内的 1 次 `/models` 和 23 次 `/chat/completions`；该 Pilot 的供应商返回成本估算为 `0.0332138 CNY`，23/23 次输出首次通过结构校验，3 条轨迹均可重放。三条运行使用同一个病例，历史 `0/3` 只是诊断性任务结果，不是模型正式成功率。项目仍不包含 MCP、长期记忆检索、数据库或交互界面。

`v0.2.1` 复核另外发出了 1 次 `/models` 和 1 次 Chat；Chat 在返回任何 AgentAction 或用量前超时。该轨迹是 0 步、0 事件且状态不变的基础设施负结果；实际 Token 与费用不可测，保守最大承诺成本为 `0.011321 CNY`。它无法判断行为纠偏是否生效，也不是任务成功率样本。

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
src/xuanyi_npc/evaluation/ 统一 Episode 结果与确定性 dev 评测器
src/xuanyi_npc/storage/  JSON 状态存储
data/cases/              结构化病例定义
data/evaluation/         P0 dev 场景、真实行为探针与脱敏回归轨迹
data/pilot/              带日期和来源的 Pilot 价格与安全策略快照
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

M2b-P0 的 3 条 dev 场景也完全离线，可由一条命令重复运行：

```bash
xuanyi-dev-eval
```

未安装项目时，在仓库根目录使用以下准确命令：

```powershell
$env:PYTHONPATH="src"
python -m xuanyi_npc.evaluation.dev_runner
```

在 macOS/Linux 中使用 `PYTHONPATH=src python -m xuanyi_npc.evaluation.dev_runner`。输出只有确定性轨迹结果；Fake LLM 的延迟、Token、成本和真实成功率保持“未测量”。

首轮真实 Pilot 的脱敏动作轨迹可以在完全不连网的情况下重评：

```bash
xuanyi-pilot-replay
```

未安装项目时，在仓库根目录运行 `python -m xuanyi_npc.evaluation.pilot_runner`。该命令只使用仓库内脱敏动作和确定性规则，不读取 API Key，不调用 DeepSeek。

## DeepSeek M2b 配置与安全边界

当前配置固定使用 DeepSeek 官方 OpenAI 兼容地址和 `deepseek-v4-flash`，禁止自动切换 Pro 或旧模型别名。项目从仓库根目录运行时会自动读取本地 `.env`；系统环境变量优先于 `.env` 中的同名配置。

先在仓库根目录复制配置模板：

```powershell
Copy-Item .env.example .env
```

然后只在 `.env` 中把 `DEEPSEEK_API_KEY=replace_with_your_deepseek_api_key` 的占位值替换为真实 Key。`.env` 已被 Git 忽略；不要把真实 Key 写入 `.env.example`、源码、日志、测试或聊天。如果不希望密钥落盘，也可以继续使用操作系统环境变量。

模型发现已经完成。只有在再次获得外部请求授权、确需复核模型列表时，以下命令才会发起一次真实但只读的 `/models` 请求：

```bash
xuanyi-deepseek-models
```

未安装项目时，对应 PowerShell 命令为：

```powershell
$env:PYTHONPATH="src"
python -m xuanyi_npc.agents.deepseek_cli models
```

标准探针已经完成且不得重跑。剩余两个安全探针当前暂停，必须再次获得单独授权；授权后的固定命令是：

```bash
xuanyi-deepseek-pilot --confirm-paid-pilot --safety-only --output results/deepseek_safety_review_001.json
```

未安装项目时，在 PowerShell 中先设置 `$env:PYTHONPATH="src"`，再运行 `python -m xuanyi_npc.agents.deepseek_cli pilot --confirm-paid-pilot --safety-only --output results/deepseek_safety_review_001.json`；macOS/Linux 使用 `PYTHONPATH=src python -m xuanyi_npc.agents.deepseek_cli pilot --confirm-paid-pilot --safety-only --output results/deepseek_safety_review_001.json`。`--safety-only` 只按冻结顺序各运行一次错误诱导抵抗探针和过早行动安全探针，不会运行标准探针或任何其他探针；它与 `--standard-only` 互斥。新文件名避免覆盖已保留结果。没有 `--confirm-paid-pilot` 时，程序会在读取 Key 和发起网络请求之前拒绝运行。

Pilot 默认保护参数：总预算 1.00 CNY；只运行同一病例的标准完成、错误诱导抵抗、过早诊断/处置安全三探针；每探针 1 次；每个 Episode 最多 8 步；每步最多一次格式修复；单次输出最多 512 Token；Adapter 不进行隐式重试。每次 Chat 发送前，将完整请求 JSON 的 UTF-8 字节数加 4096 Token 协议余量作为输入上界，全部按缓存未命中价计费，再加 512 个输出 Token 的最高费用。只有“已确认成本＋本次最大预留成本不超过 1.00 CNY”才发送；超时、响应缺少用量或用量无法核对时保留该请求的最大预留并立即冻结后续请求。

## 当前限制

- JSON 存储目前只用于验证状态接口，尚未处理多进程并发。
- DeepSeek `LLMAdapter` 已通过 MockTransport 离线测试，也有一次真实诊断性 Pilot 数据；单次样本不能代表稳定成功率、限流表现或长期成本。
- M1 只更新病例会话，不更新玩家能力、关系或长期记忆。
- 评分暂时只计算关键线索、诊断、处置和危险处置惩罚；提示扣分将在教学阶段接入。
- 演示是固定路线回放，还不是交互式游戏界面。
- V0 的 M2a Harness、M2b-P0 离线评测门槛和 M2b-P1a Adapter 预检已实现，但完整 M2 仍等待 M2b-P1b；V1、V2 当前只有配置与共享契约。
- 三个正式版本始终启用 `AgentContextFilter`；不安全提示词对照只允许在隔离的 A4 安全消融中运行。
- V1 只规划基础向量 Top-K 长期记忆和固定课程；多因素记忆排序、自适应教学与 Reflection 属于 V2。
- 长期记忆、自适应教学和 Reflection 明确不属于当前 V0 实现。
- 当前 V0 的固定课程只按步骤编号推进，不基于玩家表现动态改变。
- 当前只有一次诊断性 Pilot 的真实 Token、延迟、成本和失败轨迹，不足以形成正式比较或简历指标。
- 后续付费运行必须重新取得明确授权；MCP（M3）及以后里程碑均未开始。
