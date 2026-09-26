# CE-2A 账本写入失败停止批次修复（v3）

日期：2026-09-26。范围仅限真实运行准备的账本失败边界；真实网络调用与费用均为 0。

## 复现与调用链

基于实际未提交工作区检查；适用的全局 AGENTS.md 为空，项目及父目录未发现其他 AGENTS.md。没有以 HEAD 替代工作区基线，也没有重置、提交或推送既有改动。

新增离线故障注入先在修复前运行：3 项失败。started/completed 写失败被普通异常 fallback 吞掉，run_real 未抛异常并结束批次；provider timeout 后 error 写失败被吞掉，生成 fallback 回合产物后才由外围不确定性检查停止。旧报告中“terminal 写失败阻止后续执行”的陈述因此不能作为已验证保证。

调用链为 run_real → _execute_one → Clinic → Runtime → GameNPCAgent → PaidEvidenceAdapter。首次与格式修复已有 LLMAdapterError.abort_episode 传播；行动契约修复原来捕获所有 Exception 并 fallback，需要同时修补。

## 最小修复

- PaidEvidenceAdapter 的 started/completed/error 写入统一经过 _append；失败设置 uncertain、锁存 PaidRequestEvidenceError（abort_episode=true），后续调用直接抛出同一错误，不再进入 provider adapter。
- started 写失败发生在调用底层 adapter 之前；completed 写失败发生在已返回回复之后，回复不交给模型解析和工具执行。
- error 写失败保留原 provider_error、usage、prior_usages 和预算快照。已知异常费用计入单回合已知费用；usage 或费用缺失仍停止并保留未知状态，不算零费用。
- 行动契约修复传播不可继续异常，保留先前 usage。普通可恢复错误的 fallback 行为未更改；最终行动与 Plan 二次对齐保护未更改。
- run_real 在每回合结束后再次检查锁存失败并中断，不能进入下一回合。RUNNING.json 在可写时保留失败记录及总预算证据；原账本写入不重试。

证据字段 provider_adapter_invoked 只表示是否进入底层 complete，不声称网络已送达或 provider 已计费。started=false 可确定本次未调用；completed 可确定回复已返回；error 的外部结果依赖原异常与 usage，未知保持未知。若整个存储不可写，无法保证备用文件落盘；异常对象仍保留失败记录，已有 RUNNING/claim 禁止自动续跑。未新增跨存储事务或 exactly-once 承诺。

## 版本与实测

新增 fixtures/ce2a_context_behavior/v3，默认 runner 使用 v3。场景、私有 rubric、C/T、52 回合与 104 调用上限保持 v2 语义；fixture/experiment 身份改为 v3，JSON schema 仍沿用兼容的 v2。新 manifest 覆盖当前源文件及测试，并记录旧 v2 文件哈希。v1/v2 文件未改写；v2 旧源码哈希与当前源码不匹配属于预期，不把旧版本改称当前已验证版本。

本轮实际执行：

- 修复前故障注入：3 项预期失败。
- 行为评测与 DeepSeek adapter 专项：46 项通过。
- 加上 CE-1.1、CE-2A 相关回归：87 项通过。
- 全量离线回归：657 项通过（51.63 秒）。
- v3 离线预检：ready，冻结内容身份全部匹配，真实入口按默认禁用配置阻断。
- git diff --check：通过。

故障测试覆盖 started 零 provider 调用、completed/error 停止批次、格式与行动契约修复失败传播、世界 revision 与行动不变、已知费用保留、原始异常保留以及锁存后禁止再次调用。完整专项还覆盖正常初始/修复路径、预算保护与 52 回合离线 dry-run。上述模拟结果不证明语义理解收益。交接中旧的 40/99/651 项结果仍属于前一轮报告，未混作本轮结果。

## 下一阶段仍需满足

本轮结束于离线准备。尚未选择真实模型、核验当前官方价格或批准预算；价格 SHA/日期只证明配置身份与有效期。选定模型后还须核验完整 payload UTF-8 字节数加 framing allowance 的 token 上界依据，计算费用上界，冻结具体子集、价格与授权 ID，再由用户明确批准模型、范围和费用。

原建议 H02/H05/H03/P01A 各一次 C/T（8 回合、最多 16 次调用）仍只是计划。未运行付费模型；未实施 CE-2B、意图识别、讨论回合或自动摘要。
