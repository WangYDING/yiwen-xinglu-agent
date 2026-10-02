# Preserved stop record classification

The original result directory `evaluation_results/v21/v2_1_slim_first_round_20260920_02` is unchanged.

- G: keep as the independent observed result (18 attempted, 17 strict successes, one ordinary model max-turn failure). It is not scheduled in the recovery batch.
- C: all 24 artifacts are classified as protocol/implementation aborts caused by `campaign_rule_invalid` before provider initialization. They are not Agent capability failures and are not reused in the new pairs.
- M: the first MV01/M0 request reached the provider, but the episode artifact failed the old scenario-ID contract. Its request-level detail cannot be recovered because the old request ledger is absent. The missing fields remain missing; no request row or per-request cost is inferred from the aggregate budget snapshot. The old item is not combined with the new M pairs.
- Remaining old M entries: 11 unstarted.

The recovery batch is a new immutable C24+M12 batch. It does not append to or overwrite the old batch.
