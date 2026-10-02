# Executable package: V2.1 C/M recovery v3

## Required authorization state

The package is frozen and ready, but paid execution is not authorized by the instruction that created it. Obtain a new explicit authorization naming experiment `v2_1_slim_cm_recovery_20260920_03`, plan SHA-256 `3E711AC286AACFF25EFA2283588EB4D61755E31DD5A7CEED4402E77B5AE799E9`, C24+M12 scope, and the non-transferable C 6.00 / M 4.00 CNY caps.

## Verify and preflight

Run from `E:\yiwen-xinglu-agent\yiwen-npc` with `.venv\Scripts\python.exe`.

```powershell
(Get-FileHash -Algorithm SHA256 docs/evaluation/v2_design/revision_20260920/frozen_cm_recovery_20260920_v3.json).Hash
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_preflight --plan docs/evaluation/v2_design/revision_20260920/frozen_cm_recovery_20260920_v3.json
```

The hash must equal the frozen value above and preflight must return `READY`. Any mismatch stops execution before provider initialization.

## Paid commands after new authorization

```powershell
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_cm_recovery_20260920_v3.json --track C --confirm-paid-agent
.\.venv\Scripts\python.exe -m xuanyi_npc.evaluation.v21_execute --plan docs/evaluation/v2_design/revision_20260920/frozen_cm_recovery_20260920_v3.json --track M --confirm-paid-agent
```

Do not run G, append the old M item, change the frozen files, transfer budget, or selectively rerun a failed item.
