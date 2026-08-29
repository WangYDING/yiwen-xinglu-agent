# 异闻行录

《异闻行录》是一套可审计的 Human-Agent Cooperative Game NPC 系统。玩家与自主 NPC 组成调查搭档，在六个古风志怪异案中共同观察、推理、质疑并处置异常。

产品不包含修习、课程、考试、师徒成长或传承系统。

## 启动

```powershell
python -m pip install -e ".[dev]"
yiwen-xinglu
```

服务只绑定 `127.0.0.1`。`xuanyi-clinic` 是同一入口的兼容命令；`xuanyi-mcp-stdio` 提供本地 MCP 集成。

## 当前能力

- 六个可独立完成的异案与跨案件 Campaign 连续性；
- 玩家建议、假设、质疑和证据解释影响 NPC 的 Goal、Plan 与行动；
- LLM 只提交结构化 proposal，`CaseEngine` 独占权威世界状态写入；
- 玩家隔离的长期记忆、语义检索、Reflection 与失败安全停止；
- JSON/SQLite 持久化、事件回放、断点恢复；
- M1–M5 自有评测：Cooperation、Planning、Memory、Reflection、Agent Benchmark。

## Evaluation

Frozen production-equivalent benchmark:

- 3 cases × 3 independent repeats
- Task Success: 8/9 (88.89%)
- Diagnosis Accuracy: 100%
- Treatment Accuracy: 88.89%
- Executed Safety Violations: 0
- Infrastructure Failures: 0

Cross-session Memory: real-Agent exposure proven; behavioral benefit not claimed.

Reflection: mechanism validated and real-model generation observed; robustness and behavioral benefit not claimed.

Protocol, results, and evidence boundaries: [Agent Evaluation](docs/evaluation/README.md).

## 目录

| 路径 | 作用 |
|---|---|
| `src/xuanyi_npc/agents` | Cooperative GameNPC 与 LLM Adapter |
| `src/xuanyi_npc/application` | 协作、规划、记忆、Reflection、Campaign 编排 |
| `src/xuanyi_npc/domain` | 严格领域契约与事件 |
| `src/xuanyi_npc/engine` | 确定性案件规则与状态提交 |
| `src/xuanyi_npc/clinic` | 本地 Web 产品入口 |
| `src/xuanyi_npc/memory` | 权威记忆投影、向量与安全检索 |
| `src/xuanyi_npc/resources/cases` | 六个正式异案 |
| `tests` | 当前产品回归与 M1–M5 评测 |
| `tools/experiments` | M4.5 语义记忆的离线 Gold/Holdout 工具 |

## 验证

```powershell
pytest
python -m build
python tools/release/audit_distribution.py --dist-dir dist
```

M4.5 材料继续保留，因为当前语义记忆仍使用其 Gold、Holdout、BGE-M3 模型身份和安全门禁。它们是有限工程证据，不代表生产成功率或真人收益。

更多内容见 [文档索引](docs/INDEX.md) 与 [首次启动说明](START_HERE.md)。
