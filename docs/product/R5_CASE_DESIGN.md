# R5 进阶病例设计

三个新病例都沿用通用病例 Schema 和同一 `MultiCaseEpisodeService`，没有病例专用 Python 分支。每案包含六项普通调查、八条公开线索、三个辨证候选、三个处置候选、固定提示、两条 Gold 调查顺序以及 `resolved / suppressed / worsened` 结局。

- 双灯巷与相悖证词：把冲突证词同时间、灯油、脚印和物件位置交叉核对，避免惩罚无辜证人。
- 雾渡客船与借寿灯：辨明快速压制与解除根因的区别，确认代价是否被转移给乘客。
- 归契古祠与无名碑：综合人物、契物、地点和炁息还原因果链；案件本身提供完整调查路径。

归契古祠以可信 Schema 声明六项必需调查要求。其中“核对被抹去的见证与原交接顺序”可由普通旧拓片调查，或权限过滤后加入的“溯契还因”调查满足。任一路径满足后，同组另一调查从公开选项消失；伪造调用会以 `investigation_requirement_already_satisfied` 零写入拒绝。未声明要求的五个病例在加载时规范化为单成员要求，原有诊断开放点不变。

对应的调查引导策略依次为 `cross_check_conflicting_testimony_v1`、`bounded_treatment_and_consequence_v1` 和 `integrated_causal_reasoning_v1`。这些策略只解释公开证据、Reflection、HintCard 和当前合法步骤，不改变病例答案或角色数值。
