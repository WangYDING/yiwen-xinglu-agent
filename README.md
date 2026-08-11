# 玄医师承型智能 NPC

这是一个道家志怪背景的师承型智能 NPC 工程。项目目标是让道医 NPC 能够记忆玩家行为、判断能力与师徒关系、自适应安排教学和考核，并在确定性条件满足后开放传承。

项目中的病例、医术、异常现象和处置方式均为架空设定，不提供现实诊断、处方或剂量。

## 当前状态

**M2、M3、M4 与 M5 工程里程碑已经完成；M4.5 已以 `closed_with_known_dense_retrieval_limitations` 终止。** M5 现在提供包含三个病例、确定性跨案连续性、两项可见知识成长、结构化 Agent 工具、安全恢复、持久化重放和普通用户 CLI 的本地游戏 AI 纵向切片。P4b 的灰灶未闭环、月井未运行真实负结果继续保留；P4d 的 5/5 行动契约修复及三案闭环只是一例真实工程案例，不是正式成功率。三个病例始终可独立开始；推荐顺序只提供公开建议，不构成锁关。语义向量记忆继续默认关闭且不进入正式 Agent Prompt。M6-P0 已完成本地离线发布准备审计；当前没有远程仓库，公开身份、许可证和可分发包仍待决定或验证，尚未开始 M6-P1，也没有发布任何内容。

已经包含：

- 七个核心领域对象及其输入校验；
- 三个可独立完成的正式病例：“旧纸伞与失约书生”“灰灶客栈与无火炊烟”“月井回声与错投木简”；
- 玩家状态与病例会话状态的 JSON 保存和读取接口；
- 可列举、严格校验且原子保存的本地玩家与病例 Episode 快照；
- 调查、诊断、处置与基础评分引擎；
- 明确的技能、线索、证据和会话状态错误；
- 不调用大模型的完整病例回放；
- 从领域事件重建病例会话的状态重放器；
- V0、V1、V2 共用的 `EpisodeResult`；
- 权限过滤后的 `PlayerView` 与 `CaseObservation`；
- 不允许关键状态或永久记忆写入的安全 `AgentAction`；
- 明确且经过配置校验的 V0、V1、V2 能力边界；
- 可替换的 `LLMAdapter` 与只读输入的 `DoctorAgent`；
- 只使用最近有限轮对话和固定教学顺序的 V0 Prompt；
- `AgentAction` 格式错误时的一次修复重试与确定性降级；
- 将工具建议转换为领域命令、再交给病例引擎校验的应用层；
- 使用脚本化 Fake LLM 跑通并记录完整 Episode；
- 3 条严格 Schema 的 dev 场景，以及每条场景的参考轨迹和明确错误轨迹；
- 以统一 `EpisodeResult` 为输入的确定性评测器和单命令运行入口；
- 与 P0 Fake 故障注入分离的 3 条真实模型正向行为探针，以及首轮脱敏动作轨迹的离线重评入口；
- DeepSeek V4 Flash 的直接 HTTP Adapter、只读模型发现和明确供应商错误；
- 日期化人民币价格快照、供应商无关用量记录和请求发送前的 1 元 Pilot 严格预算门禁；
- 只使用伪 HTTP 响应的 DeepSeek Adapter 与 Pilot 离线测试；
- 面向 Agent 的公开诊断候选、调查说明和处置说明；
- 未知诊断候选由规则层拒绝，错误候选可正常提交并按确定性规则计分；
- 已完成调查从可用视图消失，伪造重复调查被明确拒绝且不产生事件；
- 基于官方 MCP Python SDK v2 的 9 个严格工具契约和可注入 Server factory；
- 复用现有存储、权限过滤、工具执行器、`fixed_v0` 策略和病例引擎的应用 Facade；
- 使用官方 `Client(server)` 完成纯进程内发现、调用、拒绝不落盘和参考轨迹等价性验证；
- 使用官方 stdio 客户端启动独立 Python 子进程，完成工具发现、完整轨迹、磁盘恢复、重启和正常关闭验证；
- V1 长期记忆的单向事件投影、SQLite 权威存储、幂等/删除/重建、派生向量、玩家隔离和 Gold 评测规划；
- V1 的严格公开来源契约、确定性调查/诊断/处置记忆投影和 SQLite Schema v1 权威存储；
- 更正、失效、应用级隐私硬删除、非内容墓碑、事务回滚和状态先提交后的显式协调恢复；
- 供应商无关 Embedding 契约、跨进程可重复的 64 维 SHA-256 特征桶 Fake Embedding；
- 固定 revision、严格 safetensors 白名单、延迟加载且离线限定的 BGE-M3 CUDA/FP32 本地 Adapter；
- SQLite Schema v1→v2 原子迁移、little-endian float32 派生向量、按玩家索引/清理/重建；
- 只使用余弦相似度的 Top-K，并显式区分“无达阈值记忆”与“索引缺失或过期”；
- `retrieval_query_v2`、`embedding_document_v2`、独立 BGE 表示空间、`stale_representation` 索引状态和 calibration-only 保守召回策略；
- 36 条未见语义 holdout、144 个完整分区候选、冻结参数网格、指标分母及 Agent/安全岗位双重证据边界；
- 由可信玩家/会话构造的 `MemoryScope`，在排序前排除当前 Episode、非允许类型和其他玩家记忆；
- 只含不透明 ID、类型、公开内容和发生时间的 `MemoryView`，以及检索后的二次权限校验；
- 独立的 V1 Agent 输入与 Prompt：记忆只作为用户上下文中的结构化 JSON 历史数据，固定课程和 `AgentAction` 不变；
- `ready`、`empty`、`unavailable` 三种记忆上下文状态；索引或安全错误会在 LLM 调用前以 `memory_context_unavailable` 停止；
- 14 条输入/Gold 分离的合成跨 Episode 记忆场景、严格 Schema、文件/配置哈希、确定性双运行器和结构化失败分类；
- 逐场景及汇总 Precision、Recall、F1、False Memory Rate、安全硬门槛、规范数据库逻辑快照和本地观察指标；
- 全新 Python 3.12 虚拟环境中的安装、测试和 Demo 复现记录；
- 领域模型、规则边界和持久化测试。
- 可注入 `CaseCatalog`、`MultiCaseEpisodeService` 与普通用户交互式 `xuanyi-play` 入口；
- 两个独立 CLI 子进程之间恢复同一未完成 Episode，以及完整旧纸伞 `resolved / 100` 回放验证。
- 两个新病例各有 6 个调查、8 条线索、3 个公开诊断和 resolved/suppressed/worsened 三类处置，并各以两种合法调查顺序验证 `resolved / 100` 与事件重放。
- 独立的 `CampaignState`、连续 `CampaignEvent`、公开完成摘要、`CampaignFact`、知识解锁和事件重放；
- 由严格 `cross_episode_rules_v1` 决定的“契物归属核验”与“交接顺序核验”，以及灰灶、月井的公开历史反应和调查建议；
- 病例先保存、Campaign 后投影的显式故障窗口；`campaign_projection_pending` 可由幂等协调补齐，拒绝和退出不写 Campaign。
- 正交的 `GameplayMode`（manual/Fake/DeepSeek V0）与 `SemanticShadowMode`（off/record-only），默认 manual/off；
- 三病例 Fake 演示仍经安全 Agent 输入、严格 `AgentAction`、应用服务、规则引擎、原子保存和 Campaign 协调完成；
- record-only shadow 使用离线 Mock 写脱敏旁路记录，明确不注入 Prompt、不影响行动和状态；DeepSeek V0 保持原 Prompt、模型发现、错误分类与预算门禁。
- 结构有效的 Agent 提案还会在状态服务之前通过当前公开行动契约；首次上下文错误使用一次独立记录的 `action_contract_repair`，第二次仍错误则安全降级且不产生第三次模型调用。
- `xuanyi-m5-acceptance` 离线验收入口：用独立子进程逐行动恢复三病例，验证 Campaign、双玩家隔离、拒绝零写入、事件重放和 semantic shadow 隔离，并输出脱敏 JSON 与摘要。
- 可直接录屏的 3 分钟与 8～10 分钟演示指南，以及分别面向 Agent 应用岗和游戏 AI 产品岗的证据清单。

**当前已完成 M5，并完成 M6-P0 发布准备审计**：P4b 的[历史负结果](docs/M5_P4B_DEEPSEEK_CAMPAIGN_PILOT_20260811.md)保持不变；P4c 的[离线行动契约审计](docs/M5_P4C_AGENT_CONTRACT_AUDIT.md)没有回写该结果；P4d 的[最终单次恢复验证](docs/M5_P4D_DEEPSEEK_RECOVERY_VALIDATION_20260811.md)以 21 次 Chat、`0.02345744 CNY` 完成灰灶和月井，并验证 5/5 行动契约修复。P5 只做离线验收，没有重跑付费实验。完整退出证据见 [`docs/M5_EXIT_AUDIT.md`](docs/M5_EXIT_AUDIT.md)，演示流程见 [`docs/M5_DEMO_GUIDE.md`](docs/M5_DEMO_GUIDE.md)，双岗位证据见 [`docs/M5_PORTFOLIO_EVIDENCE.md`](docs/M5_PORTFOLIO_EVIDENCE.md)。发布阻塞、身份/版权边界和后续计划见 [`docs/M6_RELEASE_READINESS_AUDIT.md`](docs/M6_RELEASE_READINESS_AUDIT.md) 与 [`docs/M6_PORTFOLIO_RELEASE_PLAN.md`](docs/M6_PORTFOLIO_RELEASE_PLAN.md)。

最终 M2 退出依据包括：标准探针在 8 步内完成正确诊断和处置，终态 `resolved / 100`；`SAFETY_ONLY` 的错误诱导探针抵抗了 `evil_spirit_attack` 暗示并提交正确诊断，但因一次解释性 `respond` 未能处置；过早行动探针的 1 次未知调查和 4 次过早诊断均被规则拒绝，没有状态污染。最新三探针共 24 次 Chat，24/24 首次结构化成功，格式修复、降级和非法状态写入均为 0，事件均连续且可重放。三探针共用一个病例且各运行一次，不是正式成功率样本。

M2 分层结论和数据身份见 [`docs/M2_EXIT_AUDIT.md`](docs/M2_EXIT_AUDIT.md)，M3 证据和限制见 [`docs/M3_EXIT_AUDIT.md`](docs/M3_EXIT_AUDIT.md)，M4 退出结论见 [`docs/M4_EXIT_AUDIT.md`](docs/M4_EXIT_AUDIT.md)。M4 架构与 P1–P4 实现边界见 [`docs/M4_MEMORY_PLAN.md`](docs/M4_MEMORY_PLAN.md)，Gold 契约、指标和实测结果见 [`docs/M4_MEMORY_EVALUATION_PLAN.md`](docs/M4_MEMORY_EVALUATION_PLAN.md)。M4.5 的完整负结果见 [`docs/M45_P2D_HOLDOUT_PILOT_REPORT_20260810.md`](docs/M45_P2D_HOLDOUT_PILOT_REPORT_20260810.md)，最终终止状态见 [`docs/M45_TERMINATION_AUDIT.md`](docs/M45_TERMINATION_AUDIT.md)。M5 的产品流程见 [`docs/M5_MULTI_CASE_VERTICAL_SLICE_PLAN.md`](docs/M5_MULTI_CASE_VERTICAL_SLICE_PLAN.md)，病例审计见 [`docs/M5_CASE_DESIGN.md`](docs/M5_CASE_DESIGN.md)，P3 的 Campaign 契约与故障边界见 [`docs/M5_CAMPAIGN_CONTINUITY.md`](docs/M5_CAMPAIGN_CONTINUITY.md)。项目仍不包含 HTTP/SSE、认证、远程部署或已获准的真实 V1 记忆 Prompt。

## 设计边界

- 大模型未来只负责语言、教学策略和结构化行动建议。
- 病例真相、状态数值、权限、技能解锁和最终状态修改由确定性规则负责。
- Agent 输出必须通过 Pydantic 校验，再由规则层决定是否执行。
- V0 Agent 只接收权限过滤后的只读视图、最近对话和固定课程。
- 所有病例状态变化都通过领域命令和事件记录，以支持追踪和回放。
- M3 MCP 只包装现有应用服务，返回结构化安全错误和刷新后的公开选项；不得绕过诊断策略、规则引擎或事件写入，被拒绝调用不得改变状态。
- V1 永久记忆只能由成功领域事件经过版本化确定性投影生成；先按玩家和权限隔离，再执行基础向量 Top-K，结果只读且不得改变固定课程。
- M5 正式连续性只使用确定性事件投影的公开游戏事实；语义向量记忆默认关闭，shadow 结果不能进入 Prompt 或改变行动和状态。

## 目录

```text
src/xuanyi_npc/domain/   核心领域对象
src/xuanyi_npc/agents/   LLM 协议、DoctorAgent 与 Fake LLM
src/xuanyi_npc/application/ Agent 权限视图、Campaign 协调、V1 记忆与检索
src/xuanyi_npc/config/   V0、V1、V2 能力配置
src/xuanyi_npc/engine/   确定性病例引擎
src/xuanyi_npc/evaluation/ 统一 Episode 结果与确定性 dev 评测器
src/xuanyi_npc/mcp_server/ 官方 MCP v2 的进程内工具契约与 Server factory
src/xuanyi_npc/memory/   M4 公开来源、投影、生命周期与 Embedding 契约
src/xuanyi_npc/storage/  JSON 状态与 SQLite 权威记忆存储
data/cases/              结构化病例定义
data/campaign/           确定性跨案顺序、知识和公开反应规则
data/evaluation/         P0 dev、真实行为探针、脱敏轨迹与 M4 合成记忆 Gold
data/pilot/              带日期和来源的 Pilot 价格与安全策略快照
docs/                    架构决策记录
tests/                   自动化测试
```

当前执行状态以 `docs/ROADMAP.md` 为唯一路线来源；架构约束见 `docs/DECISIONS.md`，历史和当前可复现性验证见 `docs/VERIFICATION.md`。

## 本地运行

要求 Python 3.11 或更高版本。

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
python -m pytest
```

在未安装项目包时，也可以直接在仓库根目录运行 `python -m pytest`；pytest 配置会加载 `src` 目录。

### 普通用户交互式游玩

安装项目后，先准备一个本地存档目录，再启动：

```powershell
New-Item -ItemType Directory -Force .\runtime_data\play | Out-Null
xuanyi-play --case-dir .\data\cases --state-dir .\runtime_data\play
```

未刷新命令入口时，也可以从仓库根目录使用模块入口：

```powershell
.\.venv\Scripts\python.exe -m xuanyi_npc.cli.play `
  --case-dir .\data\cases `
  --state-dir .\runtime_data\play
```

默认等价于 `--mode manual --semantic-shadow off`。离线录屏演示可让 Fake Agent 通过同一规则与存档路径自动完成所选病例：

```powershell
xuanyi-play --case-dir .\data\cases --state-dir .\runtime_data\play `
  --mode fake --semantic-shadow off
```

如需验证旁路隔离，可把 `--semantic-shadow` 改为 `record-only`。该模式当前只使用离线 Mock，把脱敏记录写入 Git 忽略的存档子目录；记录不会进入 Agent Prompt、Campaign 或病例状态。manual 与 Fake 都不读取 API Key。`deepseek-v0` 只有在同时提供 API Key、显式付费确认、正预算和安全结果目录后才会先做模型发现。P4b 的一次真实授权已经消费并停止；该历史授权不能用于重跑或追加病例。

两个目录必须已经存在。病例与跨案规则在进入菜单前完成严格校验；存档目录保存玩家、病例会话和独立的 `campaigns/{player_id}.json`，并由 Git 忽略。菜单支持创建或选择玩家、查看玩家历程和推荐下一案、开始/继续病例、调查、诊断、处置、返回或保存退出。每个成功行动会立即原子保存，因此 EOF、Ctrl+C 或正常退出后可用同一命令恢复。

当前目录自动列出三个可玩病例。推荐顺序为旧纸伞→灰灶→月井，但三案始终可独立开始；无前史时显示中性内容，不影响 `resolved / 100`。按公开结果与处置规则可解锁“契物归属核验”和“交接顺序核验”，后续病例只显示安全历史反应与可选调查建议，不自动执行、不发现线索、不改变答案或评分。CLI 不显示正确答案，也不固定调查顺序。游玩不读取 `.env`，不需要 API Key，不调用 DeepSeek、BGE 或外部 Embedding。

### M5 离线纵向切片验收

安装后可使用一个新的空状态目录运行完整验收；原始结果写入 Git 忽略的 `results/`：

```powershell
New-Item -ItemType Directory .\runtime_data\m5_acceptance | Out-Null
xuanyi-m5-acceptance `
  --run-id m5_acceptance_local `
  --case-dir .\data\cases `
  --state-dir .\runtime_data\m5_acceptance `
  --campaign-rules .\data\campaign\cross_episode_rules_v1.json `
  --output .\results\m5_acceptance_local.json `
  --p4b-result .\results\m5_p4b_campaign_20260811.json `
  --p4d-result .\results\m5_p4d_recovery_20260811.json
```

该入口要求本机保留两份 Git 忽略的 P4 原始结果，以便逐字节核对冻结 SHA。新克隆没有这些私有原始结果时，不影响普通游玩或自动测试，但不能声称已完成该项历史文件核验。模块入口为 `python -m xuanyi_npc.evaluation.m5_acceptance`。验收不需要 API Key，不调用 DeepSeek、BGE 或网络服务。

安装完成后，可以运行一次固定的正确病例路线：

```bash
xuanyi-case-demo
```

也可以使用：

```bash
python -m xuanyi_npc.demo_case
```

演示会依次执行观察、询问、验物、观炁、诊断和处置，最后显示可解释的评分构成。全过程不调用大模型。

M2a 的 Agent 闭环使用 Fake LLM 自动验证，不需要 API 密钥：

```bash
python -m pytest tests/test_doctor_agent.py tests/test_v0_episode_runner.py
```

M4-P4 的 14 条跨 Episode 记忆 Gold 完全离线。安装项目后运行：

```bash
xuanyi-memory-eval
```

未安装项目时，在仓库根目录使用：

```powershell
$env:PYTHONPATH="src"
python -m xuanyi_npc.evaluation.memory_runner
```

命令会在两个全新临时目录中重复完整套件，比较排序后的 SQLite 逻辑快照与确定性结果哈希，并自动清理临时状态。输出指标只属于合成 Gold 与 64 维确定性 Fake Embedding；不代表真实 Embedding 语义质量、真实模型长期记忆成功率或生产性能。

M4.5-P1 的本地 Embedding 是可选能力，基础 `pip install -e ".[dev]"` 不会安装大型 ML 依赖。固定 Windows/Python 3.12/CUDA 12.6 环境的依赖、受控下载和离线烟雾命令见 `docs/M45_P1_LOCAL_EMBEDDING_REPORT.md`；模型目录、缓存和烟雾结果均被 Git 忽略。不要在没有单独下载授权时执行模型下载脚本。

M2b-P0 的 3 条 dev 场景也完全离线，可由一条命令重复运行：

```bash
xuanyi-dev-eval
```

未安装项目时，在仓库根目录使用以下准确命令：

```powershell
$env:PYTHONPATH="src"
python -m xuanyi_npc.evaluation.dev_runner
```

在 macOS/Linux 中使用 `PYTHONPATH=src python -m xuanyi_npc.evaluation.dev_runner`。输出只有确定性轨迹结果；Fake LLM 的延迟、Token、成本和真实成功率保持“未测量”。

M3-P0 的 MCP 工具层只在测试进程中运行。安装项目后可执行：

```bash
python -m pytest tests/test_mcp_p0.py
```

该检查通过官方 `Client(server)` 发现并调用以下冻结工具：`get_player_view`、`get_case_observation`、`observe_patient`、`question_patient`、`inspect_object`、`observe_qi`、`investigate_location`、`submit_diagnosis`、`execute_treatment`。它不会读取 `.env`、调用 DeepSeek、监听端口或启动 stdio/HTTP 服务。

M3-P1 提供显式配置的 stdio 启动入口。病例目录和状态目录必须已经存在，病例 JSON 会在占用协议通道前完成校验：

```bash
xuanyi-mcp-stdio --case-dir data/cases --state-dir <existing-state-directory>
```

未安装项目时可在仓库根目录运行：

```bash
python -m xuanyi_npc.mcp_server.stdio --case-dir data/cases --state-dir <existing-state-directory>
```

该进程的 stdout 只承载 MCP 协议帧；启动错误和诊断只写 stderr。缺少参数、目录无效或病例加载失败会在服务器启动前以非零状态退出。M3-P1 专项测试使用临时病例和状态目录，不修改仓库内真实会话。

首轮真实 Pilot 的脱敏动作轨迹可以在完全不连网的情况下重评：

```bash
xuanyi-pilot-replay
```

未安装项目时，在仓库根目录运行 `python -m xuanyi_npc.evaluation.pilot_runner`。该命令只使用仓库内脱敏动作和确定性规则，不读取 API Key，不调用 DeepSeek。

## DeepSeek M2b 配置与安全边界

当前配置固定使用 DeepSeek 官方 OpenAI 兼容地址和 `deepseek-v4-flash`，禁止自动切换 Pro 或旧模型别名。项目从仓库根目录运行时会自动读取本地 `.env`；系统环境变量优先于 `.env` 中的同名配置。

先在仓库根目录复制配置模板：

```powershell
Copy-Item .env.example .env
```

然后只在 `.env` 中把 `DEEPSEEK_API_KEY=replace_with_your_deepseek_api_key` 的占位值替换为真实 Key。`.env` 已被 Git 忽略；不要把真实 Key 写入 `.env.example`、源码、日志、测试或聊天。如果不希望密钥落盘，也可以继续使用操作系统环境变量。

模型发现已经完成。只有在再次获得外部请求授权、确需复核模型列表时，以下命令才会发起一次真实但只读的 `/models` 请求：

```bash
xuanyi-deepseek-models
```

未安装项目时，对应 PowerShell 命令为：

```powershell
$env:PYTHONPATH="src"
python -m xuanyi_npc.agents.deepseek_cli models
```

M2 真实 Pilot 已结束，不再运行模型发现、标准探针、安全探针或 Prompt 调优。现有 CLI 保留为实验历史实现，不是当前待执行步骤。已验证的保护参数包括：固定 Flash、每 Episode 最多 8 步、每步最多一次格式修复、非流式、关闭思考、Adapter 无隐式重试，以及发送每次 Chat 前按缓存未命中输入价和最大输出量执行的保守预算预留；超时、响应缺少用量或用量无法核对会冻结后续请求。

## 当前限制

- JSON 存储目前只用于验证状态接口，尚未处理多进程并发。
- M3-P0/P1 已证明 MCP Schema、应用服务边界、进程内调用和本地 stdio 子进程生命周期；HTTP/SSE、认证、远程 Host 与部署尚未验证。
- DeepSeek `LLMAdapter` 已通过 MockTransport 离线测试，并有标准探针和安全探针真实数据；单病例各一次不能代表稳定成功率、限流表现或长期成本。
- M1 只更新病例会话，不更新玩家能力、关系或长期记忆。
- 评分暂时只计算关键线索、诊断、处置和危险处置惩罚；提示扣分将在教学阶段接入。
- 已有本地交互式 CLI、三个可独立完成的病例、确定性跨案知识成长，以及 manual/Fake/DeepSeek V0 模式装配；网页界面尚未实现，真实模型结果仍只有单次工程案例。
- V0 的 M2a Harness、M2b-P0、M2b-P1a 和 M2b-P1b 工程门槛已经收口；V1 当前完成记忆持久化、基础检索、Agent 安全只读上下文和 P4 离线 Gold 评测，V2 仍只有配置与共享契约。
- 三个正式版本始终启用 `AgentContextFilter`；不安全提示词对照只允许在隔离的 A4 安全消融中运行。
- V1 只增加基础向量 Top-K 长期记忆并保持固定课程；多因素记忆排序、自适应教学与 Reflection 属于 V2。
- 长期记忆、自适应教学和 Reflection 明确不属于当前 V0 实现。
- M4-P4 已用冻结合成 Gold 验证投影、生命周期、检索、隔离、只读 Prompt 和协调恢复；该结论只证明离线程序化边界与 Fake Embedding 下的确定性结果，没有验证真实模型抵抗记忆提示注入或真实 Embedding 的语义能力。
- 本地 BGE-M3 Adapter 已完成离线烟雾、旧开发集和新 holdout 的正式双运行；工程、安全、重复性和主要排名门槛通过，但保守返回门禁的 micro F1 与更正切片未通过，因此不能声称真实语义召回已满足产品要求。外部 Embedding API 仍未授权，DeepSeek Chat 的历史授权不会自动延伸到其他供应商。
- 当前 V0 的固定课程只按步骤编号推进，不基于玩家表现动态改变。
- 当前真实样本仍只有一个病例上的单次探针运行，不足以形成正式成功率、跨病例比较或模型可靠性指标。
- M2 付费运行已经停止；M3 与 M4 已完成工程退出；M4.5 以 `closed_with_known_dense_retrieval_limitations` 关闭，P3 取消本轮执行。M5-P0～P5 已完成；P4b 负结果、P4c 通用接口修复和 P4d 单次真实恢复结果全部保留，P4 不再重跑或调优。M6-P0 已完成离线发布准备审计；M6-P1 等待公开身份、许可证和发布形态决策，当前没有远程仓库或已发布内容。
