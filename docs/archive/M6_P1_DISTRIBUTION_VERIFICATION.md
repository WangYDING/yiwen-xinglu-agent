# M6-P1 发布工程与可分发安装验证

> 日期：2026-08-11
> 基线：`8780068e38432a3ace976e2dc1e820d9c8dc3fbb`
> 状态：本地通过；远程 CI 未运行；没有创建远程、Tag、Release 或发布。

## 1. 身份与授权

- 仓库本地 Git 配置为 `WangYDING <w17630630069@163.com>`；全局配置未修改。
- 基线之前 53 个提交继续使用 `wyd <wyd@localhost>`，没有 rebase、filter-repo、重签、`.mailmap` 或历史改写。
- wheel 元数据作者为 WangYDING，版本保持 `0.1.0`。
- wheel 同时携带 `LICENSE`、`NOTICE`、`CONTENT_RIGHTS.md` 和 `THIRD_PARTY_NOTICES.md`：Apache-2.0 仅适用于代码、测试和工程配置；叙事、病例、Campaign、文档与演示文案保留所有权。

## 2. 唯一运行资源

病例、Campaign 和运行必需配置已从仓库根 `data/` 迁至 `src/xuanyi_npc/resources/`，成为 source checkout 和 wheel 共用的唯一权威来源。`importlib.resources` 负责读取；既有 Path 型应用服务只在显式上下文中使用临时物化副本。

核心 wheel 只包含以下 6 个 JSON 运行资源：三个病例、`cross_episode_rules_v1.json`、DeepSeek Flash 的运行预算/价格策略快照，以及仅含 P4b/P4d 冻结 SHA 与公开结论的 M5 历史证据 manifest。

M4/M4.5 Gold、原始 Pilot、模型 manifest、真实结果、模型、向量、数据库和状态均不在 wheel 中。公开安装的 `xuanyi-m5-acceptance` 默认核对脱敏 manifest；若本地同时提供 P4b/P4d 原始文件，仍执行原逐字节 SHA 核对。

## 3. 构建环境与产物

| 项目 | 结果 |
|---|---|
| Python | CPython `3.12.3`，Windows |
| build / wheel / setuptools | `1.5.0` / `0.47.0` / `81.0.0` |
| wheel | `xuanyi_npc-0.1.0-py3-none-any.whl`，259,404 bytes，SHA-256 `568F95E365834FBDDB476AD0C83D91C69BE3FE93A665880A6A305B72EC2F4764` |
| sdist | `xuanyi_npc-0.1.0.tar.gz`，325,102 bytes，SHA-256 `278BE2EAA5BC6384C0C7231D99D42EE1AFFA8E1625A8FD37765AC88F0B71E6DE` |

执行 `python -m build --no-isolation` 时先生成 sdist，再从 sdist 构建 wheel。自动审计逐字节比较 wheel 与 sdist 中 6 个运行资源，并验证 4 个授权/归属文件完整。归档不含 `.env`、密钥、`results/`、`runtime_data/`、`runtime_models/`、`.git`、缓存、虚拟环境、模型权重、向量、数据库、实验 Gold 或本机绝对路径。

构建工具首次安装命令继承了本机预设的第三方镜像；发现后没有把该来源当作发布证据，而是立即用显式 `https://pypi.org/simple` 对相同精确版本执行强制重装。最终构建环境只认可这一官方 PyPI 重装结果，没有升级其他项目依赖。

## 4. 仓库外干净安装

在系统临时目录创建全新 CPython 3.12 虚拟环境，从本地 wheel 安装；核心依赖显式从官方 PyPI 获取。验证脚本从仓库目录之外运行，结果如下：

- `xuanyi-play --help`、`xuanyi-mcp-stdio --help`、`xuanyi-m5-acceptance --help` 全部成功；
- `xuanyi-play --state-dir <temp>` 使用包内三个病例进入 manual/off，无 API Key；
- 包内病例目录准确发现 `gray_hearth_inn`、`moon_well_echo`、`old_paper_umbrella`；
- `xuanyi-m5-acceptance` 使用公开 manifest 完整通过，启动 32 个工作进程，网络请求计数为 0；
- 官方 MCP Client 启动已安装的独立 stdio 子进程，准确发现 9 个冻结工具并正常关闭；
- 干净核心环境未安装 Torch、Sentence Transformers 或 BGE；
- `pip check` 通过。

```powershell
python -m build --no-isolation
python scripts/audit_distribution.py --dist-dir dist
python -m venv <temporary-directory>\venv
<temporary-directory>\venv\Scripts\python.exe -m pip install `
  --index-url https://pypi.org/simple `
  .\dist\xuanyi_npc-0.1.0-py3-none-any.whl
<temporary-directory>\venv\Scripts\python.exe `
  .\scripts\verify_installed_distribution.py
```

## 5. 测试、历史和 CI

- 全量离线测试：488 项通过。
- `pip check`、`git diff --check`、禁止跟踪文件检查：通过。
- 历史扫描基线：53 commits、590 个唯一 blob、最大 blob 158,576 bytes；真实 Key、Authorization、私钥、`.env`、原始结果、模型、数据库和运行状态命中均为 0。历史只包含公开决定保留的 `wyd@localhost` 身份；提交后会再次扫描新增提交。
- `.github/workflows/offline-ci.yml` 只配置 Windows Python 3.12：安装核心/dev 依赖、全量离线测试、构建与包内容审计、仓库外 wheel 验证、M5 验收、MCP stdio、`pip check`、历史/跟踪文件检查和 `git diff --check`。
- CI 不读取 `.env`，不调用 DeepSeek、BGE 或 Embedding API，不下载模型。依赖安装阶段允许访问 PyPI；测试阶段使用离线环境变量和项目自身门禁。

CI 文件只在本地完成语法与命令路径审查，尚未推送或在 GitHub Actions 实际执行。Linux、macOS、Python 3.11/3.13 也尚未验证。

## 6. 外部边界与下一步

- DeepSeek `/models`：0；Chat：0；Embedding API：0；BGE 加载：0；模型下载：0；费用：`0 CNY`。
- 只访问了包/许可证官方页面和 Python 依赖索引，没有发送玩家、Prompt、模型结果或项目数据。
- M6-P2 尚未开始。P2 可以在不改变发布工程边界的前提下重构首页、补架构图和脱敏演示素材。
- P4 之前仍禁止创建远程、推送、Tag、Release、GitHub 仓库或发布内容。
