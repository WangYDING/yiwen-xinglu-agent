# 工具

- `release/`：分发、安装包、敏感文件和 Git 历史审计工具。
- `experiments/`：当前 BGE-M3 语义 Gold、Holdout、模型身份和诊断工具。它们不属于正式产品运行路径，也不进入分发包。
- `freeze_ce1_context_baseline.py`：创建不可覆盖、可从自带源码快照离线重建的版本化请求基线；已有 baseline ID 会被拒绝。
- `context_request_rebuild.py`：冻结进 snapshot 的离线请求/payload 重建入口。
- `freeze_context_baseline.py`：只保留用于识别并保护历史 CE-0 v1；已有文件绝不覆盖。
- `freeze_ce2a_context_fixture.py`：保护 CE-2A 版本化请求身份；拒绝覆盖已有版本，并要求从专项测试重建、审查后以新版本落盘。

正式游戏从 `yiwen-xinglu` 启动，不需要运行本目录脚本。
