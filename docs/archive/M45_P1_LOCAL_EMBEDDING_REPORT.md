# M4.5-P1 本地 BGE-M3 Adapter 与离线烟雾报告

- **执行基线**：`d7c474d474a2ffe7e53909a09e33f2d826b6f733`
- **执行日期**：2026-08-08
- **范围**：固定本地依赖、严格白名单下载、Adapter/Mock、真实权重离线烟雾
- **不包含**：15 条语义 Gold、Top-K/阈值调整、Agent Prompt 接入、真实 Chat、任何 Embedding API、M5
- **外部模型调用**：DeepSeek `/models` 0、Chat 0、Embedding API 0、费用 0 CNY

## 1. 下载前预检

| 项目 | 结果 |
|---|---|
| 项目虚拟环境 | CPython `3.12.3`，pip `26.2.1` |
| `.venv` 下载前大小 | `83,183,416` 字节（`0.077 GiB`） |
| 项目盘下载前可用空间 | `128,752,443,392` 字节（`119.91 GiB`） |
| GPU | NVIDIA GeForce RTX 4070 SUPER，`12,282 MiB` 显存 |
| 驱动 / 驱动报告 CUDA | `576.57` / `12.9` |
| 安装后 PyTorch CUDA | `torch 2.12.1+cu126` / CUDA `12.6`，`torch.cuda.is_available() == True` |
| 下载前依赖状态 | `.venv` 不含 Torch、Transformers、Sentence Transformers、Safetensors 或 NumPy；`pip check` 通过 |

官方 wheel 的解析下载量为 `2,706,665,286` 字节（`2.521 GiB`）。按解压安装最多为 wheel 的两倍、安装期保留一份临时 wheel、模型使用单个 `.partial` 原子改名的保守估算，峰值新增占用约 `9.7 GiB`；低于授权的 `12 GiB`，且可用空间高于 `20 GiB` 停止线，因此才开始安装和下载。

## 2. 固定依赖与来源

只修改仓库内 `.venv`。准确安装清单保存在 `requirements/local-embedding-cu126-win-py312.txt`：

- 官方 PyTorch CUDA 12.6 index：`torch==2.12.1+cu126`；
- 官方 PyPI：`numpy==2.4.6`、`safetensors==0.8.0`、`transformers==4.57.6`、`sentence-transformers==5.7.0` 及锁定的传递依赖；
- 安装使用 `--no-cache-dir`，仓库内没有持久下载缓存；
- `pip check` 通过；
- `pyproject.toml` 中为独立 `local-embedding` extra，基础 `.[dev]` 不会自动安装大型 ML 依赖。

安装后 `.venv` 为 `4,817,133,738` 字节，较下载前增加 `4,733,950,322` 字节（`4.409 GiB`）。没有修改系统 Python、Anaconda、全局 pip 或 Git 身份。

## 3. 模型身份、资料纠偏和白名单

- 仓库：`BAAI/bge-m3`
- revision：`142964af7e05de16511657561de8e8750fc153a0`
- 模式：dense-only
- 精度：FP32
- 维度：1024
- 加载：`local_files_only=True`、`trust_remote_code=False`
- 本地目录：`runtime_models/bge-m3-142964af7e05`（Git 忽略）

固定 revision 的官方文件树合计 `6,858,381,860` 字节（约 `6.86 GB`），纠正 P0 文档中约 `4.59 GB` 的旧估计。本项目没有下载完整仓库，只下载下列 11 个 Sentence Transformers dense 文件，共 `2,293,250,249` 字节（约 `2.293 GB` / `2.136 GiB`）。该 revision 没有独立 `LICENSE` 文件，许可证信息保留在白名单 `README.md` 模型卡中。

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| `1_Pooling/config.json` | 191 | `e54c164a07274f2eb45bb724f54a79d1efcc90c41573887cd9a29aeee0597352` |
| `README.md` | 15,822 | `0b81ccf9134e5874d620a86e6905062ea999e779c34eb1a7e65eaeb7fe00e450` |
| `config.json` | 687 | `26159e7ad065073448460117eb24b7a4572f6f4e78eadff65dc0a11c052449fa` |
| `config_sentence_transformers.json` | 123 | `1eef72430e7194a1e59680e635aed81ffa083f05668dbc5bb1c56c04c0999c38` |
| `model.safetensors` | 2,271,064,456 | `993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e` |
| `modules.json` | 349 | `84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf` |
| `sentence_bert_config.json` | 54 | `eb9b44b13c0f52a3b3685c3b1cbdea1ba8b04bea123b98f61610048940776eb1` |
| `sentencepiece.bpe.model` | 5,069,051 | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` |
| `special_tokens_map.json` | 964 | `8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835` |
| `tokenizer.json` | 17,098,108 | `21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08` |
| `tokenizer_config.json` | 444 | `a62b2b6784f990259fddef5f16388693a8043be4f69179e6a5257eeb3f9abac4` |

预期清单和逐文件验证清单分别位于 `config/model_manifests/*_expected.json` 与 `*_verified.json`。验证清单的规范 JSON SHA-256 为 `d4ee3716bb6c6c5dd850ea0cf1d64f0218aed9cfbbc52a6e8061f439a05965a4`。`.bin`、`.pt`、pickle、ONNX、图片、sparse、ColBERT 和 reranker 文件均未下载。

## 4. Adapter 边界

`BgeM3LocalEmbeddingAdapter` 实现既有 `EmbeddingAdapter`，但不会在模块导入或构造时加载 Torch/模型。显式 `load()` 会先核对：

1. 完整 revision、模型/设备/精度/维度身份；
2. 规范 manifest SHA；
3. 本地目录恰好包含 11 个白名单文件；
4. 每个文件的大小和 SHA-256；
5. `modules.json` 只包含官方 `Transformer`、`Pooling`、`Normalize` 三种模块。

随后才以 CUDA、FP32、`local_files_only=True`、`trust_remote_code=False` 加载。它只返回 dense、L2 归一化向量，严格保持数量与顺序，并拒绝维度漂移、NaN、无穷、零范数和数量错误；不会自动切换 CPU、模型、精度、revision 或 Fake 空间。当前烟雾空间为：

`bge_m3_142964af7e05_dense_fp32_d1024_cuda_l512_v1`

设备和最大输入长度进入空间 ID，未经单独一致性证据的 CPU/GPU 或截断设置不会混用派生向量。

## 5. 真实权重离线烟雾

烟雾使用三条固定公开合成文本；未运行 15 条正式语义 Gold。程序在模型加载与两轮推理期间同时设置 Hugging Face/Transformers 离线模式并封锁 Python socket 连接：

| 指标 | 结果 |
|---|---:|
| 网络连接尝试 | 0 |
| 输出数量 / 维度 | 3 / 1024 |
| 三个向量 L2 范数 | `1.0 / 1.0 / 1.0` |
| 两轮最大逐元素差异 | `0.0` |
| 两轮批次 SHA-256 | 均为 `f7e1079522eff5e63554673cadb971d2393afd74f5ef63f3859eda866efb6f37` |
| 冷加载 | `5,876.608 ms` |
| 首轮推理 | `173.137 ms` |
| 热推理 | `15.610 ms` |
| 峰值进程工作集 | `3,351,314,432` 字节（约 `3.121 GiB`） |
| 峰值 CUDA allocated | `2,281,566,720` 字节（约 `2.125 GiB`） |
| 峰值 CUDA reserved | `2,294,284,288` 字节（约 `2.137 GiB`） |

第一次烟雾已完成模型加载和两轮推理，但最终 Windows 峰值内存读取因 64 位句柄类型未声明而失败；修复仅作用于烟雾遥测，未改变模型、向量、Adapter 或检索逻辑。随后完整烟雾通过，原始脱敏指标保存在 Git 忽略的 `runtime_data/`，真实向量未写入仓库。

## 6. 磁盘、Git 与阶段结论

`.venv` 与模型最终合计新增 `7,027,200,571` 字节（`6.545 GiB`），低于 `12 GiB` 授权上限。`runtime_models/`、`.venv/`、`runtime_data/`、`.env` 和 `results/` 均不被 Git 跟踪；未修改或清理用户全局 Hugging Face 缓存。

M4 保持完成。M4.5-P1 只证明固定 BGE-M3 能在本机以严格白名单、离线 CUDA 方式加载，并符合现有向量契约；它不证明真实语义检索效果、真实 V1 Agent 使用记忆的效果或产品收益。M4.5-P2 尚未开始，15 条正式语义 Gold 尚未创建或运行；M5 尚未开始。
