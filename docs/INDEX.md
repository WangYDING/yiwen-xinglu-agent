# 文档导航

项目文档按“当前 Cooperative GameNPC、保留的产品分支、架构、作品集、验证与历史证据”分层。文件移动只改善导航，不删除或改写历史结论。

## 第一次接触项目

- [开始游戏](../START_HERE.md)：只包含安装、启动、恢复和退出。
- [项目首页](../README.md)：产品定位、证据和诚实边界。
- [M5 最终 Benchmark 与失败分析报告](benchmarks/m5/agent_benchmark_report.md)：当前 Cooperative GameNPC 主链的冻结验证。

## Current：Cooperative GameNPC

- [项目首页](../README.md)：Human-Agent Cooperation、Goal/Plan、Memory、Reflection、Authority 与 CaseEngine。
- [M5 最终 Benchmark 与失败分析报告](benchmarks/m5/agent_benchmark_report.md)
- [M5-12 post-fix sanitized artifact](benchmarks/m5/m5_12_postfix_real_benchmark.json)
- [M5-3 / M5-12 pre-post summary](benchmarks/m5/m5_12_pre_post_summary.json)

M1～M5 是当前 Cooperative Agent engineering milestones。GameNPCAgent 自主形成行动意图并推进普通调查，玩家参与线索、质疑、诊断协商和高风险授权，确定性系统裁定合法性与世界状态。

## Retained Product Branch：Mentor Teaching / Clinic Progression

- [产品完成计划](product/PRODUCT_COMPLETION_PLAN_V1.md)
- [Mentor 分支路线图](product/ROADMAP.md)
- [长期成长](product/R1_APPRENTICESHIP_GROWTH.md)
- [导师教学闭环](product/R2_MENTOR_TEACHING_LOOP.md)
- [自适应课程与补课](product/R3_ADAPTIVE_THREE_CASE_TEACHING.md)
- [考试、权限与传承](product/R4_EXAM_PERMISSION_INHERITANCE.md)
- [六病例医馆](product/R5_SIX_CASE_CLINIC_PRODUCT.md)
- [病例设计](product/R5_CASE_DESIGN.md)
- [医馆用户指南](product/R5_CLINIC_USER_GUIDE.md)

以上内容仍是真实可运行或可审计的 retained teaching/presentation 与 Clinic progression 分支，但不再代表当前主 Agent 身份。

## 架构与决策

- [项目总纲](architecture/PROJECT_MASTER_BLUEPRINT.md)
- [产品系统架构](architecture/PRODUCT_SYSTEM_ARCHITECTURE.md)
- [ADR](architecture/DECISIONS.md)
- [历史 Agent 变体](archive/HISTORICAL_AGENT_VARIANTS.md)
- [历史技术总览](architecture/TECHNICAL_OVERVIEW.md)

## 当前验收

- [验证日志](evaluation/VERIFICATION.md)
- [R6 离线产品验收](evaluation/R6_OFFLINE_PRODUCT_ACCEPTANCE.md)
- [真实导师 Pilot 计划](evaluation/R6_REAL_MENTOR_PILOT_PLAN.md)
- [v3 冻结与结果](evaluation/R6_REAL_MENTOR_PILOT_V3_FREEZE.md)、[执行结果](evaluation/R6_REAL_MENTOR_PILOT_V3_RESULT.md)
- [真实导师医馆集成](evaluation/R6_REAL_MENTOR_CLINIC_INTEGRATION.md)
- [真实导师医馆烟雾](evaluation/R6_REAL_MENTOR_CLINIC_SMOKE_RESULT.md)
- [公开展示边界](evaluation/R6_PUBLIC_PRESENTATION_BOUNDARY.md)
- [真人试玩协议](evaluation/R6_PLAYTEST_PROTOCOL.md)
- [发布前审计](evaluation/R6_RELEASE_READINESS_AUDIT.md)

## Benchmark Interpretation

M5 报告是当前 Cooperative GameNPC 机制的冻结工程证据，其中保留 DoctorAgent baseline 和真实模型有限场景。它不代表 MentorAgent 教学效果、统计成功率或玩家收益。

## 作品集

- [演示素材及来源](portfolio/assets/README.md)
- 历史演示脚本与作品集验证保存在 [archive](archive/) 中。

## 历史证据

[archive](archive/) 完整保留：

- M2、M3、M4 退出审计；
- M4.5 BGE、语义 Gold、停止记录、负结果和终止审计；
- M5 DoctorAgent、多病例纵向切片、真实正负 Pilot 与退出审计；
- M6 分发、作品集和发布准备历史；
- R6 v1/v2 Pilot 停止、诊断、冻结和结果。

这些记录继续按形成当时的身份解释。R-series 是 retained product/teaching evolution；DoctorAgent、旧 Pilot、M4.5 与语义检索负结果按 historical/baseline evidence 阅读，不代表当前 Cooperative GameNPC 的玩家收益或生产能力。

## 工具与数据

- [发布工具](../tools/release/)
- [历史实验工具和数据](../tools/experiments/README.md)
- [实验数据与历史证据迁移索引](archive/evidence/README.md)

正式产品资源的唯一真源是 `src/xuanyi_npc/resources/`；实验输入和历史证据不进入产品分发包。

`.venv/`、`runtime_models/`、`runtime_data/` 和 `results/` 仅保留在本机并由 Git 忽略。
