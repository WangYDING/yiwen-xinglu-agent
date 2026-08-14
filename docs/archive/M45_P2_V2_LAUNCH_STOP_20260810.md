# M4.5-P2 v2 本地语义 Pilot 启动停止记录

## 1. 结论

- **授权基线**：`b78033099663464bf3d7790c6fef5d4b973dc692`
- **日期**：2026-08-10
- **状态**：在 Python 评测器启动前停止
- **停止类别**：`runtime_entry_point_unavailable`
- **M4.5-P2 结论**：未完成，不能判断 P3 准入

项目 `.venv` 中没有已安装的 `xuanyi-semantic-memory-eval.exe` 命令入口。PowerShell 在创建 Python 进程、加载模型或写正式结果前返回 `CommandNotFoundException`。按照本次授权中“运行环境错误立即停止”的门禁，没有改用模块入口、没有刷新 editable install，也没有执行第二次运行。

## 2. 启动前身份核对

| 项目 | 核对结果 |
|---|---|
| HEAD | `b78033099663464bf3d7790c6fef5d4b973dc692`，匹配 |
| 工作树 | 启动前干净 |
| 输入 SHA-256 | `ca55bebdafaa59c06eab156c44316c2f862264e9082c71b768ab54d867674f3d`，匹配 |
| v2 expectations SHA-256 | `2ce0c4ab316243b06be7a80a5b3617f26b06545a736202bd27ebf24490b9d8d0`，匹配 |
| v2 manifest SHA-256 | `4479ca16df1457782fd94af919da1942ca87619d080a2f0e339779e83447aa61`，匹配 |
| 配置 SHA-256 | `1c302cb2155260812278a70defae23d869aee094b1a28523210fb826a332fda8`，匹配 |
| 模型 revision | `142964af7e05de16511657561de8e8750fc153a0`，匹配 |
| 模型白名单 | 11 个文件、`2,293,250,249` 字节，逐项验证通过 |
| 主权重 SHA-256 | `993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e`，匹配 |
| 依赖锁 SHA-256 | `8e4179d4177fbafb62d6e1e17878ca7a71bb12c2d3d7d2747cf7ab83a1ffc0a6`，匹配 |
| CUDA | PyTorch CUDA 12.6，可用 |
| GPU | NVIDIA GeForce RTX 4070 SUPER，12,282 MiB，总空闲 10,312 MiB |
| Adapter 空间 | `bge_m3_142964af7e05_dense_fp32_d1024_cuda_l512_v1`，匹配 |
| 正式结果路径 | 两个预注册路径启动前均不存在 |

模型文件验证只读取白名单及哈希，没有加载 BGE 权重。Hugging Face 与 Transformers 离线环境变量已设置，但由于命令入口不存在，运行器内部的 socket 网络封锁尚未进入；没有发生网络连接尝试。

## 3. 未观测结果

本次正式运行次数为 0，因此以下项目均为 `not_observed`，不得填造：

- 15 条场景的 Top-K；
- calibration/test 指标；
- 阈值选择和最终阈值；
- Recall@1、Recall@3、MRR；
- macro/micro Precision、Recall、F1；
- False Memory Rate 和 empty 正确率；
- semantic negative 普通 FP；
- 运行期跨玩家、当前 Episode、inactive、删除复活及其他安全计数；
- Fake/BGE 同口径差异；
- 两次排序、指标、向量与结果哈希重复性；
- 冷/热推理延迟、运行峰值内存与显存、结果磁盘大小。

预检没有发现 Gold、模型、配置或安全身份不一致，但预检通过不能替代正式执行证据。

## 4. 停止检查点

- 忽略目录文件：`results/m45_semantic_v2_launch_stop_20260810.json`
- SHA-256：`4C76415D1789D9CE5BEA4AA93E5418670C2976FD1AB732133791EFEFB88531AF`
- 正式 run 1 文件：未创建
- repeat run 2 文件：未创建
- 本地 BGE 加载：0
- 真实向量：0
- 自动重试：0
- 替代入口：未使用
- DeepSeek `/models`：0
- DeepSeek Chat：0
- 外部 Embedding API：0
- 网络请求：0
- 费用：0 CNY

原始停止检查点继续保存在 Git 忽略的 `results/`，仓库只记录本脱敏事实和 SHA。

## 5. 后续边界

M4.5-P2 仍未完成，M4.5-P3 和 M5 尚未开始。下一次正式运行需要新的明确授权，并在运行前明确采用已安装命令入口、等价模块入口，或先刷新项目 editable install；本轮不自行选择、不修复、不重跑。
