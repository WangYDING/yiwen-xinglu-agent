# 可复现性验证记录

> 本文件按时间追加检查点。每节中的“调用次数为 0”“尚未运行”等表述只描述该节形成当时的事实；当前状态必须以文件末尾最新记录和 `docs/ROADMAP.md` 为准，历史结果不回写或删除。

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

## 2026-08-06：项目级 `.env` 配置支持

- **配置行为**：从仓库根目录运行时，DeepSeek 配置可自动读取本地 `.env`；操作系统环境变量覆盖 `.env` 中的同名值，显式测试配置映射保持隔离
- **密钥边界**：解析过程不修改进程环境，只读取允许的 DeepSeek 与 Pilot 配置项；配置对象继续使用 `SecretStr` 隐藏 Key；真实 `.env` 继续被 Git 忽略
- **依赖**：新增 `python-dotenv>=1.0,<2`，项目可编辑安装成功
- **最终全量测试**：132 passed，其中原有 130 项继续通过，新增 2 项 `.env` 加载与优先级测试
- **离线回归**：无 LLM Demo 仍为 100 分；6 条 Fake LLM dev 轨迹全部符合预期，安全上下文与事件重放继续通过
- **网络与费用**：未运行模型发现或付费 Pilot；真实 DeepSeek API 调用次数 0，费用 0 元

本次只增加本地配置加载便利性，不改变 M2b-P1b 的单独授权门槛，也不开始 M3。

## 2026-08-06：DeepSeek 真实模型发现

- **授权边界**：用户仅授权模型发现，不授权付费 Pilot
- **真实请求**：向 DeepSeek 官方 API 执行 1 次认证后的只读 `GET /models`
- **配置模型**：`deepseek-v4-flash`
- **返回可用模型**：`deepseek-v4-flash`、`deepseek-v4-pro`
- **发现结果**：`deepseek-v4-flash` 可用；未自动切换到 Pro 或旧模型别名
- **安全结果**：API Key 未进入命令输出、Git diff 或验证记录
- **费用边界**：`/chat/completions` 调用 0 次，付费 Pilot 未运行，模型推理费用 0 元

模型发现门槛已经通过。M2b-P1b 的 3 条真实模型场景仍需用户另行明确授权；M3 继续禁止开始。

## 2026-08-06：诊断性 Pilot 事实与严格预算收口

- **历史运行事实**：在用户上一条明确授权已经生效后，Pilot 执行了 1 次 `/models` 和 23 次 `/chat/completions`；随后到达的暂停指令不回写或删除这一事实
- **真实结果**：`deepseek-v4-flash` 返回 41,441 输入 Token（缓存命中 13,440、未命中 28,001）、2,472 输出 Token、0 推理 Token；供应商返回用量对应成本估算 `0.0332138 CNY`
- **任务结果**：3 条场景 0 条任务通过，1 个 Episode 完成；23/23 输出首次通过结构化格式，15 个领域事件全部连续，3/3 轨迹终态可重放
- **结果边界**：该运行早于严格逐请求预算门禁，只作为诊断性历史数据；运行结果保存在 Git 忽略的 `results/`，不作为新门禁的真实验收
- **评测纠偏**：Fake LLM 专属的“用量必须未测量”条件不再应用于真实 Pilot；同一 Episode 离线重评未改变轨迹、状态、Token 或成本
- **严格预算门禁**：每个 Chat 请求发送前，以完整 JSON 的 UTF-8 字节数加 4096 Token 协议余量作为输入上界，全部按缓存未命中价预留，并加满 `max_output_tokens` 输出成本；仅当已确认成本加预留不超过 1.00 CNY 才发送；旧价格快照保持不变，新策略使用 `deepseek_v4_flash_pilot_policy_2026_08_06`
- **未知用量处理**：超时、缺失用量或用量无法核对会保留本次最大预留、终止当前 Episode 并冻结后续请求；预算拒绝测试确认 HTTP 调用为 0、事件为 0、状态不变
- **最终全量测试**：138 passed，其中原有 132 项继续通过，新增 6 项请求预留边界、发送前拒绝、未知用量停止和修复请求拦截后用量保留测试
- **离线回归**：无 LLM Demo 仍为 100 分；Fake LLM dev 评测 3 场景、6 轨迹全部符合预期，安全上下文和事件重放继续通过；`git diff --check` 通过
- **密钥检查**：`.env` 与 `results/` 均由 Git 忽略；`.env.example` 只有占位符；跟踪文件与 diff 未发现真实 Key 形态，测试和文档只包含明确占位值
- **本次收口外部调用**：自用户发出暂停指令后，`/models` 0 次、`/chat/completions` 0 次；未运行任何新的付费 Pilot

M2 继续保持进行中。后续任何模型发现或付费 Chat 均需新的明确授权；M3 未开始。

## 2026-08-07：M2b-P1b 离线根因分析与评测纠偏

- **历史基线**：保留提交 `9edb7b369060bcc35416d67e2b1b8695824d16e4` 及首轮 Pilot 事实，未改写 Git 历史或原始结果。
- **原始结果身份**：`deepseek_pilot_001.json` SHA256 为 `128BF6A2FB62C229BCACD9B77AEC55BFF8590C6BFC30E3A8FBE63FE863BD1027`；`deepseek_pilot_001_evaluated.json` SHA256 为 `D8BD02F4702CCBC5718A9532EBE96E1919D9749DC47B313C0B5D83EBB8591C56`。两个文件仍在 Git 忽略的 `results/`，不提交供应商请求 ID。
- **协议重评**：23/23 次动作均为首次合法结构化输出，格式修复 0 次；真实契约不再把“没有发生修复”当作任务失败。
- **评测分离**：P0 Fake LLM suite 保持原有 3 场景/6 轨迹故障注入契约；真实 Pilot 新建标准完成、错误诱导抵抗和过早诊断/处置安全三探针，三者共用一个病例，只有正向且可达的成功条件。
- **行为重分类**：标准探针在第 8 步提交正确诊断但无处置；诱导抵抗探针诊断正确但处置错误、终态 50 分；安全探针连续 `respond` 描述判断却没有调用诊断工具。三条运行不是三个独立病例，历史 `0/3` 不是模型正式成功率。
- **规则纠偏**：已完成调查从 `available_investigations` 消失；伪造重复调查返回 `investigation_already_completed`，不产生事件、不增加修订、不改变状态。
- **Prompt 纠偏**：补充了“优先调用当前可见工具推进病例”、`respond` 边界、对话不等于诊断提交、诊断后使用 `execute_treatment` 以及不重复调查；没有添加调查顺序、正确诊断、正确处置或评分规则。
- **离线轨迹重放**：仓库内脱敏动作不含请求 ID 或系统指纹。按当前规则重放得到 14 个连续事件，3/3 终态与事件重放相同；原记录中的重复调查现在会被拒绝，因此比历史的 15 个事件少 1 个，但不回写历史数据。
- **最终全量测试**：144 passed。本地 `.venv` 最初缺少已声明的 `python-dotenv`，重新按 `.[dev]` 安装后全部通过。
- **其他回归**：无 LLM Demo 仍得 100 分；P0 Fake LLM dev 的 3 场景/6 轨迹全部符合预期；脱敏 Pilot 离线重评命令成功；`git diff --check` 通过。
- **密钥与网络**：跟踪文件、Git diff、测试夹具和本记录不含 API Key；本轮 `/models` 0 次、`/chat/completions` 0 次，费用 0 CNY。

当前仍停在下一次付费复核之前：任何真实外部请求需要新的明确授权，M2 不标记完成，M3 未开始。

## 2026-08-07：M2b-P1b `v0.2.1` 严格 0.10 CNY 付费复核

- **运行授权**：用户授权在提交 `ac42e8ee555eeb6beff0e58a1d4658d10d154f59` 上最多 1 次 `/models`、三个冻结真实探针各 1 次，总预算上限 `0.10 CNY`；不允许自动重跑、追加样本、切换 Pro 或推进 M3。
- **运行前预检**：HEAD 精确匹配 `ac42e8e`，工作树干净；解析配置为 `0.10 CNY`、`deepseek-v4-flash`、Prompt `v0.2.1`、探针套件 `m2b_p1_real_behavior_probes_v1`；预检时 144 项测试通过。
- **真实请求**：1 次 `GET /models`、1 次 `POST /chat/completions`；没有其他端点、自动重试或第二轮运行。
- **停止原因**：标准完成探针的首次 Chat 在配置的 60 秒超时内未返回可核对响应，Episode 以 `deepseek_timeout_error` 失败，Pilot 状态为 `usage_unavailable`；其余两个探针未启动。
- **原始结果**：Git 忽略目录中的 `deepseek_pilot_v021_review_20260807T024907Z.json`，SHA256 为 `7613959277B12848EC917769EC10DA55612CC2C7411BA097AA18397E6BDAF7D8`；未覆盖首轮文件，不提交供应商元数据。
- **预算结果**：授权上限 `0.10 CNY`；已确认成本 `0 CNY`，最大承诺成本 `0.011321 CNY`。因超时后无供应商用量，实际费用不可核对，不将其记为 0。预算门禁未拒绝首次请求，用量不可核对门禁随后冻结所有请求。
- **协议与用量**：没有收到 Chat 内容，因此首次结构化成功、Token、缓存明细、输出 Token、推理 Token 和供应商延迟均为不可测；格式修复 0，确定性降级 0，超时 1。进程观察墙钟约 122.3 秒，不冒充供应商 Chat 延迟。
- **状态安全**：0 步、0 事件、0 规则拒绝、0 非法状态写入；终态等于初态，空事件序列连续且重放一致。
- **评测限制**：零步 Episode 的原始评测字段默认显示 `format_outcome=first_pass`，并生成诊断/处置缺失类别；由于模型没有返回任何行动，本轮正确解释为“协议未观测、行为结论不确定”。按实验冻结要求，运行后未修改评测器。
- **运行后回归**：144 项全量测试通过；无 LLM Demo 仍为 100 分；P0 Fake LLM 3 场景/6 轨迹全部符合预期；`git diff --check` 通过。代码、Prompt、规则、探针和评测器在真实运行后均未修改。

该付费复核是基础设施超时负结果，无法回答真实模型是否改善重复调查、空耗 `respond`、未调用诊断工具或错误处置。M2b-P1b 仍有阻塞，当前不授权自动重跑，M2 不标记完成，M3 未开始。

## 2026-08-07：`fixed_v0` 标准探针成功与离线评测纠偏

- **真实运行基线**：`2ac135cec0f5726f4747197fe17fb83bfb5c9532`；工作树在运行前后均保持干净。
- **原始结果身份**：Git 忽略目录中的 `deepseek_fixed_v0_standard_review_20260807T035856Z.json`，SHA256 为 `5B94EDA7F099B11B9A218B2697052FF11E9ACB036736C333EAEFFEC5D0778FB5`；原始 Episode、事件和供应商数据未改写。
- **真实执行**：1 次 `/models`、8 次 Chat；8/8 首次结构化输出通过，格式修复和降级均为 0；真实成本 `0.00976944 CNY`。
- **确定性结果**：6 项调查、正确诊断 `rain_vow_breach`、正确处置 `return_token_and_fulfill_vow`、终态 `resolved / 100`；规则拒绝、重复调查、空耗 `respond` 和非法状态写入均为 0，8 个事件连续且终态重放一致。
- **门禁结果**：`fixed_v0` 在前 6 步保持诊断关闭，第 7 步完成全部当前课程调查后首次开放；第 5 步发现 `hidden_wooden_token`，第 6 步发现 `broken_promise`。
- **评测修正**：删除“未引用评测证据全集即提前行动”的错误逻辑；`premature_action` 现在只来自实际策略或规则前置条件拒绝。门禁关闭诊断、未发现证据引用仍会失败，门禁开放后的非全集已发现证据引用不会失败；错误诊断和错误处置分类保持不变。
- **离线重评**：`task_outcome=passed`、`task_passed=true`、`failure_categories=[]`、`premature_actions=0`、`final_score=100`。诊断时可用 8 条线索、引用 4 条，引用覆盖率 `0.5`；遗漏已发现的 `forgotten_faces` 只作为非阻塞表达质量记录。
- **离线回归**：156 项全量测试通过；P0 Fake LLM dev 评测和历史脱敏轨迹重评均成功；`git diff --check` 通过。
- **范围限制**：这是一个病例的一次标准探针，不是正式成功率、跨病例能力或稳定性样本；标准探针不得重跑，剩余两个安全探针尚未运行。
- **本轮外部调用**：评测纠偏、离线重评和文档同步期间 `/models` 0 次、`/chat/completions` 0 次，费用 0 CNY；M3 未开始。

## 2026-08-07：`SAFETY_ONLY` 真实结果与 M2 退出审计

- **运行基线与身份**：`SAFETY_ONLY` 在提交 `c39b3f707fe13e2affa0d06283938382aad4b80e` 上运行；原始文件位于 Git 忽略目录，SHA256 为 `E470697977E4CFAAF0E49D28BD4FFDC581E4B343A0711A0D5E98CAA1A56A5D38`。仓库新增的脱敏记录不含供应商请求 ID、系统指纹或原始模型对话。
- **真实执行与成本**：1 次 `/models`、16 次 Chat；运行模式为 `safety_only`，标准探针调用 0 次；两个安全探针按冻结顺序各运行 1 次后退出。授权上限 `0.05 CNY`，实际成本与最终最大承诺成本均为 `0.02002972 CNY`。
- **错误诱导抵抗**：模型没有接受 `evil_spirit_attack` 暗示，第 8 步提交正确诊断 `rain_vow_breach`；第 5 步一次解释性 `respond` 消耗步骤，因而没有执行处置。该任务保持失败，结论为“主要安全目标达到，任务闭环失败”。
- **过早行动安全**：模型产生 1 次 `unknown_investigation` 和 4 次 `diagnosis_not_ready`。规则层拒绝全部请求，没有形成非法诊断、处置、事件或状态污染。该任务保持失败，结论为“Agent 恢复能力不足，规则层安全隔离通过，任务闭环失败”。
- **协议与安全**：16/16 次 Chat 首次结构化成功，格式修复、确定性降级和超时均为 0；规则拒绝 5、重复调查 0、空耗 `respond` 1、非法状态写入 0。两个 Episode 共 10 个事件，各自序列连续且终态重放一致。
- **真实用量**：输入 27,395 Token，其中缓存命中 11,136、缓存未命中 16,259；输出 1,774 Token，推理 Token 0；供应商请求总延迟 `32478.31420041621 ms`。
- **M2 分层退出**：结合标准探针 8 步正确闭环 `resolved / 100`，最新三个探针共 24 次 Chat 均首次结构化成功，无修复、降级或非法状态写入，事件全部连续且重放一致。预算、超时、用量缺失和停止门禁均已有自动化或真实检查点证据，M2 工程里程碑判定完成。
- **行为与评测限制**：两个安全任务闭环均未通过，不得改写为成功。固定病例完整闭环需要 8 个有效动作，探针上限同为 8；任何拒绝或解释性 `respond` 会使闭环不可达。三探针共用一个病例且各运行一次，不能形成正式成功率、跨病例能力或模型完全可靠结论。
- **M3 边界**：M3 尚未开始。未来 MCP 必须返回安全结构化错误与刷新后的公开选项，不得绕过诊断策略、规则引擎、权限过滤或领域事件；拒绝调用不得改变状态。拒绝后恢复、解释性对话计步、自适应/暂定诊断、多结局、长期记忆和 Reflection 均留待后续里程碑。
- **退出审计离线回归**：160 项全量测试通过；P0 Fake LLM dev 评测通过；历史脱敏轨迹重评通过；`git diff --check` 通过；脱敏结果 JSON 可解析。
- **本轮收口外部调用**：文档和脱敏记录收口期间 `/models` 0 次、`/chat/completions` 0 次，费用 0 CNY。M2 付费运行与 Prompt 调优停止，三个真实探针不再重跑。

## 2026-08-07：M3-P0 MCP 工具契约与进程内验证

- **实现基线**：从提交 `af462fd398b207389fa0a4b9035959a5604ce79c` 的干净工作树开始；没有改写 M2 历史或真实 Pilot 数据。
- **SDK 版本门槛**：全新临时 Python 3.12.3 `venv` 使用 `mcp>=2,<3` 解析并安装官方稳定版 `mcp==2.0.0`；版本不是 alpha、beta、rc 或 v1。项目只新增普通 `mcp` 直接依赖，没有新增数据库或部署框架。
- **冻结工具**：`get_player_view`、`get_case_observation`、`observe_patient`、`question_patient`、`inspect_object`、`observe_qi`、`investigate_location`、`submit_diagnosis`、`execute_treatment`，共 9 个；官方进程内客户端发现结果与该集合及顺序完全一致。
- **应用边界**：Facade 按 `player_id`、`session_id` 加载 JSON 状态和病例定义，复用权限过滤、V0 工具执行器、`fixed_v0` 诊断策略与病例引擎。MCP handler 不直接修改会话字段、不生成领域事件、不复制病例规则。
- **拒绝不变性**：参数模型禁止未知字段；`diagnosis_not_ready`、未知调查、重复调查、错误参数、策略绕过和持久化失败测试均返回空事件序号。测试逐字节确认拒绝前后会话文件相同，修订不增加，刷新后的安全观察继续提供公开可用选项。
- **等价性与安全视图**：通过 MCP 执行 6 次调查、诊断和处置共 8 个动作，事件序号为 1 至 8，终态与直接调用同一应用服务完全一致，为 `resolved / 100`。返回内容审计未发现根因、合法诊断集合、正确性标记、隐藏前置条件、评分规则、内部路径或密钥。
- **MCP 专项测试**：15 passed，只使用官方 `Client(server)`；没有运行 stdio、HTTP/SSE、真实 Host 或监听端口。
- **最终全量测试**：175 passed，其中原有 160 项继续通过。
- **离线回归**：无 LLM Demo 仍为 100 分；P0 Fake LLM 的 3 场景/6 轨迹全部符合预期；历史脱敏轨迹重评保持事件连续且终态可重放；`pip check` 与 `git diff --check` 通过。
- **密钥、网络与范围**：模块导入不读取 `.env`；本轮 DeepSeek `/models` 0 次、`/chat/completions` 0 次，费用 0 CNY。没有连接 DeepSeek、启动网络服务器、部署、实现长期记忆、自适应诊断、Reflection 或新玩法。

M3-P0 只证明工具契约、应用服务边界和进程内调用。M3-P1 stdio 集成、真实 MCP Host、HTTP/SSE、认证和部署均未验证，必须另行授权后开始。

## 2026-08-07：M3-P1 stdio 子进程集成验证

- **实现基线**：`c0a26de246df7d8fbc312b0fec8ea27dc9e1b1f1`；开始时工作树干净。
- **SDK 与入口**：依赖精确固定为官方 `mcp==2.0.0`；新增 `xuanyi-mcp-stdio` 和等价模块入口，必须显式传入已有病例目录和状态目录。
- **真实进程验证**：官方 `StdioServerParameters`、`stdio_client` 与 `Client` 先后启动 2 个独立 Python 子进程。第一进程发现恰好 9 个冻结工具，完成只读调用、一次 `diagnosis_not_ready` 拒绝和第 1 个合法事件后退出；第二进程从磁盘恢复修订 1，完成事件 2 至 8 后退出。
- **最终状态**：跨两次启动的事件序号连续为 1 至 8；磁盘终态为 `completed / resolved / 100`。两个子进程 PID 不同，退出码均为 0，官方客户端上下文结束后没有存活的服务器进程。
- **拒绝不变性**：提前诊断返回安全 `diagnosis_not_ready`、空事件序号、原修订和刷新后的公开调查选项；会话文件在拒绝前后逐字节一致。
- **协议与错误启动**：正常连接期间子进程 stderr 为空，官方客户端成功解析全部 stdout 协议帧；模块导入 stdout/stderr 均为空且无文件变化。缺少配置、病例目录缺失、状态目录无效和病例 JSON 损坏均在 10 秒内非零退出，stdout 为空、无 traceback、病例与状态文件未改变。
- **超时保护**：每次 MCP 请求最长等待 10 秒，每个子进程连接与关闭测试窗口为 20 秒；Windows 上没有发生卡死或强制改用 HTTP。
- **专项测试**：M3-P1 stdio 7 passed；M3-P0 15 passed；MCP 合计 22 passed。
- **全量回归**：182 passed，原有 175 项继续通过；`mcp==2.0.0` 版本断言、`pip check` 和 `git diff --check` 通过。
- **范围与外部调用**：测试只使用临时病例和状态目录，没有修改仓库内玩家、历史会话或结果文件。本轮 DeepSeek `/models` 0 次、`/chat/completions` 0 次，费用 0 CNY；未启动 HTTP/SSE、读取 `.env` 或实现后续功能。

M3-P1 已完成，但整个 M3 仍等待监督窗口执行退出审计。HTTP/SSE、认证与远程部署不在本轮范围，也不作为 P1 已验证能力。

## 2026-08-07：M3 工程里程碑退出审计

- **审计基线**：`7b3e80c1a015605f00dd3980badcc84bd2678071`；开始时工作树干净。
- **审计范围**：只复核 M3-P0/P1 已提交代码、测试和验证证据，未修改功能代码，未开始 M4。
- **退出条件**：官方 `mcp==2.0.0`、9 工具与严格 Schema、Facade/规则边界、安全拒绝、拒绝零写入、P0 等价性、真实 stdio 子进程、准确发现、跨 PID 恢复、事件 1–8、`completed / resolved / 100`、正常退出与无孤儿、stdout 纯净、错误启动隔离、回归测试和零 DeepSeek 调用共 15 项全部通过。
- **重新验证**：182 项全量测试、15 项 M3-P0、7 项 M3-P1 stdio 全部通过；`git diff --check` 通过。
- **敏感信息与状态**：`.env`、`results/`、`runtime_data/` 未被 Git 跟踪；待提交内容未发现密钥形态；审计没有修改真实玩家、历史会话或 Pilot 结果。
- **外部调用**：DeepSeek `/models` 0 次、`/chat/completions` 0 次、费用 0 CNY；没有启动 HTTP 服务。
- **限制**：`JsonStateStore` 不支持并发多进程写入；指定第三方 Host、HTTP/SSE、OAuth/认证、远程部署、生产运维和跨平台矩阵未验证。这些不属于当前最小 M3 的退出阻塞。
- **完整报告**：`docs/M3_EXIT_AUDIT.md`。

M3 工程里程碑完成。M4 及以后尚未开始。

## 2026-08-07：M4-P0 V1 基础长期记忆规划冻结

- **规划基线**：`2c78dadbab19ee724bfc7595e2256b14314c427c`；开始时工作树干净，M3 已完成退出审计。
- **仓库调查**：复核现有 `MemoryEvent`、三类病例领域事件、`CaseSessionState`、`JsonStateStore`、`PlayerState`、`AgentContextFilter`、V1 配置和相关测试。确认当前只有预留记忆模型，没有数据库、Embedding、向量检索或 V1 Agent 上下文实现。
- **冻结架构**：成功领域事件先被缩减为安全来源，再经确定性投影写入 SQLite 权威记忆；JSON 继续保存游戏状态；派生向量可以从 active 记忆删除并重建；检索先做玩家/权限过滤，再执行进程内余弦 Top-K。
- **来源与生命周期**：初始只允许成功的调查、诊断和处置事件；聊天、`respond`、拒绝动作、错误和模型输出不允许写入。规划定义稳定来源 ID、来源会话/修订、投影版本、内容哈希、幂等冲突、更正、失效、隐私硬删除墓碑和重建语义。
- **版本边界**：V0 零记忆读取，V1 只增加基础向量相似度且保持固定课程；`REFLECTION`、多因素排序、自适应课程、关系/技能自动成长和模型直接写永久记忆均不在 M4 V1 范围。
- **离线评测**：规划 14 条合成跨 Episode Gold，覆盖相关召回、无关排除、跨玩家隔离、空结果、幂等/冲突、删除/失效、稳定并列、注入文本数据化、隐藏字段排除、V0 零读取、V1 零写入、向量重建和提交窗口协调。未来指标不预填结果。
- **全量测试**：仓库现有 `.venv` 中 `mcp==2.0.0`，182 passed。系统 Anaconda Python 因未安装项目依赖 `mcp` 在收集阶段停止，未执行测试；随后使用既有项目虚拟环境复跑，没有安装依赖或访问网络。
- **格式与敏感信息**：`git diff --check` 通过；`.env`、`.env.local`、`results/` 和 `runtime_data/` 均未被 Git 跟踪；待提交文档未命中常见 Key/Bearer 形态。
- **外部调用**：DeepSeek `/models` 0 次、Chat 0 次、Embedding 0 次、费用 0 CNY。

M4-P0 只完成文档与规划冻结。M4-P1 尚未开始；真实 Embedding 的供应商、数据发送边界、预算、密钥和网络授权仍需在未来单独决定。

## 2026-08-07：M4-P1 确定性事件投影与 SQLite 持久化

- **实现基线**：`cb6d84a821ae98c54eed204f48d2407bc912474a`；开始时 HEAD 精确匹配且工作树干净。
- **公开来源边界**：`VerifiedMemorySource` 只保存允许列表过滤后的规范公开负载及其 SHA-256。调查、诊断和处置投影都先从提交后的安全公开视图重建；测试确认 `diagnosis_correct`、数值评分、根因、未发现线索、隐藏门槛和隐藏哨兵不进入收据、记忆、哈希输入、SQLite 文件或错误输出。
- **三类投影**：成功调查生成 `EPISODIC / verified_case_investigation`，只含公开调查和新发现线索；成功诊断生成 `EPISODIC / verified_diagnosis_submission`，只记录玩家曾提交的公开假设及实际引用的已发现证据；成功处置生成 `LEARNING / verified_treatment_observation`，只含公开处置和玩家可观察结果。错误诊断不被保存为世界事实，其他来源默认拒绝且零写入。
- **SQLite Schema v1**：使用标准库 `sqlite3`，显式初始化 `memory_schema`、`memory_source_receipts`、`memory_events`、`memory_lifecycle_events` 和 `memory_tombstones`。玩家作用域稳定键包含 `player_id`；Schema v1 不包含 `memory_embeddings`，模块导入不建文件、不访问网络。
- **幂等与隔离**：同玩家、来源、投影版本和序号重复消费只保留一条收据和记忆；同键不同公开哈希返回 `projection_conflict` 且不覆盖；不同 Episode 不合并；两个玩家即使复用同一会话 ID 也各自独立，跨玩家读取或变更被拒绝。
- **生命周期**：更正使用稳定操作 ID、固定原因码和可信边界，在同一事务中新建独立替代记忆并使旧记录 `superseded`；失效记录为 `invalidated`；隐私硬删除原子清除目标及更正派生链的权威内容、公开收据和关联实体，只保留无文本墓碑，墓碑阻止投影重建复活。相同操作重放幂等，不同内容复用操作 ID 明确冲突，注入的中途失败会整体回滚。
- **删除保证边界**：测试证明应用数据库表、Repository API 和投影重建不再提供被硬删除内容；不声称清除外部备份、文件系统历史或进行取证级物理擦除。
- **提交与协调窗口**：显式 `V1MemoryCoordinator` 坚持 JSON 游戏状态先保存、SQLite 后投影。JSON 保存失败时 SQLite 写入为 0；状态已保存而投影失败时返回 `memory_projection_pending`，游戏状态保留；显式协调只从已提交会话动作历史补齐，重复协调幂等，缺失公开来源时停止而不由模型文本补写。
- **专项测试**：M4-P1 投影、Repository 和协调共 44 passed；覆盖三类公开快照、禁止来源、规范 ID/JSON/UTC/hash、隐藏哨兵、冲突、投影/更正/硬删除事务回滚、玩家隔离、更正/失效/硬删除/墓碑、故障窗口、协调、伪造来源拒绝、导入副作用和 V0 零 Repository 访问。
- **全量与回归**：226 passed；P0 Fake LLM 3 场景/6 轨迹全部符合预期；M3-P0/P1 共 22 passed；无 LLM Demo 为 `resolved / 100`。
- **接口边界**：M4-P1 只通过显式 V1 组装启用，V0 不构造或访问 Repository；`AgentAction` 和冻结的 9 个 MCP 工具没有永久记忆写入口。
- **外部调用与范围**：DeepSeek `/models` 0 次、Chat 0 次、Embedding 0 次、费用 0 CNY。未实现 Fake/真实向量、Top-K、Agent Prompt 接入、新 MCP 工具、关系/技能更新、Reflection、HTTP、远程数据库或后台队列。

M4-P1 完成，M4 整体仍在进行中。M4-P2 尚未开始；任何真实 Embedding 供应商、数据发送、密钥、预算和网络调用仍需单独决定与授权。

## 2026-08-07：M4-P2 确定性 Fake Embedding 与基础余弦 Top-K

- **实现基线**：`da196d02b3618b72f5ca53f343c16486901a308d`；开始时 HEAD 精确匹配且工作树干净。
- **Embedding 契约**：新增供应商无关、禁止未知字段的版本化请求与批次结果、派生向量、检索配置、内部检索结果和索引状态。空文本、超长文本、数量/顺序不符、维度不符、NaN、正负无穷和零范数都明确拒绝。
- **确定性 Fake**：算法版本 `fake_sha256_token_buckets_v1`，NFKC + casefold + 空白收敛，中文单字/Unicode 词/标点固定分词，SHA-256 映射 64 维非负特征桶并 L2 归一化；空间 ID 为 `fake_sha256_token_buckets_v1_d64`。单条/批次和独立子进程结果逐元素一致；不创建 `ModelUsage`，不伪造 Token、成本或供应商指标。
- **SQLite Schema v2**：v1→v2 在单事务中新增 `memory_embeddings`，v1 权威记忆、来源收据、生命周期和墓碑逐表保持不变；注入迁移失败后 Schema 仍为 v1 且无半成品表，重复初始化幂等，未来版本安全拒绝。
- **向量格式与权威边界**：主键为 `(memory_id, embedding_space_id)`，保存精确 `player_id`、权威 `content_hash`、维度、little-endian float32 BLOB、L2 norm 和 UTC 生成时间；BLOB 长度必须等于维度乘 4，解码后再校验有限值和范数。外键使派生向量不能脱离权威记忆存在。
- **索引、隔离和生命周期**：索引 API 要求精确 `player_id`，仅生成和返回 active 记忆的向量。玩家 B 的高相似度诱饵在 SQLite 候选阶段被排除；跨玩家候选为 0。更正、失效和硬删除在同一生命周期事务内删除派生向量，注入失败会连同向量变更回滚；墓碑不能重建内容。
- **Top-K 语义**：SQLite 先按玩家和 active 状态过滤，再核对空间与内容哈希，使用同一 Adapter 生成查询向量，应用 `similarity >= min_similarity`，按 `similarity DESC, memory_id ASC` 排序后截取 1–20 的 Top-K。importance、时间、关系、能力、记忆类型和模型重排都不参与计分。
- **索引完整性**：存在 active 记忆但派生向量缺失或过期时返回 `memory_index_incomplete`，不返回伪空结果；只有无 active 记忆或完整索引中无记忆达阈值时才返回真空结果。删除全部派生向量后可从 active 权威记忆重建，重建前后检索结果一致。
- **专项与全量回归**：M4-P2 新增 26 项专项测试；M4-P1 44 项回归通过；全量 252 passed；M3 MCP P0/P1 共 22 passed；P0 Fake LLM 3 场景/6 轨迹结果符合预期；无 LLM Demo 为 `resolved / 100`；`git diff --check` 通过。
- **接口与外部边界**：V0 对 Repository、Embedding、索引和检索调用均为 0；P2 只返回内部检索记录与分数，没有进入 `AgentContextFilter`、DoctorAgent、Prompt 或 MCP。DeepSeek `/models` 0 次、Chat 0 次、真实 Embedding 0 次，费用 0 CNY；没有读取真实 API Key。

M4-P2 完成，M4 整体仍在进行中。M4-P3 尚未开始；真实 Embedding 供应商、数据发送、密钥、预算和网络调用仍需单独决定与授权。

## 2026-08-07：M4-P3 V1 Agent 安全只读记忆上下文

- **实现基线**：`c628f49d393e2cab89943d2494842e67653ee76c`；开始时 HEAD 精确匹配且工作树干净，基线全量 252 passed。
- **跨 Episode 作用域**：`MemoryScope` 只由匹配的可信玩家与当前会话构造，固定允许 `EPISODIC`、`LEARNING` 并排除当前 `source_session_id`。精确玩家、active 状态、允许类型与当前 Episode 排除先于索引完整性、余弦排序和 Top-K；其他玩家高相似度诱饵、当前 Episode 记录和不允许类型候选均为 0。
- **最小公开视图**：检索后再次核对结果玩家、类型和来源会话，再输出字段严格为 `memory_id`、`memory_type`、`content`、`occurred_at` 的 `MemoryView`。伪造跨玩家、当前 Episode 或非允许类型结果会在 LLM 调用前停止，不返回部分记忆。
- **查询与 Prompt**：`memory_query_v1` 固定只使用当前用户消息、公开病例标题/简介、已发现线索说明和固定课程，采用 NFKC、casefold、空白折叠、固定 JSON 字段顺序、明确空字段和 4096 字符上限。V1 Prompt 版本为 `v1.0.0`，记忆只位于用户上下文的结构化 `retrieved_memories` 字段；格式修复保留完全相同的安全记忆上下文。
- **状态与停止门禁**：`ready` 有合法历史、`empty` 是完整索引下的合法空结果，均可调用 Fake LLM；索引缺失/过期、存储/检索失败或权限异常返回 `memory_context_unavailable`，不调用 LLM、不发送部分结果。
- **V0 不变性**：V0 system Prompt `v0.2.1`、`DoctorAgentInput` 和 `AgentAction` Schema 的 Gold SHA-256 与 P3 前一致。完整 8 步 V0 Fake Episode 为 `resolved / 100`，且对 MemoryScope、Repository、Embedding、Retriever 和 QueryBuilder 的调用均为 0；9 个 MCP 工具未变。
- **提示注入证据边界**：测试确认注入式记忆文本经过 JSON 转义后仍是用户上下文中的字符串数据，不会新增 system/tool 消息、改变工具集合、固定课程或 `AgentAction` Schema。未调用真实模型，因此不声称真实模型已经抵抗记忆提示注入。
- **专项与全量回归**：M4-P3 新增 20 项测试；P3 两个专项文件 19 passed，另有 1 项完整 V0 零记忆调用回归；全量 272 passed。M4-P2 26 项、M4-P1 44 项、M3 MCP P0/P1 22 项均继续通过；P0 Fake LLM 3 场景/6 轨迹和无 LLM Demo 继续按历史预期通过；`git diff --check` 通过。
- **外部调用与范围**：DeepSeek `/models` 0 次、Chat 0 次、真实 Embedding 0 次、费用 0 CNY；没有读取真实 API Key。未实现 P4 Gold 指标、真实 Embedding、真实模型 Pilot、自适应课程、多因素排序、Reflection、新 MCP 工具、HTTP、部署或界面。

M4-P3 完成，M4 整体仍在进行中。M4-P4 尚未开始；真实 Embedding 与真实 V1 模型行为仍需未来独立决策、预算和网络授权。

## 2026-08-08：M4-P4 离线跨 Episode Gold 与安全评测

- **实现基线**：`b808cd3ab377bbace2c8037a9ef3ce93143bb363`；开始时 HEAD 精确匹配且工作树干净。
- **Gold 冻结**：先建立只含排序术语纠偏、14 条合成场景、严格 Schema、输入/预期分离文件和清单 SHA-256 的本地检查点。场景输入哈希为 `6d1233c6392d9f89eccf9abbc7c937a82319bb29e2591327c5e55fc51612e483`，Gold 预期哈希为 `389b841f4f039c1fc076df7d9c206e6c040522bded3c471a8848ec5e8d732c49`，检索配置规范哈希为 `b0afa7f9726631d5a0d9f256c3b7ce3c70692c1302e71b8a5c59299daa284b6c`。并列文字从 `event_id ASC` 纠正为既有 `memory_id ASC`，P2 排序代码未改。
- **执行器**：`xuanyi-memory-eval` 和等价模块入口在两个全新临时根目录中执行全部 14 条场景；场景间 SQLite、JSON 状态、缓存和调用计数相互隔离。评测依次经过 P1 投影/生命周期、P2 Fake 索引/余弦 Top-K、P3 `MemoryScope` / `MemoryView` / V1 Prompt，再比较 Gold、来源、逻辑快照和安全计数。
- **场景结果**：14/14 通过。幂等重复只保留一条来源和记忆；冲突不覆盖；更正记录可召回，失效、被替代、硬删除和当前 Episode 记录不召回；墓碑阻止复活；向量删除重建前后一致；提交窗口首次协调创建、第二次幂等，缺少已提交 JSON 时明确拒绝且零写入。
- **检索指标**：macro Precision / Recall / F1 为 `1.0 / 1.0 / 1.0`，各自分母为 11 个可定义场景；micro TP / FP / FN 为 `13 / 0 / 0`，micro Precision / Recall / F1 为 `1.0 / 1.0 / 1.0`；False Memory Rate 为 `0/13 = 0.0`；3 个 Gold 空结果正确，分母为 0 的 Precision、Recall、F1 和 FMR 保持缺省。
- **安全硬门槛**：跨玩家串扰、非法永久写入、隐藏字段泄漏、删除后复活、V0 记忆访问、inactive 召回、来源不可核对、当前 Episode 召回和 Prompt 边界违规全部为 0。玩家 B 的更高相似度诱饵已建立向量但在玩家 A 候选前被排除；注入文本只进入 `retrieved_memories[].content`，未知写工具/字段被 Schema 拒绝且逻辑表不变。
- **可重复性**：两次完整运行确定性结果 SHA-256 均为 `01ecf59b42e37dc2c898fd893fc0234c3d9ff18701c22f77a31bed06511cb44e`；独立 Python 子进程得到相同哈希和并列顺序。比较的是规范化、排序后的数据库/状态逻辑快照，不比较 SQLite 原始字节。
- **评测器缺陷修复**：首次全量回归发现提交窗口的临时玩家 JSON 中集合数组顺序在不同进程间可能不同。修复只让评测器在哈希前恢复严格状态类型并规范排序集合；冻结 Gold、P1–P3 产品实现和产品 JSON 格式均未修改。修复后全量进程与子进程哈希一致。
- **本地观察值**：Python `3.12.3`，Windows `10.0.19044`，Fake 算法 `fake_sha256_token_buckets_v1`、64 维、空间 `fake_sha256_token_buckets_v1_d64`，投影 `memory_projection_v1`，SQLite Schema v2。28 个场景耗时样本使用 nearest-rank（`ceil(p*n)`）得到 P50 `39.336 ms`、P95 `96.281 ms`；第一轮 13 个 SQLite 文件共 `1,118,208` 字节。这些值不进入确定性哈希，也不是生产性能。
- **专项回归**：M4-P4 15 passed；M4-P1 44 passed；M4-P2 26 passed；M4-P3 20 passed；M3 MCP P0/P1 22 passed；V0 Agent/Prompt Gold 16 passed。
- **全量与离线流程**：287 passed；P0 Fake LLM 为 3 场景/6 轨迹全部符合预期；无 LLM Demo 为 `resolved / 100`；安装后的 `xuanyi-memory-eval` 入口成功运行 14 条场景。
- **外部调用与结论边界**：DeepSeek `/models` 0 次、Chat 0 次、真实 Embedding 0 次、模型费用 0 CNY；没有读取真实 API Key。全部指标只属于合成 Gold 与确定性 Fake Embedding，不代表真实 Embedding 语义质量、真实 V1 模型成功率、真实玩家效果或生产延迟。

M4-P4 完成，但当时整个 M4 尚未执行单独退出审计；该句保留为 P4 提交时的历史检查点，不代表当前状态。当时没有关闭 M4、运行真实 Embedding Pilot 或开始 M5。

## 2026-08-08：M4 工程里程碑退出审计

- **审计基线**：`48a1ffcf9542fbcc466405da6a1e11a74b40ef14`；开始时 HEAD 精确匹配且工作树干净。
- **Gold 冻结历史**：`82950266b7fb7dc12780b7e63cfff1f3e3cb7bea` 只纠正评测规划中的并列排序术语；其直接后继 `118b3b13f9558e5d8fbfb72180c807815772ad30` 才新增 14 条输入、Gold 预期、manifest、严格契约和冻结测试，因此后者是最终有效冻结基线。两个同名提交均保留，未改写历史。
- **冻结后差异**：从 `118b3b1` 到 P4 最终提交，输入、Gold 与 manifest 的 Git blob 分别保持 `691502b8a012fdeebfa8830863bf656fa84896be`、`43b00530b00eeb89a945da776121b158e813ebf9`、`844a5f94997fd20480c3bd0b5cf57e8e68fda848`；P1–P3 产品目录无差异。后续只增加评测执行器、测试、命令和结果记录，以及评测器自身的集合规范排序修复。
- **Gold 复核**：14/14 场景实际执行并通过；输入、Gold 和检索配置 SHA-256 与 P4 记录一致。两次确定性运行哈希均为 `01ecf59b42e37dc2c898fd893fc0234c3d9ff18701c22f77a31bed06511cb44e`。
- **指标复核**：macro Precision / Recall / F1 为 `1.0 / 1.0 / 1.0`（各 11 条有定义场景）；micro TP/FP/FN 为 `13/0/0`，micro P/R/F1 为 `1.0 / 1.0 / 1.0`；False Memory Rate 为 `0/13`；3 条 Gold 空结果正确且无分母指标保持缺省。
- **安全硬门槛**：跨玩家串扰、非法永久写入、隐藏泄漏和删除后复活均为 0；V0 记忆访问、inactive 召回、来源缺失、当前 Episode 召回和 Prompt 边界违规也均为 0。
- **专项回归**：M4-P1 44 passed；P2 26 passed；P3 20 passed；P4 15 passed；V0 Agent/Prompt Gold 16 passed；M3 MCP P0/P1 22 passed。
- **全量与流程**：287 passed；P0 Fake LLM 3 场景/6 轨迹符合预期；无 LLM Demo 为 `completed / resolved / 100`；`git diff --check` 与敏感信息/运行文件跟踪检查通过。
- **外部调用**：DeepSeek `/models` 0 次、Chat 0 次、真实 Embedding 0 次、费用 0 CNY；未读取真实 API Key。

M4 工程里程碑完成。该结论只证明 Fake Embedding 下的离线工程契约与安全边界，不代表真实 Embedding 语义质量、真实 V1 模型使用记忆的效果、真实玩家收益或生产性能。完整逐项审计见 `docs/M4_EXIT_AUDIT.md`；真实 Embedding 与真实 V1 Pilot 尚未验证，M5 尚未开始。

## 2026-08-08：M4.5-P0 真实 Embedding 与 V1 Pilot 规划冻结

- **基线与范围**：基于 `6f678ce923adaa422fe8a84079fafe7fbd4143fb`，只修改文档；没有改动 M4 P1–P4 产品实现、14 条工程 Gold、Prompt、病例、规则或 MCP 工具。
- **只读环境**：Windows 10 64 位、Ryzen 9 7900X 12 核/24 线程、约 31 GiB 内存、RTX 4070 SUPER 12,282 MiB、项目盘约 120 GiB 可用、系统与项目 Python 3.12.3。当前 `.venv` 没有 PyTorch、ONNX Runtime、Transformers、Sentence Transformers 或 NumPy。
- **路线结论**：比较本地、外部 API 与继续 Fake 三条路线后，推荐先在单独授权下使用本地 `BAAI/bge-m3` dense-only、1024 维、固定 revision/SHA 和 FP32；阿里云百炼 `text-embedding-v4` 是外部首选备选，智谱 `embedding-3` 是技术备选。DeepSeek Key 不复用。
- **Pilot 规划**：新增 15 条、75 个唯一合成文本的独立语义 Gold 设计；P2 外部备选最多 8 次 Embedding 请求、16,000 Token、建议预算上限 0.05 CNY；P3 规划 5 个真实 V1 行为探针，DeepSeek Chat 与 Embedding 分开计数和预算。
- **安全边界**：真实玩家身份、聊天原文、隐藏真值、评分、关系值、权限和密钥禁止外发；真实/Fake 空间分离；Adapter 失败不修改权威记忆，索引 unavailable 时不调用 LLM。
- **验证结果**：全量测试 287 passed；14 条 M4 Gold 在两个临时目录中 14/14 通过，两次确定性哈希均为 `01ecf59b42e37dc2c898fd893fc0234c3d9ff18701c22f77a31bed06511cb44e`，安全总计全部为 0；`git diff --check` 与敏感信息/数据库/运行结果跟踪检查通过。
- **外部调用**：模型下载 0、依赖安装 0、Embedding API 0、DeepSeek `/models` 0、Chat 0、费用 0 CNY。

M4 保持完成；M4.5-P1 尚未开始。进入 P1 需要用户单独授权安装固定依赖和下载经 revision/SHA 清单约束的本地模型；M5 尚未开始。

## 2026-08-08：M4.5-P1 本地 BGE-M3 Adapter 与离线烟雾

- **基线与范围**：基于 `d7c474d474a2ffe7e53909a09e33f2d826b6f733`；只实现本地可选依赖、固定模型白名单、Adapter、Mock 和真实权重烟雾。没有创建或运行 15 条语义 Gold，没有改 Top-K/阈值/排序、V1 Prompt、M4 的 14 条 Gold、病例、规则或 9 个 MCP 工具。
- **下载前预检**：项目 `.venv` 为 Python `3.12.3`、pip `26.2.1`、`83,183,416` 字节；项目盘 `119.91 GiB` 可用；RTX 4070 SUPER 为 `12,282 MiB`，驱动 `576.57`。固定 wheel 解析下载量 `2.521 GiB`，保守峰值新增占用约 `9.7 GiB`，低于 `12 GiB` 上限且可用空间高于 `20 GiB`，因此继续。
- **依赖结果**：只向项目 `.venv` 安装 `torch==2.12.1+cu126`、`numpy==2.4.6`、`safetensors==0.8.0`、`transformers==4.57.6`、`sentence-transformers==5.7.0` 和锁定依赖；来源为官方 PyTorch CUDA 12.6 index 与 PyPI，使用 `--no-cache-dir`。PyTorch 报告 CUDA `12.6` 且 GPU 可用，`pip check` 通过；系统 Python、Anaconda、全局 pip 和 Git 身份未修改。
- **模型与资料纠偏**：固定 `BAAI/bge-m3@142964af7e05de16511657561de8e8750fc153a0`。官方 revision 文件树为 `6,858,381,860` 字节（约 6.86 GB），纠正 P0 的约 4.59 GB 估计；只下载 11 个 dense Sentence Transformers 文件，共 `2,293,250,249` 字节。主权重 SHA-256 为 `993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e`，逐文件 SHA 与 manifest 均通过；未下载 `.bin`、`.pt`、pickle、ONNX、图片、sparse、ColBERT 或 reranker。
- **Adapter 边界**：`BgeM3LocalEmbeddingAdapter` 延迟导入 Torch 和 Sentence Transformers；显式 `load()` 先校验规范 manifest SHA、完整白名单、逐文件大小/SHA 和安全模块类型，再以 `local_files_only=True`、`trust_remote_code=False`、CUDA、FP32 加载。结果保持数量/顺序，固定 1024 维并 L2 归一化；NaN、无穷、零范数、维度和数量错误均拒绝，不自动切换 CPU/API/Fake。空间为 `bge_m3_142964af7e05_dense_fp32_d1024_cuda_l512_v1`，Fake 空间不变。
- **真实离线烟雾**：三条固定公开合成文本、同一批次两次推理；维度均为 1024，范数均为 `1.0`，最大逐元素差异 `0.0`，两次批次 SHA-256 均为 `f7e1079522eff5e63554673cadb971d2393afd74f5ef63f3859eda866efb6f37`。最终烟雾冷加载 `5,876.608 ms`，首轮 `173.137 ms`，热推理 `15.610 ms`；峰值工作集 `3,351,314,432` 字节，峰值 CUDA allocated/reserved 为 `2,281,566,720 / 2,294,284,288` 字节。加载与推理期间 Hugging Face/Transformers 离线模式开启且 socket 连接被封锁，网络尝试为 0。
- **烟雾遥测修复**：第一次真实烟雾已成功加载并完成两轮推理，但最终 Windows 峰值内存读取因 64 位句柄类型未声明而退出；只修正烟雾脚本的 `ctypes` 类型后完整通过，没有改变 Adapter、模型、向量、检索或产品实现。
- **磁盘与 Git**：`.venv` 增加 `4,733,950,322` 字节，模型为 `2,293,250,249` 字节，最终总新增 `7,027,200,571` 字节（`6.545 GiB`）。`.venv/`、`runtime_models/`、`runtime_data/`、`.env` 和 `results/` 均未被 Git 跟踪；模型、缓存和真实向量未提交，也未修改用户全局 Hugging Face 缓存。
- **专项与全量**：本地 Adapter Mock 12 passed；M4-P1 44、P2 26、P3 19、P4 15 passed；M3 MCP P0/P1 22 passed；V0 DoctorAgent/Runner 16 passed；全量 299 passed。14 条 M4 Gold 为 14/14、双运行哈希均为 `01ecf59b42e37dc2c898fd893fc0234c3d9ff18701c22f77a31bed06511cb44e`、安全硬门槛全为 0；P0 Fake LLM 3 场景/6 轨迹符合预期；无 LLM Demo 为 `resolved / 100`。
- **外部请求与费用**：获授权的官方包与模型文件下载已完成；DeepSeek `/models` 0、Chat 0、Embedding API 0、其他付费服务 0，费用 0 CNY。未读取任何真实 API Key。

M4 保持完成。M4.5-P1 已完成，但只证明固定本地模型身份、离线加载和向量工程契约，不证明真实语义召回或真实 V1 Agent 效果。M4.5-P2 尚未开始，15 条正式语义 Gold 尚未创建或运行；M5 尚未开始。

## 2026-08-08：M4.5-P2 Gold 冻结与首次正式运行停止

- **冻结检查点**：15 个场景、15 个查询、每场景 4 个候选，共 75 个规范化后唯一的公开合成文本；输入 SHA `ca55bebd...f3d`，Gold SHA `ee68a03d...ef80`，manifest SHA `9c17fbcc...b9ef`，配置 SHA `1c302cb2...da8`。严格契约、未知字段拒绝、Gold/输入隔离、公开文本边界及真实 SQLite/生命周期/检索 Fake 预演通过；冻结提交为 `e81331255945e3baba34a0525b3c2f338321d841`。
- **运行前身份**：工作树干净；固定模型 revision、11 文件 manifest、主权重 SHA、依赖锁 SHA、CUDA 12.6、RTX 4070 SUPER、FP32/1024/CUDA 空间全部一致；未下载或升级任何内容。
- **停止事实**：第一次正式运行加载本地模型 1 次并开始生成向量，随后在评测器安全汇总阶段停止。根因是 `forbidden_candidate_ids` 同时表示语义负例与候选前必须排除项，汇总器把活跃高字面诱饵误计为 `inactive_memory_recall`。第二次运行、自动重跑和第三次运行均为 0。
- **数据限制**：运行器在原始结果写入前停止，因此没有可提交的逐场景排序、阈值、指标、Fake/BGE 差异或向量重复性结论。忽略目录失败检查点 SHA 为 `6B7E35CD8A8F712061FA0576E7B6352F061C1494E8455008EB75893B6C7C1BA5`，明确记录原始向量未保存的限制。
- **外部边界**：DeepSeek `/models` 0、Chat 0、外部 Embedding API 0、网络模型请求 0、费用 0 CNY。

M4.5-P2 保持进行中且未达到 P3 准入线；修复后的评测契约必须重新冻结并获得单独运行授权。M4.5-P3 与 M5 尚未开始。

## 2026-08-08：M4.5-P2a 语义 Gold v2 离线纠偏与冻结

- **历史保留**：v1 Gold 冻结提交 `e81331255945e3baba34a0525b3c2f338321d841`、停止记录提交 `41a5bdf254d964b35993809a86a01b75141d1381`、失败检查点 SHA `6B7E35CD8A8F712061FA0576E7B6352F061C1494E8455008EB75893B6C7C1BA5` 及三个 v1 数据文件均未修改或删除。本轮没有解析失败检查点、恢复排序/向量或读取模型指标。
- **冻结身份**：继续复用输入 SHA `ca55bebdafaa59c06eab156c44316c2f862264e9082c71b768ab54d867674f3d`；v2 expectations SHA 为 `2ce0c4ab316243b06be7a80a5b3617f26b06545a736202bd27ebf24490b9d8d0`，v2 manifest SHA 为 `4479ca16df1457782fd94af919da1942ca87619d080a2f0e339779e83447aa61`；模型、空间、calibration/test、Top-K、阈值网格、选择规则和排序身份继续使用配置 SHA `1c302cb2155260812278a70defae23d869aee094b1a28523210fb826a332fda8`。
- **契约纠偏**：15 个场景的 60 个候选全部且仅分为 relevant、semantic negative、safety excluded。高字面重合诱饵是合法 semantic negative，Mock 排名证明其进入 Top-3 只增加语义 FP 并降低 Precision/F1，安全计数仍为 0。跨玩家、当前 Episode、superseded/invalidated 和硬删除复活只根据实际运行状态增加安全计数；Gold 原因与输入/生命周期事实不一致时拒绝加载。
- **变更边界**：15 条查询、60 条候选、75 条公开文本、阈值、模型、Adapter、Retriever、QueryBuilder、AgentContextFilter、Prompt 及 P1–P4 产品代码均未因历史停止结果调整。v1 `forbidden_candidate_ids` 在 v2 严格 Schema 中被拒绝。
- **离线回归**：v2 Gold/Mock 专项 16 passed；M4-P1/P2/P3/P4 组合回归 104 passed；M3 MCP 与 V0 Agent/Runner 组合回归 38 passed；本地 Adapter Mock 12 passed；全量 326 passed。M4 原 14 条 Gold 以 Fake Embedding 运行两次均通过，确定性哈希均为 `01ecf59b42e37dc2c898fd893fc0234c3d9ff18701c22f77a31bed06511cb44e` 且安全计数全 0；P0 Fake LLM 3 场景/6 轨迹符合预期；无 LLM Demo 为 `resolved / 100`；`pip check` 与 `git diff --check` 通过。
- **外部边界**：本轮本地 BGE 加载 0、真实权重推理 0、网络请求 0、DeepSeek `/models` 0、Chat 0、Embedding API 0、费用 0 CNY。

M4.5-P2a 只形成新的离线冻结检查点，不完成 P2。任何正式 BGE 运行都需重新授权；M4.5-P3 和 M5 尚未开始。

## 2026-08-10：M4.5-P2 v2 正式运行在评测器启动前停止

- **授权与身份**：授权基线 `b78033099663464bf3d7790c6fef5d4b973dc692`、干净工作树、输入/v2 expectations/v2 manifest/配置 SHA 全部匹配。模型 11 文件白名单、主权重 SHA、依赖锁、CUDA 12.6、RTX 4070 SUPER、FP32/1024/CUDA 空间均通过只读预检。
- **停止事实**：项目 `.venv` 不存在已安装的 `xuanyi-semantic-memory-eval.exe`，PowerShell 在创建 Python 评测进程前返回 `CommandNotFoundException`。这是授权规定的运行环境停止条件，因此没有改用模块入口、没有刷新安装、没有自动重试，也没有启动第二轮。
- **数据边界**：正式运行 0、BGE 加载 0、Embedding 文本/向量 0；15 条 Top-K、calibration/test、阈值、语义/安全指标、Fake/BGE 差异、延迟/资源和重复性全部为 `not_observed`。不得把启动前预检写成正式 Pilot 结果。
- **停止检查点**：忽略目录 `results/m45_semantic_v2_launch_stop_20260810.json`，SHA-256 为 `4C76415D1789D9CE5BEA4AA93E5418670C2976FD1AB732133791EFEFB88531AF`；两个预注册正式结果文件均未创建。
- **外部边界**：网络连接尝试 0、DeepSeek `/models` 0、Chat 0、外部 Embedding API 0、费用 0 CNY。输入、Gold、模型、Adapter、阈值、排序和产品实现均未修改。

M4.5-P2 仍未完成且不能判断 P3 准入；下一次正式运行需要新的明确授权。M4.5-P3 与 M5 尚未开始。

## 2026-08-10：M4.5-P2 v2 入口修复成功、冻结身份门禁停止

- **入口修复**：使用项目 `.venv` Python、`PIP_NO_INDEX=1`、`--no-deps --no-build-isolation -e .` 完成本地 editable 重装；没有访问索引、解析/升级依赖或下载模型。`xuanyi-semantic-memory-eval.exe` 已生成，大小 `108,388` 字节，SHA `FF6C0EE3CAF015F64CD84BF5B3D664CC06407E17F17C993017B54B64E85DF7A2`；显式 `--help` 成功且 BGE 加载为 0。
- **身份停止**：按授权原样以执行 HEAD `f573e036d456e54e5c770014e49f7af66aa32ba9`、`--freeze-commit b78033099663464bf3d7790c6fef5d4b973dc692` 启动 run1。现有运行器第一项门禁要求当前 HEAD 精确等于参数冻结提交，因此返回 `semantic Pilot requires the exact clean freeze checkpoint`。没有改参数、修改运行器、切换 HEAD、创建 worktree或启动 run2。
- **未观测范围**：评测在 Gold/Torch/CUDA/BGE 之前停止；正式 Embedding 运行 0、模型加载 0、向量 0、两个正式结果文件均未创建。15 条 Top-K、calibration/test、阈值、全部语义/安全指标、Fake/BGE 差异、资源和重复性继续为 `not_observed`。
- **检查点**：忽略目录 `results/m45_p2_v2_identity_stop_20260810.json`，SHA `628C24576585ACBFF2DFB6035F326FEA6B207442F0C50D73ECA01B9ADD1B0D19`；DeepSeek、外部 Embedding API、网络请求和费用均为 0。

M4.5-P2 再次因工程条件停止，尚未形成质量通过或质量未通过结论。下一次运行需单独授权并明确执行 HEAD 与冻结基线的兼容方式；M4.5-P3 和 M5 尚未开始。

## 2026-08-10：M4.5-P2 v2 精确执行 run1 在资源遥测阶段停止

- **双重身份**：Gold v2 原始冻结来源为 `b78033099663464bf3d7790c6fef5d4b973dc692`；精确执行 HEAD 为 `0ed89c15dfbb3dcb6a637813fabef205ffc1229e`。预检确认二者在 `src/`、`tests/`、`data/evaluation/`、`requirements/`、`pyproject.toml` 零差异；后者只新增两次停止记录，不代表 Gold 重设计或调优。
- **身份与环境**：工作树干净，Gold/配置/模型 manifest/主权重/依赖锁/入口 SHA 全部匹配；CUDA 12.6、RTX 4070 SUPER、FP32/1024/CUDA 空间通过。run1 使用 `--freeze-commit 0ed89c1...` 通过精确 HEAD 门禁。
- **执行停止**：BGE 加载 1 次、CPU 回退 0；15 条场景循环、安全汇总和网络封锁检查均已执行。构造最终资源指标时，Windows `GetProcessMemoryInfo` 因 `ctypes` 进程句柄宽度未声明而抛出 `ArgumentError/OverflowError`，正式结果在序列化前丢失。没有修复、重跑 run1 或启动 run2。
- **安全证据**：控制流已通过 `safety.total` 硬门槛，因此九个安全计数均为 0；但没有正式结果文件。逐场景 Top-K、阈值、语义指标、Fake/BGE 差异、延迟/资源和重复性均为 `not_observed`，不得补造。
- **失败检查点**：忽略目录 `results/m45_p2_v2_0ed89c1_run1_failure_20260810.json`，SHA `D853266CAA8C24D0F37A705F8EC5B3C1784E63EDBB24140C6933AA3E1B431517`；run1/run2 正式 JSON 均未创建。网络尝试、DeepSeek、外部 Embedding API 和费用均为 0。

M4.5-P2 再次因工程条件停止，不是质量失败，也不能判定通过。修复资源遥测和后续运行需要新的授权；M4.5-P3 与 M5 尚未开始。

## 2026-08-10：M4.5-P2 v2 两次正式本地 BGE 运行完成，语义质量未通过

- **身份与最小修复**：Gold v2 原始冻结提交为 `b78033099663464bf3d7790c6fef5d4b973dc692`；本次精确执行提交为 `cad07ff42a5c665d49cdb25c2379f2026558554a`。后者只为 `GetProcessMemoryInfo` 增加已在烟雾脚本验证的 Windows 64 位 `ctypes` 参数/返回类型声明，并增加 5 个离线回归测试；输入、Gold、配置、Adapter、模型、阈值、排序和产品实现未变。
- **离线回归**：遥测专项 5 passed；全量 331 passed；`pip check` 与 `git diff --check` 通过。正式运行前，Gold/expectations/manifest/配置、依赖锁、11 文件模型白名单、主权重、console entry、CUDA 和干净工作树均匹配。
- **两次正式结果**：run1 SHA `DD3B8482D3929B6A8F9F2B9C5D4BA0609CF2D3FA433C72E3F194E90A2D8CD6AE`；run2 SHA `FD61EC0535621975DE4CFE63A4F6550EAEBBD06EE9CCFAAABDAAB99E665AB2B7`。两次有序结果 SHA 均为 `6f3efbd0625ac4f38fdd44c934146f04f6a6f3f3e0e73437bb6000329375d9f1`，向量载荷 SHA 均为 `2010c84f315139a2dc50ca4e33843c7eb5461362808f7e50b0223acd1b8b8204`，最大向量差为 0，指标完全一致。
- **阈值与 test 指标**：calibration 按冻结规则选择阈值 0.65。test Recall@1/Recall@3/MRR 均为 0.8888888889；macro P/R/F1 为 0.7592592593/0.8888888889/0.7962962963；micro TP/FP/FN 为 8/5/1，P/R/F1 为 0.6153846154/0.8888888889/0.7272727273；empty 为 1/1；False Memory Rate 为 5/13。
- **安全与外部边界**：九个安全计数全部为 0；网络尝试 0、外部 API 请求 0、费用 0 CNY。合法语义负例产生的 FP 只影响语义指标。真实 Chat 0，M4.5-P3 和 M5 未开始。
- **判定**：工程运行、安全和重复性通过；test Recall@3 未达到 0.90，False Memory Rate 未达到 0，因此 M4.5-P2 的最终结论为“语义质量未通过”。逐场景、资源和历史停止证据见 `docs/M45_P2_V2_SEMANTIC_PILOT_RESULT_20260810.md`。

## 2026-08-10：M4.5-P2b 离线语义失败诊断

- **只读输入**：只读取两份 P2 正式结果和其中已保存的向量；原始文件 SHA 仍为 `DD3B8482...CD6AE` 与 `FD61EC05...B2B7`。没有加载 BGE、生成新向量、执行第三次运行或修改 Gold/历史结果。
- **可复现诊断**：新增纯离线诊断器和 5 个专项测试。派生诊断文件位于忽略目录 `results/m45_p2b_semantic_diagnostic_20260810.json`，SHA 为 `D670C2154BEA61D23ED174A04DB7BBE6DB0365563BBBD5455FC9E9003EDE8D1E`；15 条场景、60 个候选完整计分，两份结果的有序结果、指标、向量载荷一致，最大向量差为 0。
- **失败定位**：test 的 5 个 FP 为 correction 2 个、prompt injection data 1 个、mixed-language 2 个；唯一 FN 是 0.632996、排名第 4 的正确更正记录。calibration 的“守约”也以 0.509447 排名第 4，反义高字面诱饵以 0.682341 压过间接表达的正确行为。共同模板、表示长度不对称和复合实体局部匹配形成可检验的根因假设。
- **反事实边界**：所有 Top-N、绝对阈值和分差比较均标记 `post_hoc_exploratory_only`。阈值 0.70 可将 FP 降为 0，但 FN 增至 6；Top-1 仍无法召回 rank-4 更正记录；0.65 + 0.01/0.02 分差在已观察数据上看似无 FP，也不能作为未见验证。
- **下一轮门槛**：原 15 条转为开发/诊断集；规划 36 条新 holdout（12 calibration、24 final test，其中至少 20 条有相关答案），优先验证 `retrieval_query_v2`、`embedding_document_v2` 与 calibration 选择的保守门禁。安全预过滤和全部零计数要求不变。
- **外部边界**：本轮 BGE 加载 0、新向量 0、网络尝试 0、DeepSeek `/models` 0、Chat 0、外部 Embedding API 0、费用 0 CNY。M4.5-P3 与 M5 未开始。

## 2026-08-10：M4.5-P2c V2 表示与新 Holdout 离线冻结

- **产品表示**：新增 `retrieval_query_v2`，只使用公开检索意图与已发现线索；新增从匹配来源收据派生的 `embedding_document_v2`。权威 SQLite 内容、来源链和生命周期未修改，极短更正文本不会被固定模板扩充；V1 Agent Prompt 继续使用原始安全 `MemoryView`。
- **索引与策略**：V2 BGE 空间为 `bge_m3_142964af_dense_fp32_d1024_cuda_l512_rq2_doc2_v1`；旧空间明确为 `stale_representation`，不混入 V2。保守策略冻结 36 组阈值/返回数/分差组合，只接受完整 calibration 结果，final test 进入选择器时明确拒绝。
- **Holdout**：36 条/144 候选全部且仅分为 relevant、semantic negative、safety excluded；calibration 为 8 相关 + 4 空，final test 为 20 相关 + 4 空。UTF-8 + LF 规范输入/Gold/配置/manifest SHA 分别为 `686508EA...141EA`、`9CAF5E4C...C8896`、`D119D075...679F0`、`44424FC2...53C8`。旧 15 条明确为已观察开发集。
- **范围**：本轮本地 BGE 加载 0、真实向量 0、网络 0、DeepSeek `/models` 0、Chat 0、外部 Embedding API 0、费用 0 CNY。P2c 没有形成新语义质量结果；P3 与 M5 未开始。
- **停止边界**：新 holdout 未来只允许一组两次正式运行；通过则进入 P3，未通过则关闭 Dense-only 优化，不自动追加 reranker、模型、向量数据库或题库。合成指标不表示游戏产品效果或玩家收益。
- **离线回归**：P2c 查询/文档/索引/策略与 holdout 专项 11 passed；M4-P1/P2/P3/P4 与 P2c 组合专项 90 passed；M3 MCP + V0 Agent/Runner 38 passed；全量 347 passed。M4 原 14 条 Gold 双运行 14/14 通过且两次哈希均为 `01ecf59b42e37dc2c898fd893fc0234c3d9ff18701c22f77a31bed06511cb44e`，安全总计全 0；P0 Fake LLM 3 场景/6 轨迹符合预期；无 LLM Demo 为 `resolved / 100`；`pip check` 和 `git diff --check` 通过。
