# 文档导航

项目文档按“当前产品、架构、作品集、当前验收、历史证据”分层。文件移动只改善导航，不删除或改写历史结论。

## 第一次接触项目

- [开始游戏](../START_HERE.md)：只包含安装、启动、恢复和退出。
- [项目首页](../README.md)：产品定位、证据和诚实边界。
- [当前路线图](product/ROADMAP.md)：R1～R6 当前状态。

## 产品

- [产品完成计划](product/PRODUCT_COMPLETION_PLAN_V1.md)
- [长期成长](product/R1_APPRENTICESHIP_GROWTH.md)
- [导师教学闭环](product/R2_MENTOR_TEACHING_LOOP.md)
- [自适应课程与补课](product/R3_ADAPTIVE_THREE_CASE_TEACHING.md)
- [考试、权限与传承](product/R4_EXAM_PERMISSION_INHERITANCE.md)
- [六病例医馆](product/R5_SIX_CASE_CLINIC_PRODUCT.md)
- [病例设计](product/R5_CASE_DESIGN.md)
- [医馆用户指南](product/R5_CLINIC_USER_GUIDE.md)

## 架构与决策

- [项目总纲](architecture/PROJECT_MASTER_BLUEPRINT.md)
- [产品系统架构](architecture/PRODUCT_SYSTEM_ARCHITECTURE.md)
- [ADR](architecture/DECISIONS.md)
- [Agent 变体](architecture/AGENT_VARIANTS.md)
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

## Cooperative Agent Benchmark

- [M5 最终 Benchmark 与失败分析报告](benchmarks/m5/agent_benchmark_report.md)
- [M5-12 post-fix sanitized artifact](benchmarks/m5/m5_12_postfix_real_benchmark.json)
- [M5-3 / M5-12 pre-post summary](benchmarks/m5/m5_12_pre_post_summary.json)

该报告属于历史 Cooperative/DoctorAgent 工程评测，不代表当前 MentorAgent 产品效果或统计成功率。

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

这些记录继续按形成当时的身份解释，不代表当前 MentorAgent 成功率、真人收益或生产能力。

## 工具与数据

- [发布工具](../tools/release/)
- [历史实验工具和数据](../tools/experiments/README.md)
- [实验数据与历史证据迁移索引](archive/evidence/README.md)

正式产品资源的唯一真源是 `src/xuanyi_npc/resources/`；实验输入和历史证据不进入产品分发包。

`.venv/`、`runtime_models/`、`runtime_data/` 和 `results/` 仅保留在本机并由 Git 忽略。
