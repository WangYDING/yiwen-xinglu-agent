# R5 进阶病例设计

三个新病例都沿用通用病例 Schema 和同一 `MultiCaseEpisodeService`，没有病例专用 Python 分支。每案包含六项普通调查、八条公开线索、三个辨证候选、三个处置候选、固定提示、两条 Gold 调查顺序以及 `resolved / suppressed / worsened` 结局。

- 双灯巷与相悖证词：把冲突证词同时间、灯油、脚印和物件位置交叉核对，避免惩罚无辜证人。
- 雾渡客船与借寿灯：辨明快速压制与解除根因的区别，确认代价是否被转移给乘客。
- 归契古祠与无名碑：综合人物、契物、地点和炁息还原因果链；普通路径完整，传承路径只减少一次核对成本。

对应课程依次为 `cross_check_conflicting_testimony_v1`、`bounded_treatment_and_consequence_v1` 和 `integrated_causal_reasoning_v1`。课程只解释公开证据、反思、HintCard 和固定下一步，不改变病例答案与成长数值。
