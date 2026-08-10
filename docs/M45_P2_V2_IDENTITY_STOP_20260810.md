# M4.5-P2 v2 入口修复后身份门禁停止记录

## 1. 结论

- **执行 HEAD**：`f573e036d456e54e5c770014e49f7af66aa32ba9`
- **冻结基线参数**：`b78033099663464bf3d7790c6fef5d4b973dc692`
- **日期**：2026-08-10
- **入口修复**：成功
- **正式 run1**：在模型加载前被冻结身份门禁拒绝
- **run2**：未启动
- **M4.5-P2 判定**：再次因工程条件停止

本轮没有修改、reset、checkout 或改写历史。`b780330..f573e03` 之间继续只有前一次启动停止记录和当前状态文档，评测器、Gold、配置、Adapter 和产品代码均未变化。

## 2. 离线入口修复

在仓库根目录使用项目 Python 执行：

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
```

同时设置 `PIP_NO_INDEX=1` 和 `PIP_DISABLE_PIP_VERSION_CHECK=1`。pip 只从本地仓库构建 editable wheel，没有解析依赖、升级包、下载模型或访问索引；系统 Python 和 Anaconda 未使用。

结果：

- `.venv/Scripts/xuanyi-semantic-memory-eval.exe` 已生成；
- 文件大小 `108,388` 字节；
- SHA-256：`FF6C0EE3CAF015F64CD84BF5B3D664CC06407E17F17C993017B54B64E85DF7A2`；
- 显式 `--help` 返回冻结的三个必需参数；
- `--help` 没有加载 BGE、生成向量或写结果；
- `.venv` 继续被 Git 忽略，工作树未因安装变化。

## 3. run1 身份停止

入口验证后，使用授权给出的参数原样启动：

```powershell
.\.venv\Scripts\xuanyi-semantic-memory-eval.exe `
  --run-id m45_p2_v2_run1_20260810 `
  --freeze-commit b78033099663464bf3d7790c6fef5d4b973dc692 `
  --output .\results\m45_p2_v2_run1_20260810.json
```

评测器在 `run_local_bge` 的第一项门禁检查中发现当前 HEAD `f573e03...` 不等于传入冻结提交 `b780330...`，返回：

```text
RuntimeError: semantic Pilot requires the exact clean freeze checkpoint
```

该检查发生在 Gold 加载、Torch 导入、CUDA 初始化、模型加载、Embedding 和结果写入之前。本轮没有改变 `--freeze-commit`，没有把文档-only 后继提交当成精确冻结提交，也没有创建临时 worktree、切换 HEAD、修改评测器或改用模块入口。根据授权门禁，立即停止且不执行 run2。

## 4. 未观测指标

正式 Embedding 运行次数为 0，以下全部为 `not_observed`：

- 15 条场景 Top-K；
- calibration/test 指标与阈值选择；
- Recall@1、Recall@3、MRR；
- macro/micro Precision、Recall、F1；
- False Memory Rate、empty 正确率和语义 FP；
- 跨玩家、当前 Episode、superseded、invalidated、hard-deleted/删除复活等运行期安全计数；
- Fake/BGE 排序差异；
- 两次运行的排序、指标、向量容差与结果哈希；
- 冷/热延迟、峰值内存、峰值显存和正式结果磁盘占用。

不能依据此前预检或 P1 烟雾填补这些正式指标。

## 5. 停止检查点与外部边界

- 忽略目录检查点：`results/m45_p2_v2_identity_stop_20260810.json`
- SHA-256：`628C24576585ACBFF2DFB6035F326FEA6B207442F0C50D73ECA01B9ADD1B0D19`
- 大小：`1,230` 字节
- run1 正式结果：未创建
- run2 正式结果：未创建
- BGE 加载：0
- 向量：0
- 自动重试：0
- 网络请求：0
- DeepSeek `/models`：0
- DeepSeek Chat：0
- 外部 Embedding API：0
- 费用：0 CNY

M4.5-P2 仍未完成，不能判断真实语义质量或 P3 准入。下一次运行需要新的明确授权，同时必须解决“当前执行 HEAD”与评测器“精确冻结 HEAD”语义冲突；本轮不自行选择解决方式。M4.5-P3 与 M5 尚未开始。
