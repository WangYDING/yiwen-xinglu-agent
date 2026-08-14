# M4.5-P2 v2 run1 资源遥测异常停止记录

## 1. 三类历史身份

- **Gold v2 原始冻结提交**：`b78033099663464bf3d7790c6fef5d4b973dc692`
- **本次精确执行提交**：`0ed89c15dfbb3dcb6a637813fabef205ffc1229e`
- **本次 run1 ID**：`m45_p2_v2_0ed89c1_run1_20260810`

`b780330` 继续表示输入、v2 expectations、v2 manifest、配置和评测器的原始冻结来源；`0ed89c1` 只在该冻结内容之上保留两次诚实停止记录，并作为本次运行器要求的精确 HEAD。预检确认二者在 `src/`、`tests/`、`data/evaluation/`、`requirements/` 和 `pyproject.toml` 零差异。本轮没有把 `0ed89c1` 描述为重新设计或调优 Gold。

此前两次停止历史继续保留：

1. `f573e03`：项目 `.venv` 尚无已安装命令入口，评测器未启动；
2. `0ed89c1` 前一轮：入口修复成功，但执行 HEAD 与传入冻结参数不精确相等，模型未加载。

## 2. 本次预检

以下条件全部通过后才启动 run1：

- HEAD 精确等于 `0ed89c15dfbb3dcb6a637813fabef205ffc1229e`；
- 工作树干净；
- 输入 SHA：`ca55bebdafaa59c06eab156c44316c2f862264e9082c71b768ab54d867674f3d`；
- v2 expectations SHA：`2ce0c4ab316243b06be7a80a5b3617f26b06545a736202bd27ebf24490b9d8d0`；
- v2 manifest SHA：`4479ca16df1457782fd94af919da1942ca87619d080a2f0e339779e83447aa61`；
- 配置 SHA：`1c302cb2155260812278a70defae23d869aee094b1a28523210fb826a332fda8`；
- 模型 manifest SHA：`d4ee3716bb6c6c5dd850ea0cf1d64f0218aed9cfbbc52a6e8061f439a05965a4`；
- 主权重 SHA：`993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e`；
- 依赖锁 SHA：`8e4179d4177fbafb62d6e1e17878ca7a71bb12c2d3d7d2747cf7ab83a1ffc0a6`；
- 入口 SHA：`FF6C0EE3CAF015F64CD84BF5B3D664CC06407E17F17C993017B54B64E85DF7A2`；
- CUDA 12.6、RTX 4070 SUPER、FP32、1024 维及冻结空间一致；
- run1/run2 结果路径均不存在。

## 3. run1 执行与停止点

run1 使用授权命令原样启动。评测器通过精确 HEAD、Gold/配置、模型文件、CUDA 和网络封锁门禁，加载本地 BGE-M3 一次并完成全部场景循环。随后在构造最终 `SemanticRunResourceMetrics` 时调用 Windows `GetProcessMemoryInfo`，因 `ctypes` 未声明进程句柄的 64 位参数类型而失败：

```text
ctypes.ArgumentError: argument 1: OverflowError: int too long to convert
```

异常发生在结果序列化和文件写入之前。run1 正式 JSON 未创建，内存中的 Top-K、相似度、阈值、语义指标、Fake 对照、向量值和延迟没有可恢复的原始文件。根据授权中的评测器异常与结果保存停止条件，没有修改遥测函数、没有重跑 run1，也没有启动 run2。

## 4. 可核对与不可核对结果

从固定执行顺序可以核对：

- 身份门禁通过；
- CUDA BGE 加载 1 次，未回退 CPU；
- 15 条场景循环在异常前完成；
- socket 网络封锁范围已经退出且没有触发网络尝试错误；
- 安全硬门槛在资源遥测前已通过，`safety.total = 0`；
- 自动重试 0，run2 启动 0。

因此下列安全计数在该进程控制流中均为 0，但没有被写入正式结果文件：

| 安全计数 | 值 |
|---|---:|
| `cross_player_recall` | 0 |
| `current_episode_recall` | 0 |
| `inactive_memory_recall` | 0 |
| `deletion_resurrection` | 0 |
| `hidden_content_leak` | 0 |
| `prompt_boundary_violation` | 0 |
| `authority_write_by_embedding` | 0 |
| `embedding_space_mixing` | 0 |
| `incomplete_index_as_empty` | 0 |

以下均为 `not_observed`，不得根据进程内临时值或历史失败运行补造：

- 15 条逐项 Top-K 与相似度；
- calibration/test 最终指标；
- 阈值选择过程与最终阈值；
- Recall@1、Recall@3、MRR；
- macro/micro Precision、Recall、F1；
- False Memory Rate、empty 正确率、semantic negative 普通 FP；
- Fake/BGE 同口径差异；
- 两次排序、指标、向量容差及结果哈希一致性；
- 冷/热推理延迟、正式峰值内存/显存和结果文件磁盘占用。

## 5. 原始证据与外部边界

- 忽略目录失败检查点：`results/m45_p2_v2_0ed89c1_run1_failure_20260810.json`
- SHA-256：`D853266CAA8C24D0F37A705F8EC5B3C1784E63EDBB24140C6933AA3E1B431517`
- 大小：`1,286` 字节
- run1 正式结果：未创建
- run2 正式结果：未创建
- DeepSeek `/models`：0
- DeepSeek Chat：0
- 外部 Embedding API：0
- 网络尝试：0
- 费用：0 CNY

## 6. 判定

M4.5-P2 **再次因工程条件停止**。本次不是语义质量未通过，也不能据此判定达到 P3 准入线。修正 Windows 资源遥测需要新的代码修改、测试、提交和再次运行授权；本轮不实施。M4.5-P3 与 M5 尚未开始。
