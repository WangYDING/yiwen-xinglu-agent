# 《异闻行录》证据导航

本页是产品事实、代码入口、评测历史和证据边界的统一导航。《异闻行录》是由单一主 Agent 驱动的 Human-Agent Cooperative Game NPC System，不是通用 Agent 平台或多 Agent 系统。

阅读评测材料时应区分四种状态：

- **Current implementation**：当前工作区中已有真实代码和回归覆盖；
- **Observed result**：在明确冻结协议下实际运行得到的结果；
- **Frozen / awaiting work**：协议或执行包存在，但相应范围尚未完整运行；
- **Historical / superseded**：保留用于追踪演化，不能作为当前最终结论。

## Start Here / Product

- [项目首页](../README.md)：对外产品说明、运行链、关键证据和当前限制。
- [开始游戏](../START_HERE.md)：本地安装、LLM/离线模式、预算授权和状态目录。
- [项目总纲](architecture/PROJECT_MASTER_BLUEPRINT.md)：产品身份、玩家/Agent/确定性系统的责任边界。
- [产品案件设计](product/R5_CASE_DESIGN.md)：六个正式案件与体验设计。
- [产品路线图](product/ROADMAP.md)：已实现、评测状态、明确缺口和下一里程碑。
- [正式案件资源](../src/xuanyi_npc/resources/cases/)：六案的运行时数据。

## Architecture

- [产品系统架构](architecture/PRODUCT_SYSTEM_ARCHITECTURE.md)：当前组件、数据流与持久化边界。
- [技术总览](architecture/TECHNICAL_OVERVIEW.md)：简洁运行链和资源边界。
- [架构决策记录](architecture/DECISIONS.md)：模型提案/规则提交、玩家贡献、记忆来源和安全失败等 ADR。
- [主 Agent](../src/xuanyi_npc/agents/game_npc.py)：A1 结构化决策、Goal/Plan proposal、修复与 fallback。
- [协作运行时](../src/xuanyi_npc/application/cooperative_runtime.py)：单回合编排、确认、执行、状态推进与遥测。
- [权威案件引擎](../src/xuanyi_npc/engine/case_engine.py)：调查、诊断、处置、评分与权威状态变更。

## Runtime / Agent / Authority

- [公开行动契约](../src/xuanyi_npc/application/action_contract.py)：从当前 Observation 投影精确行动空间，并拒绝未知目标、额外参数和未公开证据。
- [Goal/Plan 策略](../src/xuanyi_npc/application/goal_plan_policy.py)：Goal/Plan 更新及 PlanStep—Decision 对齐校验。
- [确定性计划评估](../src/xuanyi_npc/application/plan_evaluator.py)：依据环境事实判断保持、推进、完成或结束。
- [NPC 权限策略](../src/xuanyi_npc/application/npc_authority.py)：自主调查、诊断协商和处置确认的风险分层。
- [工具执行器](../src/xuanyi_npc/application/case_tools.py)：将通过校验的公开工具映射为领域命令。
- [JSON 状态存储](../src/xuanyi_npc/storage/json_store.py)：玩家、案件、Agent 和 Campaign 快照；revision 检查不是数据库级原子 CAS。
- [MCP server](../src/xuanyi_npc/mcp_server/server.py)：独立 stdio 集成入口；主 Agent 运行链不经过 MCP client。

## Human-Agent Cooperation

- [协作领域契约](../src/xuanyi_npc/domain/cooperation.py)：玩家贡献、评价、决策、确认和回合结果。
- [玩家体验编排](../src/xuanyi_npc/application/player_experience.py)：贡献记录与协作体验投影。
- [M1–M5 架构与面试审计](final_agent_architecture_and_interview.md)：当前能力映射与表达边界；形成于 V2.1 前，涉及评测结论时应以后续 V2/V2.1 报告为准。

## Planning / Replanning

- [规划领域契约](../src/xuanyi_npc/domain/cooperative_planning.py)：Goal、Plan、Step、Evaluation 和状态转换。
- [P0 计划行动恢复修复](p0_plan_action_recovery_fix_report.md)：历史修复阶段。
- [P1 诊断行动审计](p1_diagnosis_action_selection_audit.md)与[修复报告](p1_diagnosis_action_selection_fix_report.md)：历史修复阶段。
- [P2 Plan/Decision 对齐审计](p2_plan_decision_alignment_audit.md)、[修复报告](p2_plan_decision_alignment_fix_report.md)与[P2a 遥测](p2a_alignment_telemetry_report.md)。
- [P3 模型可见诊断契约](p3_model_visible_diagnosis_contract_fix_report.md)、[结构化修复失败审计](p3_structured_repair_failure_audit.md)与[P3a 修复遥测](p3a_repair_attempt_telemetry_report.md)。
- [P4 处置动作契约修复](p4_treatment_action_contract_fix_report.md)与[停滞审计](p4_treatment_stall_quick_audit.md)。
- [P5 可执行步骤承诺修复](p5_executable_step_decision_commitment_fix_report.md)与[旧纸伞审计](p5_old_paper_treatment_decision_audit.md)。

P0–P5 是从失败轨迹到当前行为的修复链，不是六组可以相加的独立效果实验。

## Memory

- [Memory 实现报告](PHASE_B_MEMORY_IMPLEMENTATION_REPORT.md)：权威来源、投影、检索、隔离和生命周期。
- [Memory 评测说明](evaluation/memory_evaluation.md)：机制证据、真实 Agent 曝光和非结论。
- [跨 session Memory 暴露实现](e9_cross_session_memory_exposure_implementation.md)与[真实 Agent pilot](e10_real_agent_memory_exposure_pilot.md)。
- [SQLite Memory repository](../src/xuanyi_npc/storage/sqlite_memory.py)：事务写入、来源回执、纠正、失效、删除、embedding 和 Reflection 回执。
- [Memory 检索](../src/xuanyi_npc/application/memory_retrieval.py)与[生产协调](../src/xuanyi_npc/application/memory_coordination.py)。
- [M4.5 语义 Memory 实验归档](archive/M45_SEMANTIC_MEMORY_EXPERIMENT.md)：BGE-M3、Gold/Holdout 和负结果的历史依据；它是有限工程证据，不是生产成功率或行为收益证明。
- [M4.5 工具与冻结数据](../tools/experiments/README.md)。

当前已证明持久化、隔离、检索和有限曝光；没有证明 Memory 稳定提升任务成功率。V2.1 有效 M 配对中 M0/M1 都是 6/6 严格成功，没有观察到任务成功差异。

## Reflection

- [Reflection 实现报告](PHASE_C_REFLECTION_IMPLEMENTATION_REPORT.md)与[生产审计](PHASE_C_REFLECTION_PRODUCTION_AUDIT.md)。
- [Reflection 评测说明](evaluation/reflection_evaluation.md)：确定性机制、真实生成与证据边界。
- [E11 OFAT harness](e11_reflection_ofat_harness_implementation.md)：固定候选下的机制验证。
- [E12 真实模型 pilot](e12_real_agent_reflection_ofat_pilot.md)与[E13 no-write 根因审计](e13_reflection_no_write_root_cause_audit.md)。
- [Reflection 生成与校验](../src/xuanyi_npc/application/reflection.py)、[生命周期](../src/xuanyi_npc/application/reflection_lifecycle.py)和[Memory consolidation](../src/xuanyi_npc/application/reflection_memory.py)。

当前证明的是机制和有限真实生成，不是模型参数训练、稳定下游收益或持续自我进化。

## Evaluation History

### M1–M5：早期 Cooperative Agent 验证

- [M5 Agent Benchmark](benchmarks/m5/agent_benchmark_report.md)与[M5 pre/post summary](benchmarks/m5/m5_12_pre_post_summary.json)。
- [早期 Agent benchmark 报告](agent_task_benchmark_report.md)、[失败审计](agent_task_benchmark_failure_audit.md)与[评测审计](agent_evaluation_benchmark_audit.md)。

这些材料保留为历史能力建设证据。涉及当前可靠性时，应继续阅读 E 系列、V2 和 V2.1；不能把 M1–M5 的局部结果包装成当前最终成绩。

### E2–E13：冻结基线、Memory 与 Reflection

- [E2 招聘评测冻结](e2_recruitment_evaluation_freeze.md)。
- [E3 冻结 3×3 统计报告](e3_frozen_3x3_statistical_evaluation_report.md)与[E4 失败审计](e4_frozen_3x3_failure_audit.md)。
- [E5 structured fallback 修复](e5_structured_fallback_policy_fix_report.md)。
- [E6 post-E5 冻结 3×3 可靠性报告](e6_post_e5_frozen_3x3_reliability_report.md)：历史冻结基线，3 案 × 3 次，Task Success 8/9。该结果只适用于该协议，不是线上成功率。
- [E7 Memory/Reflection 消融设计](e7_memory_reflection_ablation_design.md)与[E8 评测协议](e8_memory_reflection_evaluation_protocol.md)：设计与协议材料，不等于已经获得收益结论。
- [E9–E13 Memory/Reflection 材料](evaluation/README.md)：统一说明其机制证据和非结论。
- [能力稳定化历史](evaluation/capability_stabilization.md)与[任务结果说明](evaluation/task_benchmark_and_results.md)。

### V2：完整运行与失败暴露

- [V2 原设计](evaluation/v2_design/README.md)：historical design，后续已由 V2.1 修订。
- [V2 stall remediation](evaluation/v2_stall_remediation_20260919.md)与[两次小批次计划](evaluation/v2_small_batch_regression_plan_20260919.md)、[修订计划](evaluation/v2_small_batch_regression_plan_20260920.md)。
- [V2 任务全量运行结果目录](../evaluation_results/v2/v2_task_full_20260918_01/)和[Memory 全量运行结果目录](../evaluation_results/v2/v2_memory_full_20260918_01/)：暴露了严重任务推进与评测问题；这些失败结果推动 P0–P5 修复，不是当前产品成功率。
- [最新诊断修复验证](../evaluation_results/v2/v2_diagnosis_validation_20260920_05/RESULTS_REPORT.md)：6 个 T 与 M01 三条件共 9/9，仅证明该小批次关键路径恢复；病例均为 development 或 validation-exposed，不是正式可靠性或 Memory 收益结论。

## Architecture Comparison

- [A0 `SimpleActionGameNPCAgent`](../src/xuanyi_npc/agents/simple_action.py)：只生成当前行动，无持久 Goal/Plan。
- [A1 `GameNPCAgent`](../src/xuanyi_npc/agents/game_npc.py)：维护持久 Goal/Plan，接受计划契约和确定性评估。
- [C 架构比较 runner](../src/xuanyi_npc/evaluation/v21_architecture_runner.py)。
- [Closure-audited C/M 结果](../evaluation_results/v21/v2_1_slim_cm_recovery_20260920_04/RESULTS_REPORT.md)：8 个已执行配对中 A0 0/8、A1 8/8，但 A0/A1 动作接口说明不对称；4 个配对未启动。该结果是 architecture-as-implemented 观察，不能证明显式 Planning 本身更优。

## V2.1

### Design and task surface

- [V2.1 修订设计](evaluation/v2_design/revision_20260920/README.md)：G 回归、C 架构、M 记忆、R Reflection、S 攻击和 E 工程轨道的完整设计；完整 162-episode 方案没有执行。
- [任务规格](evaluation/v2_design/revision_20260920/task_specs.md)与[设计矩阵](evaluation/v2_design/revision_20260920/design_matrix.json)。
- [四个评测专用案件](../src/xuanyi_npc/evaluation/fixtures/v21/cases/)：C01、C02、C09、C10，不属于六个正式产品案件。
- [精简首轮 catalog](evaluation/v2_design/revision_20260920/slim_first_round_catalog.json)：G18、C24、M12，共 54 个目标 Episode。

### Freeze and execution history

- [V2 精简首轮冻结包](evaluation/v2_design/revision_20260920/SLIM_FIRST_ROUND_FREEZE_V2.md)：历史状态曾为 `READY / AWAITING_NEW_PAID_AUTHORIZATION`；随后已执行，不能再解释为当前“尚未运行”。
- [原 54 项执行报告](../evaluation_results/v21/v2_1_slim_first_round_20260920_02/RESULTS_REPORT.md)：G 17/18；原 C/M 因实现缺陷失效。
- [C/M recovery freeze v4](evaluation/v2_design/revision_20260920/CM_RECOVERY_FREEZE_V4.md)：v3 已被 v4 supersede；冻结文档形成时等待新授权。
- [C/M recovery closure-audited 结果](../evaluation_results/v21/v2_1_slim_cm_recovery_20260920_04/RESULTS_REPORT.md)：M 12/12；C 启动 16/24，形成 8 个配对，另 8 项未启动；架构归因受接口不对称影响。

V2.1 没有一个可合并的总成功率。G 属于原冻结实验；C/M 属于独立 recovery 实验；未启动项目不是模型失败；`20/36` 也不是模型成功率。完整 162-episode 设计、独立 Reflection、真实攻击、并发和重启恢复仍未执行。

## Known Limitations

- 同一 session 的状态提交没有数据库级原子 CAS，严格并发安全尚未证明；
- pending confirmation 没有完整的重启恢复；
- world、AgentState 与 SQLite memory 的跨存储恢复尚未完全闭环；
- 原始 structured output schema 遵循仍不稳定；
- A0/A1 当前比较受到接口不对称混杂，且 C 配对未完整执行；
- Memory 的稳定行为收益没有被证明，当前有效配对没有任务成功差异；
- Reflection 的下游行为收益和经验质量没有被充分证明；
- 真实攻击、充分 prompt injection 覆盖、身份认证、多租户隔离、OS/container sandbox、公网部署安全和系统性并发/崩溃演练尚未完成。

详细状态与下一步见[产品与工程路线图](product/ROADMAP.md)。

## Local-only Artifacts

`.venv/`、`runtime_models/`、`runtime_data/`、`results/`、`evaluation_results/` 和 `.env` 通常不作为发布包内容。结果目录中的本地真实运行证据可用于当前工作区审计，但在对外引用前应确认其分发、隐私和不可变性边界。
