# 文档导航

本页保留全部实验、停止记录和负结果，同时把当前产品总纲与常用路径放在前面。产品身份以 [`PROJECT_MASTER_BLUEPRINT.md`](PROJECT_MASTER_BLUEPRINT.md) 为准，系统边界以 [`PRODUCT_SYSTEM_ARCHITECTURE.md`](PRODUCT_SYSTEM_ARCHITECTURE.md) 为准，里程碑状态以 [`ROADMAP.md`](ROADMAP.md) 为准；架构决策以 [`DECISIONS.md`](DECISIONS.md) 为准。

## 当前产品总纲

- [`PROJECT_MASTER_BLUEPRINT.md`](PROJECT_MASTER_BLUEPRINT.md)：《问道医途》固定主题、玩家/导师身份、产品循环和非目标。
- [`PRODUCT_SYSTEM_ARCHITECTURE.md`](PRODUCT_SYSTEM_ARCHITECTURE.md)：病例、导师、教学、成长、关系、记忆、权限与传承的权威边界和数据流。
- [`PRODUCT_COMPLETION_PLAN_V1.md`](PRODUCT_COMPLETION_PLAN_V1.md)：M0～M6 之后的 R1～R6 产品完成顺序。
- [`R1_APPRENTICESHIP_GROWTH.md`](R1_APPRENTICESHIP_GROWTH.md)：R1 长期状态、成长规则、事件、协调与公开边界。
- [`R2_MENTOR_TEACHING_LOOP.md`](R2_MENTOR_TEACHING_LOOP.md)：R2 导师角色、固定课程、提示、师评、恢复与 CLI 边界。
- [`R3_ADAPTIVE_THREE_CASE_TEACHING.md`](R3_ADAPTIVE_THREE_CASE_TEACHING.md)：R3 三核心课、固定补课、长期教学计划、结构化记忆与恢复边界。
- [`R4_EXAM_PERMISSION_INHERITANCE.md`](R4_EXAM_PERMISSION_INHERITANCE.md)：R4 正式考试、补课重考、权限过滤、可达性审计与第一条传承链。
- [`R5_SIX_CASE_CLINIC_PRODUCT.md`](R5_SIX_CASE_CLINIC_PRODUCT.md)：R5 六病例、组合式医馆服务、安全边界与传承作用。
- [`R5_CASE_DESIGN.md`](R5_CASE_DESIGN.md)：三个进阶病例及课程设计。
- [`R5_CLINIC_USER_GUIDE.md`](R5_CLINIC_USER_GUIDE.md)：普通用户启动、游玩、退出和恢复指南。
- [`R6_OFFLINE_PRODUCT_ACCEPTANCE.md`](R6_OFFLINE_PRODUCT_ACCEPTANCE.md)：八路线、确定性重复运行与真实性分层。
- [`R6_REAL_MENTOR_PILOT_PLAN.md`](R6_REAL_MENTOR_PILOT_PLAN.md)：未来付费 Pilot 的四场景和硬门禁；未运行。
- [`R6_PLAYTEST_PROTOCOL.md`](R6_PLAYTEST_PROTOCOL.md)：15/45分钟试玩材料、数据最小化与严重问题门槛；未执行。
- [`R6_RELEASE_READINESS_AUDIT.md`](R6_RELEASE_READINESS_AUDIT.md)：发布前离线审计和仍存在的发布阻塞项。
- [`M5_PRODUCT_GAP_AUDIT.md`](M5_PRODUCT_GAP_AUDIT.md)：按 L0～L5 重新审计 M5 的产品成熟度、缺口和下一验收条件。
- [`ROADMAP.md`](ROADMAP.md)：区分 M0～M6 历史与 Product Completion Plan v1 的 R1～R6 主线。

## 快速开始与作品集

- [`../README.md`](../README.md)：项目概览、安装、游玩与限制。
- [`M5_DEMO_GUIDE.md`](M5_DEMO_GUIDE.md)：3 分钟及 8～10 分钟演示脚本。
- [`M5_PORTFOLIO_EVIDENCE.md`](M5_PORTFOLIO_EVIDENCE.md)：Agent 应用岗与游戏 AI 产品岗证据分层。
- [`assets/README.md`](assets/README.md)：三张真实离线终端素材的来源、SHA 与隐私记录。
- [`TECHNICAL_OVERVIEW.md`](TECHNICAL_OVERVIEW.md)：M6-P2 首页重构前的详细 README 历史内容。
- [`M6_P1_DISTRIBUTION_VERIFICATION.md`](M6_P1_DISTRIBUTION_VERIFICATION.md)：wheel/sdist、干净安装和 CI 准备证据。
- [`M6_P2_PORTFOLIO_VERIFICATION.md`](M6_P2_PORTFOLIO_VERIFICATION.md)：招聘首页、演示素材、链接与分发回归证据。
- [`M6_PORTFOLIO_RELEASE_PLAN.md`](M6_PORTFOLIO_RELEASE_PLAN.md)：P0～P4 发布路径；P4 前不创建远程或发布。

## 架构与安全

- [`DECISIONS.md`](DECISIONS.md)：追加式 ADR。
- [`AGENT_VARIANTS.md`](AGENT_VARIANTS.md)：V0/V1/V2 与安全过滤边界。
- [`algorithm-experiment-plan-v0.2.md`](algorithm-experiment-plan-v0.2.md)：当前实验设计；v0.1 仅是历史版本。
- [`M2_EXIT_AUDIT.md`](M2_EXIT_AUDIT.md)：结构化 Agent、预算和真实模型边界。
- [`M5_P4C_AGENT_CONTRACT_AUDIT.md`](M5_P4C_AGENT_CONTRACT_AUDIT.md)：公开行动契约与拒绝恢复。

## 三病例与 Campaign

- [`M5_MULTI_CASE_VERTICAL_SLICE_PLAN.md`](M5_MULTI_CASE_VERTICAL_SLICE_PLAN.md)：产品范围与阶段设计。
- [`M5_CASE_DESIGN.md`](M5_CASE_DESIGN.md)：三个病例、公开/隐藏边界和参考轨迹。
- [`M5_CAMPAIGN_CONTINUITY.md`](M5_CAMPAIGN_CONTINUITY.md)：确定性跨 Episode 连续性和知识成长。
- [`M5_AGENT_MODES.md`](M5_AGENT_MODES.md)：manual、Fake、DeepSeek V0 与 semantic shadow 隔离。
- [`M5_EXIT_AUDIT.md`](M5_EXIT_AUDIT.md)：纵向切片最终验收。

## MCP

- [`M3_EXIT_AUDIT.md`](M3_EXIT_AUDIT.md)：9 个工具、进程内调用、真实 stdio 子进程、持久化、重启和关闭。
- [`VERIFICATION.md`](VERIFICATION.md)：M3-P0/P1 专项命令与测试证据。

## 记忆与 Embedding

- [`M4_MEMORY_PLAN.md`](M4_MEMORY_PLAN.md)：可信事件投影、SQLite 权威记忆和 Top-K 架构。
- [`M4_MEMORY_EVALUATION_PLAN.md`](M4_MEMORY_EVALUATION_PLAN.md)：14 条离线工程 Gold。
- [`M4_EXIT_AUDIT.md`](M4_EXIT_AUDIT.md)：Fake Embedding 工程里程碑边界。
- [`M45_REAL_MEMORY_VALIDATION_PLAN.md`](M45_REAL_MEMORY_VALIDATION_PLAN.md)：本地真实 Embedding 验证方案。
- [`M45_P2B_SEMANTIC_FAILURE_ANALYSIS.md`](M45_P2B_SEMANTIC_FAILURE_ANALYSIS.md)：Dense 检索失败根因。
- [`M45_P2D_HOLDOUT_PILOT_REPORT_20260810.md`](M45_P2D_HOLDOUT_PILOT_REPORT_20260810.md)：新 holdout 双运行负结果。
- [`M45_TERMINATION_AUDIT.md`](M45_TERMINATION_AUDIT.md)：`closed_with_known_dense_retrieval_limitations` 终止结论。

## 真实正负实验

- [`M5_P4B_DEEPSEEK_CAMPAIGN_PILOT_20260811.md`](M5_P4B_DEEPSEEK_CAMPAIGN_PILOT_20260811.md)：灰灶未闭环、月井未启动的真实负结果。
- [`M5_P4D_DEEPSEEK_RECOVERY_VALIDATION_20260811.md`](M5_P4D_DEEPSEEK_RECOVERY_VALIDATION_20260811.md)：通用契约修复后的单次真实恢复案例。
- [`PILOT_DIAGNOSTIC_001.md`](PILOT_DIAGNOSTIC_001.md)、[`PILOT_REVIEW_V021_001.md`](PILOT_REVIEW_V021_001.md)、[`PILOT_STANDARD_FIXED_V0_001.md`](PILOT_STANDARD_FIXED_V0_001.md)：M2 真实模型诊断和标准探针历史。

这些记录不是正式成功率，也不应被合成指标替代。

## 退出审计与发布审计

- [`M2_EXIT_AUDIT.md`](M2_EXIT_AUDIT.md)
- [`M3_EXIT_AUDIT.md`](M3_EXIT_AUDIT.md)
- [`M4_EXIT_AUDIT.md`](M4_EXIT_AUDIT.md)
- [`M45_TERMINATION_AUDIT.md`](M45_TERMINATION_AUDIT.md)
- [`M5_EXIT_AUDIT.md`](M5_EXIT_AUDIT.md)
- [`M6_RELEASE_READINESS_AUDIT.md`](M6_RELEASE_READINESS_AUDIT.md)：P0 当时检查点及 P1 后续处理说明。
- [`M6_P2_PORTFOLIO_VERIFICATION.md`](M6_P2_PORTFOLIO_VERIFICATION.md)：P2 本地首页和素材收口；没有远程或发布。

## 历史检查点

- [`algorithm-experiment-plan-v0.1.md`](algorithm-experiment-plan-v0.1.md)：历史实验方案，不是当前执行状态。
- `M45_P2_V2_*STOP_20260810.md`：入口、身份和遥测三次诚实停止记录。
- [`M45_P2A_SEMANTIC_GOLD_V2_FREEZE.md`](M45_P2A_SEMANTIC_GOLD_V2_FREEZE.md)、[`M45_P2C_SEMANTIC_HOLDOUT_FREEZE.md`](M45_P2C_SEMANTIC_HOLDOUT_FREEZE.md)：Gold 冻结身份。
- [`VERIFICATION.md`](VERIFICATION.md)：从 M0 至今的可复现验证日志。
