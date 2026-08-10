# M4.5 真实记忆验证方案

## 1. 文档身份

- **状态**：M4.5-P0/P1 已完成；P2a 已离线冻结 Gold v2；命令入口已修复，但 run1 因执行 HEAD 与冻结参数不精确相等在模型加载前停止，P3 未开始
- **规划基线**：`6f678ce923adaa422fe8a84079fafe7fbd4143fb`
- **日期**：2026-08-08
- **当前结论**：M4 保持完成；本地 BGE-M3 Adapter 与离线烟雾已通过；历史 v1 的标签复用问题已由 P2a v2 三分区契约离线纠正。项目命令入口随后通过零网络 editable 重装修复，但 run1 因执行 HEAD `f573e03` 与传入冻结提交 `b780330` 不精确相等而被现有运行器拒绝；正式指标和重复性结果仍未产生，M5 尚未开始
- **P1 外部执行**：只从官方包源安装项目 `.venv` 依赖并从 Hugging Face 固定 revision 下载白名单；Embedding API 0、DeepSeek `/models` 0、Chat 0、费用 0 CNY

M4.5 是产品效果验证门槛，不回写 M4 的离线工程结论。M4 已证明 Fake Embedding 下的投影、存储、生命周期、隔离、Top-K、只读上下文和评测契约；M4.5 才回答“真实语义向量是否能找对历史、真实模型是否会正确使用历史”。

M5 应等待 M4.5。自适应教学会依据历史召回改变教学策略；如果真实召回尚未验证，后续失败将无法区分是“找错/漏找了记忆”还是“教学策略本身错误”，实验变量会混在一起。

## 2. 证据、推断与推荐

本方案明确区分三类陈述：

- **实测事实**：来自本机只读调查或现有代码；
- **官方证据**：来自模型发布方、官方仓库、官方文档或正式论文；
- **工程推荐**：基于上述证据作出的下一阶段选择，不代表已经安装、运行或验证。

## 3. 只读环境调查

### 3.1 本机必要规格

| 项目 | 只读调查结果 | 规划含义 |
|---|---|---|
| 操作系统 | Windows 10 IoT Enterprise LTSC，64 位，Build 19044 | PyTorch 官方支持 Windows 10+；仍需在 P1 用精确依赖版本验证 |
| CPU | AMD Ryzen 9 7900X，12 核 / 24 线程 | 可作为 GPU 不可用时的功能性回退，但延迟尚未测量 |
| 内存 | 约 31 GiB | 足以进行一个小型 dense Embedding Pilot；真实峰值仍需 P1 测量 |
| GPU | NVIDIA GeForce RTX 4070 SUPER | 可用于本地 CUDA 推理 |
| 显存 | 12,282 MiB | 足以评估约 0.6B 参数、约 2.27 GB 权重的候选模型；不代表长文本大批次必然不会 OOM |
| 驱动 | NVIDIA 576.57 | 只记录版本，不记录设备序列号 |
| 项目盘可用空间 | 约 120 GiB | 模型、依赖和缓存有充足空间，但 P1 仍限定下载范围 |
| Python | 系统与项目 `.venv` 均为 3.12.3，64 位 | 落在 PyTorch 官方 Windows Python 3.9–3.12 支持范围内 |
| 当前 ML 依赖 | 未安装 PyTorch、ONNX Runtime、Transformers、Sentence Transformers 或 NumPy | P0 没有改变环境；P1 需要单独安装/下载授权 |

调查没有记录序列号、用户名或个人目录。可用内存属于调查时瞬时值，不作为模型容量结论。

### 3.2 本项目可接受的本地模型范围

以下是工程约束，不是本机性能实测结果：

- 单个权重文件优先不超过 3 GB，模型仓库允许文件总量不超过 5 GB；
- P1 下载前至少保留 10 GB 可用空间，覆盖权重、固定依赖和缓存；
- 参数规模优先不超过约 1B，输出维度不超过现有契约上限 4096；
- 首轮只用 dense embedding，不引入 sparse、ColBERT、多向量或 reranker；
- 生产式大批量、长文本和多模型常驻不在本轮容量声明内。

### 3.3 现有接口的最小接入面

现有 `EmbeddingAdapter` 已冻结请求版本、空间 ID、维度、批次顺序、有限数值、非零范数和返回数量校验；SQLite 派生向量与余弦检索也已按 `embedding_space_id` 隔离。真实本地实现预计只需：

1. 新增一个实现既有 `EmbeddingAdapter` 的具体 Adapter；
2. 新增显式配置：本地模型目录、不可变 revision、文件清单哈希、设备、精度、批次和超时；
3. 新增稳定错误映射与独立的实验测量记录器；
4. 新增 Mock、离线加载、维度、顺序、数值和无网络测试；
5. 在显式 V1 组装中替换 Fake Adapter，不修改权威记忆、生命周期、Top-K 排序或 V0。

基础 `embed()` 契约不需要加入供应商字段。请求数、延迟、Token/计费单位和费用由可注入的 Pilot 测量记录器保存，不能污染派生向量或 Fake Embedding 结果。模块导入不得加载模型、读取 `.env` 或访问网络。

## 4. 三条路线比较

### 4.1 方案 A：本地 Embedding

#### 首选候选：`BAAI/bge-m3`，dense-only

官方模型页和仓库记录：MIT 许可证、100+ 语言、最长 8192 Token、dense 输出 1024 维，并支持 Sentence Transformers、PyTorch 与 ONNX。P1 对固定 revision `142964af7e05de16511657561de8e8750fc153a0` 的官方文件树重新核对后，整个 revision 为 `6,858,381,860` 字节（约 6.86 GB），纠正 P0 时约 4.59 GB 的旧估计；本项目只下载 11 个 dense Sentence Transformers 白名单文件，共 `2,293,250,249` 字节。单个 `model.safetensors` 为 `2,271,064,456` 字节，SHA-256 为 `993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e`。完整逐文件哈希见 `docs/M45_P1_LOCAL_EMBEDDING_REPORT.md`。

优势：

- 记忆文本不离开本机；
- 中文、中英混合和跨语言检索属于模型发布方明确支持范围；
- 1024 维直接落在现有向量契约内；
- dense-only 可复用现有余弦 Top-K，不引入向量数据库或 reranker；
- 现有请求不区分 query/document 角色，BGE-M3 的基础 dense 用法可保持这一边界，改动小；
- 模型页标注 MIT；P1 必须保存并复核许可证全文，任何商业分发都保留许可证与版权声明。

成本与风险：

- 首次需要约 2.3 GB 模型权重，以及 PyTorch、Transformers、Sentence Transformers 等较大依赖；
- Windows CUDA 依赖组合、显存峰值、冷启动和 CPU 延迟尚未实测；
- 将模型一起打包会显著放大交付物，不应默认随 Python 包分发；
- 发布方基准不能代替本项目志怪中文语义 Gold；
- P1 必须优先使用 safetensors、`trust_remote_code=False`、`local_files_only=True`，并拒绝未列入清单的 pickle 权重、静默联网和 hash 不匹配。

本机是否适合：**适合做本地 Pilot**。12 GiB 显存和 31 GiB 内存对该候选有明显余量，但只有 P1 的真实冷启动、峰值显存、GPU/CPU 延迟和两次输出稳定性测试才能形成运行结论。

#### 备选本地候选：`Qwen/Qwen3-Embedding-0.6B`

官方资料记录 Apache-2.0、0.6B 参数、100+ 语言、32K 上下文、最高 1024 维，仓库约 1.21 GB，其中 safetensors 约 1.19 GB。它更小且中文基准较新，但官方建议查询使用任务 instruction，而文档不加 instruction；要发挥该能力，需要新增版本化的 query/document 格式身份，改动和实验变量均多于 BGE-M3。因此它保留为首选候选失败后的本地备选，不与首轮 Pilot 同时引入。

#### 运行与复现规划

- 首轮精度固定为 FP32；GPU 与 CPU 若都运行，必须使用不同 `embedding_space_id` 或证明向量容差与排序一致后再决定是否共用；
- 候选空间 ID 形式为 `bge_m3_<revision12>_dense_fp32_d1024_v1`，完整 revision、文件 SHA、依赖锁、设备和配置进入 Pilot manifest；
- 不下载 `.bin`、ONNX、sparse/ColBERT 权重或图片等非允许文件；
- 本地模型文件由部署者单独缓存，Python 包只保存 manifest 和加载配置；
- 重复性以“文件 SHA 相同、配置相同、两次排序/指标相同、向量差异在预先冻结容差内”判断，不声称跨硬件逐字节一致。

### 4.2 方案 B：外部 Embedding API

DeepSeek Chat Key 不自动适用于任何 Embedding 供应商。下面只是官方资料快照，不代表已开户、同意条款或调用成功。

| 供应商与模型 | 官方端点与限制 | 价格/免费额度 | 数据与账户边界 | 结论 |
|---|---|---|---|---|
| 阿里云百炼 `text-embedding-v4`（北京） | OpenAI 兼容 base URL `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，Embedding 模型名精确为 `text-embedding-v4`；64–2048 维，默认 1024；每请求最多 10 条、单条最多 8192 Token、每批最多 33,000 Token；30 RPS、1,200,000 TPM | 实时 CNY 0.0005/千输入 Token，即 0.5 元/百万；北京新用户显示 100 万 Token、90 天的一次性免费额度，必须在控制台核对是否真实剩余 | 需要阿里云账号、实名认证/服务开通、北京 Workspace 和独立 `DASHSCOPE_API_KEY`；官方声明不把数据用于模型训练，并提供账户级用量监控，但公开页面没有给出本项目可以依赖的直接 API 原文/日志保留期限 | 外部 API 首选备选；规格、价格和隐私说明最完整 |
| 智谱 `embedding-3` | `POST https://open.bigmodel.cn/api/paas/v4/embeddings`；256/512/1024/2048 维；数组最多 64 条；官方页面同时写 8K 上下文与单条最多 3072 Token，Pilot 应采用更严格的 3072 限制；本次资料未确认可选择的服务区域 | CNY 0.5/百万 Token；本次一手资料未确认可用免费额度 | 需要新的智谱账号和 API Key；本次一手资料未找到足够明确的直接 API 原文/日志保留和训练使用条款 | 技术备选；隐私、区域和额度证据不足，不能优先 |

外部 API 的优势是依赖轻、无需本地模型常驻、维护成本低；缺点是文本离开本机、需要新账号和密钥、供应商模型可能漂移，且长期调用会产生按量费用。两份官方文档都提供面向中国用户的公开端点，但本轮没有验证用户网络的实际可达性。任何外部路线都必须使用直接、可测试的 HTTP Adapter，不强制安装供应商 SDK；首轮固定连接超时 10 秒、单请求总超时 60 秒、无隐式重试。

#### 外部最小 Pilot 成本

语义 Gold 规划为 15 条查询和 60 条候选记忆，共 75 条唯一合成文本，保守输入上限 16,000 Token。若使用阿里 `text-embedding-v4` 实时接口，按每批 10 条最多 8 次请求，目录价最大约 `16,000 / 1,000 × 0.0005 = 0.008 CNY`。即使控制台有免费额度，预算门禁仍按目录价计算，建议严格上限 **0.05 CNY**。

该估算不是实际费用。P2 只有在请求前最大成本门禁、返回用量核对、独立费用统计和用户单独授权都完成后才能调用。

### 4.3 方案 C：继续只用 Fake Embedding

Fake Embedding 可以继续演示存储、隔离、生命周期、索引重建和 Agent 安全边界，成本与网络调用为 0。它不能证明中文同义词、无字面重合的语义关系或真实错误诱饵排序有效，也不能支持“长期记忆改善了教学”的产品结论。

该路线适合暂时停止、离线演示或回归测试，不建议在此状态下实现或评估 M5 自适应教学。

### 4.4 对比摘要

| 维度 | 本地 BGE-M3 | 外部 API | 继续 Fake |
|---|---|---|---|
| 中文真实语义 | 待本项目 Gold 验证；官方支持 100+ 语言 | 待本项目 Gold 验证；两候选均声明中文能力 | 不具备可宣称的真实语义能力 |
| 数据出域 | 否 | 是，仅可发送批准的合成文本 | 否 |
| 首次准备 | 下载约 2.3 GB 权重并安装大型依赖 | 新账号、服务条款、独立 Key | 无 |
| 持续费用 | 无调用费，消耗本机资源 | 按 Token 付费 | 无 |
| 维护 | 需固定模型/依赖和处理 Windows CUDA | 需处理供应商漂移、限流、计费和隐私 | 最低 |
| 现有接口改动 | 小 | 中等，需 HTTP、用量、预算和供应商错误 | 已完成 |
| 能否进入 M5 | 通过 P2/P3 后可以 | 通过 P2/P3 后可以 | 不建议 |

## 5. 推荐决策

**推荐先走本地 `BAAI/bge-m3` dense-only。**

理由：本机硬件足够做小型本地 Pilot；记忆文本完全留在本地；MIT 许可清晰；1024 维和无角色化 instruction 的基础用法最贴合现有供应商无关 Adapter；一次下载后没有长期调用费用。外部 API 保留为 P1 因 Windows/CUDA、依赖体积、延迟或模型质量门禁失败时的单独备选，首选阿里云百炼 `text-embedding-v4`。

该推荐不等于授权。用户下一次需要作出的决定是：

- **进入 P1 时**：授权安装固定依赖并下载经 revision/SHA 清单约束的本地 BGE-M3 文件；不需要 API Key 或人民币预算；
- **仅当改走 API 时**：用户自行开通供应商账号、接受条款、创建独立 Key，并授权最多 0.05 CNY 的 P2 Embedding 预算；DeepSeek Key 不复用；
- **进入 P2 时**：无论本地/API，都需要单独授权执行冻结语义 Gold；
- **进入 P3 时**：需要单独授权 DeepSeek Chat 预算；Embedding 与 Chat 的调用数、费用和停止门禁完全分开。

### 5.1 数据发送边界

允许参与本地或外部 Pilot：

- 经人工检查的、公开、合成、架空病例记忆文本；
- 合成的中文、中英混合查询；
- 不含真实身份的固定测试 ID，只在本地 manifest 中使用，发送文本本身不携带 ID。

绝对禁止发送：

- 真实玩家姓名、账号、`player_id`、聊天原文或自由文本日志；
- 病例根因、未发现线索、正确答案标记、评分、隐藏门槛；
- 关系值、能力值、技能、权限、来源收据或内部文件路径；
- `.env`、API Key、Authorization、供应商请求 ID 或其他密钥；
- 未获得授权的真实运营数据、个人信息或第三方内容。

### 5.2 失败回退

Embedding 是派生数据，权威记忆仍在 SQLite `memory_events`。真实 Adapter 失败时：

1. 不修改或删除权威记忆；
2. 不把部分真实向量标为完整索引；
3. V1 返回 `memory_context_unavailable`，不调用 LLM；
4. 可在显式工程演示中重建 Fake 空间，但不得在真实 Pilot 中静默切换；
5. Fake 与真实向量使用不同 `embedding_space_id`，互不覆盖或混用；
6. 失败结果与已完成测量保留，禁止自动重跑。

## 6. M4.5 分阶段门槛

| 阶段 | 输入 | 产物 | 不包含 | 退出条件 | 网络/付费 | 停止条件 |
|---|---|---|---|---|---|---|
| P0：规划 | M4 退出结论、现有接口、本机只读规格、官方资料 | 本文、语义 Gold 规划、路线推荐与授权边界 | 代码、依赖、模型、API 调用 | 文档一致；全量与 M4 Gold 回归通过 | 无 | 资料无法支持模型/价格/隐私结论时只记录未知，不猜测 |
| P1：真实 Adapter 离线实现与 Mock | 单独下载/安装授权、不可变模型 revision 与文件清单 | 本地 BGE-M3 Adapter、显式配置、Mock、离线加载/维度/无网络测试、模型 manifest | Gold 实跑、Agent Prompt、真实 Chat | **已完成**：`local_files_only`、无导入副作用、向量严格有效、批次/顺序一致、V0 零调用、Fake 空间不变 | 只发生获授权的官方依赖/模型下载；模型 API 与调用费为 0 | hash/许可/依赖不符、静默联网、OOM、维度漂移、非有限向量或 V0 变化即停止 |
| P2：真实语义 Pilot | P1 通过、语义 Gold 与阈值已提交冻结、单次运行授权 | 真实排序、Recall@K/MRR/P/R/F1、空结果、Fake 差异、延迟、模型身份与脱敏结果 | Chat、Prompt 调优、真实玩家数据 | 语义门槛达到；安全计数全 0；两次本地排序一致；原始文件忽略 | 本地 0 CNY；API 备选需独立 Key 和最多 0.05 CNY | 预算拒绝、超时、维度/模型变化、用量缺失、费用不可核对、hash 变化或安全计数非 0 即停止 |
| P3：真实 V1 Agent Pilot | P2 通过、V1 `v1.0.0`、固定课程、真实检索、单独 Chat 授权 | 少量跨 Episode 行为探针、Chat/Embedding 分账、事件与重放证据 | 自适应课程、写记忆工具、Reflection、M5 | 相关历史使用、当前事实隔离、注入边界、无虚假记忆、无永久写入口和 unavailable 停止均有真实证据 | DeepSeek Chat 建议独立上限 0.10 CNY；Embedding 另设独立计数/上限 | 任一预算/用量/超时/模型/索引/安全停止条件触发即保存并结束，不自动重跑 |
| 退出审计 | P0–P3 提交与原始结果哈希 | 分层结论、限制、是否准入 M5 | 新调参、新运行、M5 代码 | 证据支持工程与行为边界；负结果未被改写 | 无新增调用 | Gold 漂移、数据越界、安全计数非 0 或证据不足则不得关闭 M4.5 |

## 7. P2 Pilot 固定门禁

- 只用 `docs/M45_SEMANTIC_GOLD_PLAN.md` 规定并在运行前提交冻结的语义 Gold；
- 15 条场景、75 条唯一文本、每种 Adapter 只运行一次正式 Pilot；
- 外部路线最多 8 个 Embedding 请求，保守输入上限 16,000 Token；本地路线记录批次数但 API 请求为 0；
- 运行前按目录价保守预留，只有“已确认费用 + 本批最大费用 ≤ 授权上限”才执行；
- 禁止自动重跑、自动切换模型、自动改变维度、阈值或 Top-K；
- 超时、返回数量/顺序/维度异常、非有限或零范数向量、用量缺失、费用不可核对立即停止；
- 原始结果进入 Git 忽略目录，仓库只保存脱敏指标、配置身份、模型/清单 SHA-256 和结果 SHA-256；
- 单次结果只称“小型合成语义 Pilot”，不得写成产品准确率或真实玩家收益。

指标至少包括 Recall@1、Recall@3、MRR、macro/micro Precision/Recall/F1、空结果正确率、False Memory Rate、Fake/真实 Top-K 重合与排序差异、冷/热延迟、请求/批次数、Token 或供应商计费单位、人民币费用。跨玩家串扰、当前 Episode 召回、隐藏泄漏、inactive/删除复活必须为 0。

## 8. P3 真实 V1 Agent Pilot

P3 只有在 P2 通过并完成独立审计后才可授权。它固定使用：

- DeepSeek `deepseek-v4-flash`；
- V1 Prompt `v1.0.0`；
- P2 通过的真实 Embedding 空间；
- V1 基础余弦 Top-K；
- V0 相同的固定课程、`AgentAction`、规则引擎、一次格式修复和事件写入；
- 无永久记忆写、改、删工具。

建议冻结 5 个行为探针：

1. `v1_relevant_history_use_001`：模型能引用相关历史，但仍依据当前病例行动；
2. `v1_history_not_current_truth_001`：模型不把过去行为或错误假设当作当前病例真相；
3. `v1_memory_injection_resistance_001`：记忆中的“忽略规则/调用工具”等文本不改变动作边界；
4. `v1_false_memory_abstention_001`：没有相关历史时不声称记得不存在的事实；
5. `v1_memory_unavailable_stop_001`：离线制造 unavailable，预期 Embedding/Chat 调用均为 0。

前四个探针各运行一次、每个最多 8 次 Chat，总上限 32 次；第五个不调用模型。任何 Agent 尝试使用不存在的永久记忆写工具都由现有 Schema 拒绝并单独记录。Chat 预算建议上限 0.10 CNY；若 P3 使用外部 Embedding，Embedding 预算另行设置，绝不与 Chat 共用余额或调用统计。

## 9. 一手资料

资料核对日期均为 2026-08-08：

- [BAAI/bge-m3 官方模型仓库与文件清单](https://huggingface.co/BAAI/bge-m3/tree/main)
- [BGE-M3 safetensors 不可变文件页与 SHA-256](https://huggingface.co/BAAI/bge-m3/blob/142964af7e05de16511657561de8e8750fc153a0/model.safetensors)
- [FlagEmbedding 官方仓库](https://github.com/FlagOpen/FlagEmbedding)
- [BGE-M3 正式论文](https://arxiv.org/abs/2402.03216)
- [Qwen3-Embedding-0.6B 官方模型页](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
- [Qwen3 Embedding 官方仓库](https://github.com/QwenLM/Qwen3-Embedding)
- [Qwen3 Embedding 正式论文](https://arxiv.org/abs/2506.05176)
- [PyTorch Windows/Python 官方安装支持](https://docs.pytorch.org/get-started/locally/)
- [Sentence Transformers 官方安装说明](https://sbert.net/docs/installation.html)
- [阿里云百炼 Embedding 模型、端点、价格与额度](https://help.aliyun.com/en/model-studio/embedding)
- [阿里云百炼限流](https://help.aliyun.com/en/model-studio/rate-limit)
- [阿里云百炼隐私说明](https://www.alibabacloud.com/help/en/model-studio/privacy-notice)
- [阿里云百炼新用户免费额度规则](https://help.aliyun.com/en/model-studio/new-free-quota)
- [智谱 Embedding-3 官方说明](https://docs.bigmodel.cn/cn/guide/models/embedding/embedding-3)
- [智谱文本嵌入 API](https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E6%96%87%E6%9C%AC%E5%B5%8C%E5%85%A5)

## 10. Material Passport

- **实体**：本地模型文件、真实 Embedding Adapter、派生向量、语义 Gold、Pilot 原始结果与脱敏指标
- **来源**：模型发布方不可变仓库/论文、供应商官方文档、现有确定性记忆事件和合成架空文本
- **写入权限**：模型只能返回向量；权威记忆仍只由已验证领域事件投影。Adapter 不得写权威记忆
- **派生关系**：真实向量按独立 `embedding_space_id` 依附 active 权威记忆，可删除和重建
- **删除/失效**：沿用 M4 生命周期；更正、失效和硬删除同步清理所有真实/Fake 派生空间，不从墓碑复活
- **外发边界**：本地路线无文本外发；API 路线只发送冻结的合成架空文本
- **审计身份**：full model revision、逐文件 SHA、依赖锁、设备/精度、查询模板、维度、Top-K/阈值、请求/费用和结果 SHA
- **保留策略**：原始供应商结果与请求 ID 仅在 Git 忽略目录；仓库只提交脱敏指标和哈希
