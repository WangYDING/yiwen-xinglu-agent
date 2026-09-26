# CE-2A 最终请求上下文有限质量验收

日期：2026-09-26
范围：现有 CE-0／CE-1／CE-1.1／CE-2A 与行为评测 v3 的离线上下文质量；不含 CE-2B、真实模型调用或付费运行准备。

## 结论

本轮没有确认到需要修改代码或冻结夹具的缺口。代表性最终 adapter 请求具备当前案件事实、玩家本轮贡献、必要 Goal/Plan、完整历史回合、有效 pending 公开投影和明确的非授权边界；历史裁剪、重启、格式修复与行动契约修复均保持设计的不变量。没有仅因文本可继续扩充、长度变化或排版差异而实施修改。

当前状态已具备进入“小批量真实评测准备阶段”的上下文工程前提，但尚不具备直接运行付费评测的授权和配置条件。真实模型是否正确消解指代、处理改口、对歧义发起澄清以及利用 omission 提示，仍只能由后续固定模型对照回答。

## 实际范围与证据

- 以当前未提交工作树为基线；分支为 `main`，相对 `origin/main` 超前 1 个提交，CE 实现、评测和 fixtures 中有大量既有未提交/未跟踪内容。没有用 HEAD 替代当前基线，没有重置、覆盖、提交或推送。
- 项目目录、父目录及核对的上级目录未发现适用 `AGENTS.md`。
- 阅读了 CE 总体/CE-2 设计、CE-1.1、行动契约 Plan 对齐、CE-2A 实施与 replay 修补、行为评测实现和 v3 账本失败报告；报告只用于导航，结论以代码、测试、冻结请求和实际离线请求为依据。
- 代码链核对到 `ClinicService.submit_player_contribution()` → `build_context_snapshot()` → `CooperativeRuntime.handle()` → `ContextAssembler` / `GameNPCAgent` → adapter；同时检查 SQLite completed-history 选择、进程内 pending 投影、repair 构建和执行前 Plan/权限边界。
- 复用与当前源码 SHA-256 一致的 52 回合 v3 离线产物 `runtime_evaluations/ce_quality_acceptance_20260926_tmp/ce2a_behavior0/run/`。抽查 H02、H05、H03、P01O、P01A、H04、O01、R01 的首次及存在时的修复请求；另以冻结 `ce2a_requests_v1.json`、`ce2a_requests_v2.json` 和 CE-1 pre-change provider payload 作请求身份证据。

## 检查点记录

| 检查点与预期不变量 | 实际证据 | 结论 |
|---|---|---|
| 当前事实、玩家贡献和必要 Goal/Plan 进入 A1 请求 | 代表样本均含 `AUTHORITATIVE_WORLD_case_observation`、`PLAYER_BELIEF_player_contribution`、当前 Goal/Plan/评价、权限和公开行动空间；当前输入原文各出现 1 次 | 已满足 |
| 唯一指代、歧义、撤回与改口所需历史存在 | H02 含唯一“检查木简”历史；H03 同时保留两个合理对象及“未确定先问谁”；H05 依时间顺序保留原建议和撤回改口；H04 旧意见在前、当前明确新目标在后 | 构建已满足；模型是否正确使用需真实对照 |
| pending 引用可关联公开对象与当前状态 | P01O/P01A 的 T 请求含唯一有效 pending 的 confirmation/decision、公开 action `exam_exhaustion`、authority mode、理由、revision 和精确响应标记；P01O 当前 Plan 为空 | 已满足；语义解释质量需真实对照 |
| 当前权威事实与历史陈述、玩家意见分离 | system suffix 明示历史非当前权威事实；历史 user/assistant envelope 分别标为玩家信念和历史非授权回复；当前区块用 authoritative / agent intent / player belief 分区 | 已满足 |
| 历史和 pending 不提升授权 | system 明示 pending 只读且不授予权限；P01A 为 `question`，Runtime 不把它当 approval，离线产物无新 world action；历史不能恢复授权 | 已满足 |
| 过期 pending、重启与裁剪不误导 | scope/revision 过滤测试通过；R01 重启后有 durable completed history、无旧 pending；O01 只保留最新完整后缀，省略较旧回合并给出精确数量、原因和重述提示 | 已满足；模型是否遵循重述提示需真实对照 |
| 首次及 repair 沿用同一 snapshot | format repair 以原请求消息为不可变前缀；A1-origin action repair 复用同一历史/pending snapshot，仍保持 A0 request shape | 已满足 |
| A1 2048、repair 512 与 A0-shape action repair 不变 | 冻结五类请求身份与本轮专项通过；H02/H03 首次为 2048，格式修复沿用默认 512 | 已满足 |
| 行动契约修复后最终 Plan 对齐 | Runtime 在 `_resolve_contract()` 后、authority/tool 前复核最终 action；不匹配 repaired action 的回归证明不执行工具 | 已满足 |
| 账本失败停止批次 | started/completed/error 写失败及 format/action repair 写失败专项均 fail-closed；world revision/action 不变，后续回合不开始 | 已满足 |
| 重复、冲突、顺序或无关内容未实际挤占必要信息 | 当前事实/约束/输入常驻，pending 不参与历史裁剪，历史以完整 pair 的连续后缀选择；抽样未发现相互冲突的重复陈述或当前信息被挤掉 | 已满足；未把请求长度当 token 或效果证据 |
| 必要信息与可裁剪历史优先级、遗漏提示 | pending 超限会在模型/工具前失败；历史最多 3 个完整回合、12,000 message-content 字符，O01 marker 明示缺失并要求重述 | 已满足；统一 provider token 预算仍非 CE-2A 范围 |
| C/T 差异只限预期增强 | 对 8 个代表场景逐请求比较：schema、输出上限及非 CE-2A 前缀/repair 尾部一致；差异仅为 v2 system 规则、完整历史 envelope、pending 投影和 omission metadata | 已满足 |

## 代表样本结果

| 样本 | 覆盖结果 |
|---|---|
| H02 | 唯一历史指代进入首次请求；格式修复完整复用首次快照 |
| H05 | 原建议与最新撤回/替换均按完整回合、时间正序进入 |
| H03 | 请求保留真实歧义，没有把两个合理对象伪装成唯一答案；离线 fallback 不作为语义证据 |
| P01O / P01A | pending 公开对象只在 T 增强中补足；question 不产生授权或诊断提交 |
| H04 | 当前明确改口位于历史旧意见之后；该场景正确作为当前输入负对照，不计历史依赖收益 |
| O01 | 较旧完整回合被裁剪，最新完整回合保留，omission 数量/原因/重述提示存在 |
| R01 | 重启恢复 completed history，但 process-local pending 不恢复、不复活授权 |

## 本轮实际运行

运行了 27 项定向离线 pytest，全部通过（约 7.2 秒）。覆盖：

- v3 真实案件 fixtures 的私有答案隔离、C/T 起点与 adapter 边界、repair snapshot、R01/O01、P01O/P01A；
- A0/A1 首次、格式修复、行动契约修复的同快照与冻结请求身份；
- 撤回/改口、跨 scope 隔离、多 pending、精确双 ID 标记、超长历史 omission；
- 工具成功但历史完成写失败不重放；
- repair 后最终 Plan 不匹配时拒绝执行；
- 账本 started/completed/error 及 format/action repair 写失败停止批次。

另对 8 个代表场景的实际 v3 adapter 请求做了逐请求 C/T 结构比较，全部只含预期差异。未运行全量测试；前一轮报告的 46/87/657 项没有计入本轮实测。未调用真实或付费模型，真实调用次数与费用均为 0。

## 确定性结论与剩余验证

确定性证据已解决：信息是否进入最终请求、角色/来源/权威边界、scope/revision 过滤、历史成对和裁剪顺序、pending 精确关联、repair 快照复用、请求 shape/上限、Plan 对齐、账本失败停止与无工具副作用。

仍需真实模型对照：指代实际理解率、改口后旧意见误用率、H03 是否恰当澄清、O01 是否按提示请求重述、回复质量和任务推进收益，以及真实 provider token/延迟/错误分布。这些不能由模拟输出、字符数或请求更长/更短推出。

因此可以结束本轮验收并进入后续“小批量真实评测准备”的单独阶段；在真正运行前仍须另行选择并冻结模型、核验价格与完整 payload 上界、冻结子集/授权 ID，并取得明确付费授权。本轮不开展这些工作。
