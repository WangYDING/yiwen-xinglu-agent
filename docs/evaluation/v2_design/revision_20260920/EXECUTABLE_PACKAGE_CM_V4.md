# Executable package: V2.1 C/M recovery v4

Paid execution requires a new explicit authorization naming experiment `v2_1_slim_cm_recovery_20260920_04`, plan SHA-256 `E890FB2365BBB68C157EE246E52A07AFCF9ED3E21682579F6B4EDFD213C158C1`, C24+M12 scope, and non-transferable hard caps C 6.00 CNY and M 4.00 CNY.

Run from `E:\yiwen-xinglu-agent\yiwen-npc`:

```powershell
(Get-FileHash -Algorithm SHA256 docs/evaluation/v2_design/revision_20260920/frozen_cm_recovery_20260920_v4.json).Hash
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_preflight --plan docs/evaluation/v2_design/revision_20260920/frozen_cm_recovery_20260920_v4.json
```

The hash must match and preflight must be `READY`. After new paid authorization only:

```powershell
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_cm_recovery_20260920_v4.json --track C --confirm-paid-agent
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_cm_recovery_20260920_v4.json --track M --confirm-paid-agent
```

Do not run G, reuse the old M item, alter frozen inputs, transfer budget, or selectively rerun failures.
