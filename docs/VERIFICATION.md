# 可复现性验证记录

## 2026-08-03：M2 前独立环境预检

- **验证基线提交**：`0a69e36`（M1.5 Agent 安全门槛）
- **主机系统**：Windows
- **临时环境**：全新 `venv`，未继承全局 site-packages；验证结束后删除
- **Python**：3.12.3
- **安装方式**：`python -m pip install -e ".[dev]"`
- **实际安装 Pydantic**：2.13.4
- **实际安装 pytest**：8.4.2
- **测试结果**：69 passed
- **已安装命令验证**：`xuanyi-case-demo` 成功完成无 LLM 正确路线
- **Demo 最终结果**：病例解决，线索 40 + 诊断 30 + 处置 30 = 100

此结果证明 M1/M1.5 基线可以从项目声明在空白 Python 环境中安装和运行，不依赖开发环境中预装的 Pydantic 2.8 或 pytest 7.4。

完成 V0/V1/V2 配置调整与两份人工 Gold 快照后，使用另一全新临时 `venv` 再次执行相同流程：Pydantic 2.13.4、pytest 8.4.2 下 **72 passed**，已安装 Demo 仍得到 100 分。第二个临时环境也在验证后删除。

后续依赖、Python 最低版本或安装配置发生变化时，需要新增记录，不能覆盖本次结果。

## 2026-08-04：M1 退出审计与 M2-V0 验证

修改前先在全新临时 `venv` 中重做 M1 退出审计：

- **Python**：3.12.3
- **安装方式**：`python -m pip install -e ".[dev]"`
- **M1/M1.5 测试结果**：72 passed
- **无 LLM Demo**：正确路线完成并得到 100 分
- **额外状态验证**：将人工 Gold 的 `completed / revision=3 / score=0` 终态写入 `JsonStateStore` 后读取，模型完全相等

完成 M2-V0 工作树后，在另一个全新临时 `venv` 中重新安装并验证：

- **Python**：3.12.3
- **Pydantic**：2.13.4
- **pytest**：8.4.2
- **全部测试结果**：84 passed
- **Fake LLM V0 Episode**：8 步建议均经规则层执行，产生 8 个连续领域事件，最终得分 100；从初始状态重放事件可得到相同终态
- **失败路径**：已覆盖一次格式修复、二次失败确定性降级、供应商异常降级、工具参数未知字段、动作类型不匹配、未发现证据、统一脱敏拒绝反馈和最大步数
- **已安装无 LLM Demo**：仍成功完成并得到 100 分

两个临时环境均在验证后删除。此次验证没有调用真实 LLM，也没有产生真实供应商的成功率、延迟、Token 或成本指标。

## 2026-08-04：M2a 收口与公开诊断接口纠偏

本轮修改前先按当前工作树复核，而不是沿用截图中的旧测试数：

- **修改前实际全量**：84 passed
- **修改前无 LLM Demo**：100 分
- **修改前 Fake LLM 完整 Episode**：通过

接口纠偏后，在全新临时 `venv` 中重新安装最终工作树：

- **Python**：3.12.3
- **Pydantic**：2.13.4
- **pytest**：8.4.2
- **最终全量测试**：88 passed
- **无 LLM Demo**：仍为 100 分
- **Fake LLM 完整 Episode**：8 步、8 个连续领域事件，测试验证从初始状态重放得到相同终态
- **公开诊断接口**：Agent 可见 3 个中立候选；已知错误候选可提交且诊断得分为 0；未知候选返回 `unknown_diagnosis`，不产生事件或状态变化
- **安全上下文**：Prompt 测试确认不包含内部根因 ID、`valid_diagnosis_ids`、正确性、处置结果、评分规则或隐藏前置条件
- **公开行动语义**：调查和处置具有独立公开说明；内部结果说明未进入 Agent 视图
- **格式检查**：`git diff --check` 通过
- **实验 v0.1 SHA256**：`681CC9B9236CA3095A3D1BD01A6C48D2DE7CD52936B22F849B8C5CF93802BA08`，原文件作为历史版本保留

验证结束后删除临时环境。本记录只证明 M2a Fake LLM Harness 和安全闭环；真实 LLM 适配、3 条 dev 场景、小型 Pilot、真实超时、Token 与延迟仍属于未完成的 M2b。

## 2026-08-04：M2a 检查点与 M2b-P0 确定性 dev 预检

- **M2a 本地检查点**：`ab7e960387c5387606cbf4f9395d4a579d2fbba9`（`feat: complete safe M2a agent harness`）
- **最终全量测试**：97 passed，其中原有 88 项继续通过，新增 9 项 dev Schema、评测与轨迹测试
- **无 LLM Demo**：8 个确定性动作完成病例，评分仍为 100
- **Fake LLM 完整 Episode**：8 步、8 个连续领域事件、终态重放一致
- **dev 单命令入口**：`xuanyi-dev-eval` / `python -m xuanyi_npc.evaluation.dev_runner`
- **dev_case_correct_001**：参考轨迹完成，8 步、8 事件、100 分、重放一致；词表外错误轨迹有 2 个规则拒绝步骤，停在 6 事件/修订 6，拒绝步骤没有产生事件
- **dev_case_wrong_hypothesis_001**：公开错误候选被规则层接受，Episode 完成且 8 事件可重放；诊断分为 0、总分 70，评测器分类为 `wrong_hypothesis` 与 `score_mismatch`
- **dev_recovery_001**：参考轨迹首次格式失败后在同一步完成一次修复，8 步完成并得到 100 分；失败对照在 8 步上限终止、8 次安全降级、0 事件、终态等于初态
- **安全上下文**：6 条轨迹的所有 Agent 请求均未发现配置中的内部根因、合法诊断集合、正确性、评分或隐藏门槛字段
- **事件一致性**：6 条轨迹均通过连续性检查，且从初始状态重放事件得到相同终态
- **运行指标**：Fake LLM 输出固定为 `measurement_status = not_measured`，未填写真实延迟、Token、成本或成功率

本轮没有接入真实供应商、SDK 或 API，也没有实现 MCP、长期记忆、自适应教学、Reflection、界面或多 Agent。M2b-P1 仍未开始，整个 M2 保持进行中。

## 2026-08-04：M2b-P1a DeepSeek Adapter 离线预检

- **验证基线提交**：`b296373b5b3079c7775b5644c5a4538a337c5926`（M2b-P0）
- **供应商与模型配置**：DeepSeek 官方 API、`https://api.deepseek.com`、仅 `deepseek-v4-flash`；Pro 和旧模型别名不在允许配置中
- **价格快照**：2026-08-04 DeepSeek 官方人民币价目；Flash 缓存命中输入 0.02 元/百万 Token、缓存未命中输入 1.00 元/百万 Token、输出 2.00 元/百万 Token
- **最终全量测试**：130 passed，其中原有 97 项继续通过，新增 33 项用量、Adapter、HTTP 错误和 Pilot 门禁测试
- **离线 HTTP 验证**：全部供应商响应使用 `httpx.MockTransport`；覆盖 `/models`、Chat JSON、缓存 Token、推理 Token、请求 ID、系统指纹、空内容、截断、401/403、429、超时、5xx、非法 JSON 和缺字段
- **请求约束**：测试确认 `stream=false`、JSON Output、`thinking=disabled`、`temperature=0`、默认 `max_tokens=512`，且应用层工具反馈不转换为供应商原生工具调用
- **用量与成本**：`ModelUsage` 不再假设美元；估算成本和币种成对出现，缓存缺失时按未命中保守估算，已知部分成本在用量不完整时仍保留
- **Pilot 门禁**：只允许冻结的 3 条 P0 场景各 1 次、每 Episode 8 步、每步一次格式修复；默认预算 1.00 CNY，达到预算返回 `budget_exhausted` 并保留已完成检查点
- **回归验证**：无 LLM Demo 仍为 100 分；Fake LLM 完整 Episode 与 3 条离线 dev 场景继续通过，事件可重放
- **格式检查**：`git diff --check` 通过
- **密钥与网络**：未读取或打印真实 `DEEPSEEK_API_KEY`；未执行模型发现命令或 Pilot 命令；真实 DeepSeek API 调用次数 0，费用 0 元

本记录只证明协议实现和离线门禁。真实 Key 权限、Flash 可用性、模型行为、延迟、Token 和成本仍未验证，属于需要用户再次明确授权的 M2b-P1b。
