# 《异闻行录》产品与工程路线图

本页按当前工作区中的实现和可审核结果区分状态。代码存在不等于收益已经证明；冻结计划存在不等于评测已经完成；历史实验结果也不自动代表当前版本。

## Completed / Implemented

- 六个正式志怪案件、本地 Web 产品入口和跨案件 Campaign；
- 由 `CaseEngine` 独占权威世界写入的调查、诊断、处置、事件与评分链；
- 玩家自然语言贡献、Agent 独立评价与人机协商；
- 严格 structured proposal、一次有限修复、动作契约修复遥测和 safe fallback；
- 公开 Observation、`GoalPlanPolicy`、`PublicActionContractValidator` 和 `NPCAuthorityPolicy` 的分层校验；
- 诊断协商、不可逆处置确认、拒绝后旧 pending 失效及新确认绑定；
- 持久 Goal/Plan、Plan/Decision 对齐校验和确定性计划完成评估；
- JSON 权威状态快照、事件回放、SQLite 记忆存储、投影回执与对账；
- 玩家隔离、生命周期过滤和 BGE-M3 稠密向量排序的长期 Memory；
- 证据包、候选校验、保守 consolidation、索引回执和 `no_write` 的 Reflection 生命周期；
- 请求、修复、provider ID、usage、费用、Trace 和不可变 artifact 遥测；
- A0 `SimpleActionGameNPCAgent` 与 A1 `GameNPCAgent` 两个真实模型入口，以及共享的安全执行链；
- 评测冻结哈希、唯一调度、预检、分池预算、停止门控和离线重评分基础设施；
- 当前工作区 590 项 pytest 回归通过。

恢复能力的准确边界是：**支持权威状态快照、事件回放、记忆投影对账和部分故障恢复。pending confirmation 重启恢复、严格的同 session 原子并发以及部分跨存储恢复路径仍未完成。**

## Frozen / Evaluation Status

### V2.1 精简首轮

54-episode `G18 + C24 + M12` 计划曾以 `READY / AWAITING_NEW_PAID_AUTHORIZATION` 冻结，随后已经发生真实模型执行，不能再标为“尚未运行”：

- G 完成 18 项，严格成功 17/18；这是已暴露回归任务结果；
- 原 C 24 项在 provider 调用前因 campaign rule 实现缺陷中止；
- 原 M 首项调用后因 artifact contract 失败，剩余 11 项未启动；
- 因此原批次没有有效的 A0/A1 或 M0/M1 比较结果。

### C/M recovery

新的 C24+M12 recovery 包完成了真实模型执行，但只形成部分可用结论：

- M 完成 12/12，形成 6 个有效 M0/M1 配对；两条件均为 6/6 严格成功，没有观察到任务成功收益，M1 平均成本更高；
- C 计划 24 项，只启动 16 项，形成 8 个完整 A0/A1 配对；另 8 项、即 4 个配对未启动；
- 已执行配对中 A0 为 0/8、A1 为 8/8，但 A0 未获得与 A1 等价的精确公开 action arguments，归因受到接口不对称混杂；该批次不能证明“显式规划优于直接行动”；
- 完整 54 项不能合并为一个总成功率，`20/36` 也不是模型成功率，因为其中 8 个计划 C 项没有模型结果。

后续评测必须先让 A0/A1 获得等价的动作接口、保留 schema 失败响应的 usage，再冻结新的 C-only 完整配对计划并另行授权。完整 162-episode 设计、独立 Reflection、真实攻击、并发与重启恢复不属于已完成结果。

## Known Gaps / Not Completed

### 状态、一致性与恢复

- **Same-session atomic concurrency**：当前 revision 检查和文件替换不是数据库级原子 CAS；还没有证明并发旧 revision 请求只能提交一次或严格排序。
- **Pending confirmation restart restoration**：pending 主要保存在进程内，重启后不能完整恢复原确认 ID、动作摘要、owner 和失效语义。
- **Complete cross-store recovery**：world、AgentState 与 SQLite memory 分开提交；部分对账已经实现，完整的故障注入、重启修复和不重复副作用证据链尚未闭环。
- **Concurrency/crash drills**：尚未系统执行并发竞争、各提交边界崩溃、重启和恢复演练。

### 模型与能力证据

- **Structured-output stability**：原始 schema 遵循仍不稳定，需要继续降低修复与 fallback 依赖，并完整保留失败响应 usage。
- **Fair A0/A1 comparison**：A0/A1 已实现，但当前 C 结果受接口不对称影响，且 4 个配对未启动；尚无公平、完整的真实模型架构比较。
- **Memory benefit evidence**：检索、隔离和曝光已验证；当前有效配对没有观察到任务成功收益，尚未证明稳定的行为收益。
- **Reflection downstream benefit**：机制和有限真实生成已验证；经验质量、错误记忆率和后续任务收益尚未充分验证。
- **New-task generalization and human play evidence**：当前样本仍小，部分任务已暴露；真人体验和新任务泛化证据不足。

### 安全与部署

- **Real attack track**：尚未完成冻结的真实模型攻击轨道。
- **Prompt injection coverage**：已有权限和不可信输入边界，但没有充分覆盖输入位置、持久记忆和工具结果中的攻击组合。
- **Authentication / multi-tenant isolation**：当前 player scope 不是公网身份认证，也不构成生产多租户隔离。
- **OS/container sandbox**：领域工具白名单不等于操作系统或容器沙箱。
- **Public deployment security**：产品仍是本地回环服务，没有完成公网部署、TLS、密钥管理、限流、告警和安全运维验证。
- **Broad safety claim**：有限批次中没有观察到授权失败，不能推出系统无安全漏洞或已经全面安全。

## Next Milestones

1. 对齐 A0/A1 的公开 action space、参数契约和修复反馈，冻结新的 C-only 配对评测；
2. 修复 schema 失败响应的 usage 保留与 artifact 汇总，再执行完整可重评分验证；
3. 为同 session 引入可证明的串行化或原子事务边界，并完成冲突注入；
4. 持久化 pending confirmation，并验证重启后的匹配、过期和失效行为；
5. 完成 world / AgentState / memory 各提交边界的故障注入和对账恢复；
6. 在独立冻结协议下扩展 Memory、Reflection、真实攻击和真人试玩证据。

评测历史、冻结包和结果报告的正式入口见[证据导航](../INDEX.md)。
