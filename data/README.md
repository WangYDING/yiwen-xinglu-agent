# 正式数据位置

可安装产品的正式病例、课程、成长、考试、权限、传承和验收资源位于：

```text
src/xuanyi_npc/resources/
```

它们必须随 wheel 安装，因此保留在 Python 包内作为唯一权威真源，不在顶层 `data/` 复制第二份。

顶层 `data/evaluation/` 与 `data/pilot/` 保留冻结评测输入、Gold 和历史 Pilot 快照；它们不是游戏规则真源。BGE、语义实验脚本和模型身份清单位于 `tools/experiments/`。
