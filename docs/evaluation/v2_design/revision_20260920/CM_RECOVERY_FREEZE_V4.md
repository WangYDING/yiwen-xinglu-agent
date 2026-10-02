# V2.1 C/M recovery freeze v4

Experiment `v2_1_slim_cm_recovery_20260920_04` is frozen and awaiting new paid authorization.

Plan SHA-256: `E890FB2365BBB68C157EE246E52A07AFCF9ED3E21682579F6B4EDFD213C158C1`

Scope is a new complete C24+M12 paired batch. It preserves the original frozen C/M subsequence, pair membership, conditions, and three repeats. G is excluded and remains independently preserved in `v2_1_slim_first_round_20260920_02`; the old unpaired M request is excluded.

Budgets are non-transferable: C expected 3.70 CNY / hard cap 6.00 CNY; M expected 2.50 CNY / hard cap 4.00 CNY; total expected 6.20 CNY / hard cap 10.00 CNY.

The v4 delta adds fail-closed handling for pool initialization failures in addition to the v3 fixture, contract, evidence, usage, permission, trace, budget, and artifact-write gates. The v3 candidate and its evidence remain preserved but are superseded by v4.

Offline formal-entry evidence completed C24 and M12 in exact frozen order with 36 readable and exactly regradable artifacts, 72 confirmation events, and 72 controlled commits. The substitute made zero paid provider calls. This proves execution-chain reliability only and is not evidence of model capability, safety generalization, or memory benefit.
