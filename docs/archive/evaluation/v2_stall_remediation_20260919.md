# V2 任务停滞离线核查与修复记录

日期：2026-09-19。本文不覆盖 2026-09-18 的报告、grader 输出或真实模型 artifact；本轮没有调用付费模型。

## 1. 从旧 artifact 重算的事实

更正后的可复算明细见 [`evaluation_results/v2/v2_stall_audit_20260919_04.md`](../../../evaluation_results/v2/v2_stall_audit_20260919_04.md)。原 `_01`–`_03` 报告与全部原始 artifact 均保留，未覆盖；其中 `_01` 将旧 M `world_committed` 缺少 `tool` 字段误判为没有诊断提交，不能再作为该项结论的依据。

- T 共 72 个唯一运行：38 个已真实提交诊断但未提交治疗，31 个没有诊断提交，2 个供应商错误，1 个完成。
- 上述 38 个“诊断后停滞”运行在诊断提交后都没有任何后续工具尝试。
- M 共 54 个运行：权威 `terminal_snapshot` 显示最终已有诊断的运行 31 个；`submit_diagnosis` 工具尝试共 65 次、分布于 34 个运行；结合终态、同回合 `tool_attempted`、controlled `world_committed` 与 digest 匹配的有效确认，可确认诊断提交 31 次，`UNKNOWN` 为 0 个运行，另有 23 个运行没有诊断提交证据。
- M 的 `execute_treatment` 工具尝试仍为 0。正确结论不是“M 全部在诊断前停滞”：31 个运行已经进入诊断后状态但没有治疗工具尝试；另有 3 个运行尝试诊断但未形成可确认提交，20 个运行没有诊断尝试。
- `t01_r01` 的旧记录显示：第 8 回合产生诊断 pending，第 9 回合确认与诊断提交成功；第 10–16 回合世界 revision 保持 7，每回合仍有模型调用，但没有工具尝试。

旧 Trace 没有保存第 10–16 回合的完整提案、格式修复结果、确定性校验错误或 fallback 原因。因此下列解释均不能由旧记录区分：模型主动只回应、初次输出无效后修复、两次无效后 fallback。不能把其中任一种写成旧运行的已证实根因。

## 2. 离线确认的产品缺陷

`CooperativeRuntime` 原先只在工具成功/失败后调用 `DeterministicPlanEvaluator`。合法的非工具 PlanStep（例如“先讨论治疗风险”）即使已经用 `RESPOND` 完成，也不会被标记完成或推进。下一轮仍看到同一个 active step，后续 `propose_treatment` 步骤可能永久不可达。

这是可独立复现的状态机活性缺陷，位置在诊断后的治疗讨论链路，但现有旧 Trace 不能证明 38 次旧停滞全部或部分由它触发。

修复后，成功的 `RESPOND` 会推进当前无工具 PlanStep；若存在兼容的下一步骤，下一步骤成为 active。修复不选择诊断/治疗答案、不自动执行工具、不改变权限策略、评分标准或回合上限。

离线反证与边界：

- “已提交诊断后没有创建治疗目标”不是当前可复现缺陷；确定性测试确认 completed diagnosis goal 会被替换为 active `SELECT_TREATMENT` goal。
- `t01_r01` 的诊断确认关联与世界提交链是完整的，因此该运行在第 9 回合之前没有确认链阻断证据。
- 真实模型在新版状态推进下会选择工具、主动回应还是触发修复/fallback，仍需新 Trace 的小规模真实运行回答。

## 3. Diagnostic Trace v2

新 artifact 使用 `trace_schema_version=v2_diagnostic`；旧 artifact 继续按 `v1_sparse` 读取。

每回合新增或补强：

- `turn_context`：调用前公开观测、世界 revision、持久化 Goal/Plan 与 Agent state revision；
- `model_context`：模型实际收到的公开观测、Goal/Plan、上次计划评价、pending 关联与被投影的 memory IDs；
- `model_request_finished`：initial / format repair / action-contract repair 阶段、原始结构化输出、校验阶段/错误/路径、usage、供应商 ID、耗时；
- `proposal_finalized`：最终完整提案、fallback 原因、repair 类型、最终动作；
- `permission_evaluated`：权限模式及输入/输出 confirmation 关联；
- `tool_result`：工具真实状态、错误/回执序号以及执行前后公开世界和 Agent 状态。

Trace 不记录 API key、环境变量、私有 oracle 或模型内部思维链。模型输出只记录结构化提案本身；模型输入事件只包含已进入生产模型边界的公开投影。

`trace_integrity` v2 会把缺少上述逐回合证据的运行标为 `UNKNOWN`，不再把只有调用计数的稀疏轨迹判为证据完整。

## 4. E/R 证据纠正

新离线产物：`evaluation_results/v2/v2_offline_20260919_02/deterministic_fixtures`。先前生成的 `_01` 也保留，未覆盖。
结合旧真实模型结果的修正版证据报告为 `evaluation_results/v2/v2_evidence_corrected_report_20260919_02.md`；旧最终报告仍保留。

|场景|修正后状态|证据边界|
|---|---|---|
|E01–E04|PASS|真实调用权限策略或 pending 校验组件；只是组件单元证据，不是完整 Clinic 端到端故障注入|
|E05|NOT_READY|旧夹具只构造“一次提交、一次拒绝”事件，未真实重复交付操作|
|E06|NOT_READY|旧夹具只声明非原子 CAS，没有执行并发冲突实验|
|E07|NOT_READY|旧夹具只构造重启失效事件，没有真实销毁并重建服务|
|E08|NOT_READY|旧夹具没有向真实 SQLite 投影/对账组件注入故障|
|E09|NOT_READY|旧夹具没有在真实世界提交后注入 AgentState 写失败|
|E10|NOT_READY|旧夹具没有调用真实 bounded-output 与执行链完成两个子用例|
|E11|NOT_READY|旧夹具没有让真实 adapter 边界返回超时/未知 usage|
|E12|NOT_READY|旧夹具没有分别验证投影隔离与真实模型行为攻击|
|R01–R06|NOT_READY|旧夹具只构造候选结果事件；属于评分器合成轨迹，不是 reflection validator/lifecycle 的生产证据|

报告生成器现将工程 `FAIL`、`UNKNOWN`、`NOT_READY` 都计入“未就绪”。合成轨迹仍可用于 grader 单元测试，但不再产生生产机制 PASS。

## 5. 下一步真实模型最小对照计划（待预算批准）

建立单独版本的 `v2_stall_probe_v1`，专门检查行为是否依赖明确的阶段提示。它不并入正式 T/M 成绩，也不作为“修复前与修复后成功率”对比：两个条件都使用同一版已修复代码、同一 checkpoint 和同一配置，唯一自变量是 continuation 文本。用生产规则离线准备一个“旧纸伞案诊断已授权提交、尚未治疗”的公开 checkpoint，克隆为两个隔离状态。固定 `deepseek-flash`、temperature 0、checkpoint、权限、grader 与 Trace v2，并保留原 16 回合协议中剩余的 7 回合，只改变诊断提交后的玩家继续输入：

1. 中性条件：沿用“请依据当前公开状态继续推进，不要让我提示下一步骤”。
2. 阶段提示条件：只复述公开状态已进入处置阶段，要求继续评估公开处置；不提供正确 treatment ID 或答案。

先各 1 次，共 2 个 continuation。旧 `t01_r01` 第 10–16 回合实际发生 8 次调用、费用 0.0710 元；预计两条件共约 16–28 次调用、约 0.14–0.22 元，建议硬预算 0.25 元。这个 probe 只用于定位阶段提示依赖及诊断后的动作链差异，不估计修复效果或端到端任务成功率，也不进入任何正式 T/M 汇总。

若两条 Trace 完整且能区分主动 RESPOND、校验/fallback、计划推进和权限链，再运行完整旧纸伞 episode：每条件 2 次，共 4 episodes。依据旧 T01 cooperative 运行，预计 92–104 次调用、约 0.71–0.89 元，建议该阶段硬预算 1.20 元。不会自动运行 126 次完整回归。
