# GitHub Public Repository Audit

## Executive verdict

Public code is worth publishing, but the current repository needs curation before the next public commit. Evaluation source/tests/manifests are high-value engineering evidence; dozens of phase reports and full raw artifacts are not. No high-confidence credential was found in tracked HEAD or 120-commit history, but the working tree contains large ignored local state/model/env data and untracked evaluation databases that must remain private.

This was a read-only audit of `git status`, `git ls-files`, `.gitignore`, requested directories, tracked blobs and all-history secret patterns. History scan covered 1,247 blobs; maximum historical blob was 158,576 bytes.

## Current repository facts

| Area | Current observation | Publication implication |
|---|---|---|
| `docs/` | 62 present files, ~0.60 MB; many P0–P5/E2–E13 and older tracked internal reports | Curate to 5–8 evaluation docs |
| `evaluation_results/` | 103 untracked files, ~2.02 MB; 19 run families; 4 SQLite DBs | Never publish wholesale |
| `src/xuanyi_npc/evaluation/` | 34 files, ~0.71 MB; new E9–E12 sources are untracked | Publish current relevant runners/harnesses |
| `tests/` | 207 files, ~4.52 MB | Publish tests; they demonstrate boundaries and reproducibility |
| `tools/experiments/data/evaluation/` | 15 present files, ~0.27 MB; new frozen configs untracked | Publish reviewed manifests/configs/fixtures |
| `runtime_data/` | 35,370 files, ~1.06 GB; saves, logs, SQLite, an embedded venv | DO NOT PUBLISH; already ignored |
| `runtime_models/` | 11 files, ~2.29 GB | DO NOT PUBLISH; already ignored |
| `.venv/` | 36,318 files, ~4.82 GB | DO NOT PUBLISH; already ignored |
| `.pytest_cache/`, `__pycache__/` | local generated caches | DO NOT PUBLISH; already ignored |

The worktree is heavily dirty with many tracked modifications/deletions and untracked frozen-evaluation work. Cleanup must be deliberate; do not stage everything with `git add .`.

## Evaluation publication categories

### A — MUST KEEP PUBLIC

- Production-relevant evaluation code: `src/xuanyi_npc/evaluation/agent_task_benchmark.py`, `cross_session_memory_exposure.py`, `reflection_ofat.py`.
- Paid runners are useful if reviewed for safe confirmation/budget behavior: `real_agent_memory_exposure_pilot.py`, `real_agent_reflection_ofat_pilot.py`.
- Tests: `tests/test_agent_task_benchmark.py`, `test_cross_session_memory_exposure.py`, `test_reflection_ofat.py`, the two real-pilot entry tests, P0–P5 regression tests, production Memory/Reflection tests.
- Frozen identity/config: `tools/experiments/data/evaluation/agent_task_benchmark_v1.json`, `cross_session_memory_exposure_v1.json`, Memory real-pilot config, Reflection CONTROL/ABLATION and real-pilot configs.
- Existing semantic holdout runner/contracts and frozen M4.5 fixtures remain valuable mechanism-level retrieval evidence.

### B — PUBLIC BUT CURATE

Recommended 5–8 core evaluation documents:

1. `docs/recruitment/evaluation_for_recruitment.md` — public entry point.
2. `docs/archive/evaluation/e6_post_e5_frozen_3x3_reliability_report.md` — final task reliability evidence.
3. A merged capability report from `docs/archive/evaluation/frozen_3x1_final_acceptance_report.md` + archived P0–P5.
4. A merged benchmark protocol from E2 + task benchmark audit/report.
5. A merged Memory report from E8–E10.
6. A merged Reflection report from E11–E13.
7. Optional `docs/evaluation/README.md` index with claim boundaries.

Keep E3 only as a compact historical comparison inside the summary. P0–P5, E2–E5, E7–E9, E11 and E13 are valuable internal provenance but too granular as separate public documents. E4/P1/P3/P4/P5 diagnostics and retries are internal debugging narrative. E10/E12 results belong in merged mechanism reports; full phase-by-phase files can remain outside the public branch or release bundle.

### C — OPTIONAL SAMPLE ARTIFACT

Do not upload all `evaluation_results/`. Publish only deliberately copied/redacted JSON samples:

- E6 `manifest.json` + `aggregate.json`, optionally one sanitized successful and one failure episode.
- E10 `manifest.json` + `aggregate.json` + three sanitized scenario `artifact.json` files, excluding `state/`.
- E12 `manifest.json` + `aggregate.json` + CONTROL `artifact.json`, excluding `state/` and SQLite.

Before publication, remove provider request IDs, system fingerprints, raw session/player IDs, absolute paths and any prompt/response payload. Keep hashes, bounded metrics, sanitized IDs and failure codes. Full artifacts add noise and expose operational metadata without improving the recruitment story.

### D — DO NOT PUBLISH

- `runtime_data/**` — real/local player/session saves, dialogues, logs, headers, SQLite and a nested virtualenv.
- `runtime_models/**` — ~2.29 GB model weights/cache.
- `.venv/**`, `.pytest_cache/**`, `**/__pycache__/**`.
- `evaluation_results/**/state/**`, specifically the four current `memories.sqlite3` files under E10/E12 pilots.
- Full dry runs, retries and diagnostics under `evaluation_results/agent_task_benchmark_dry_run*`, `post_p0`, `post_p1`, `post_p2*`, `post_p5_final`, `p3*`, `p4*`, `p5*`.
- Raw/full per-turn provider artifacts unless separately redacted.
- `.env` or any future credential file; only `.env.example` with placeholders is appropriate.

## Security and privacy findings

### Tracked HEAD

No tracked `.env`, key/pem, SQLite/database, log, model weight, runtime state, virtualenv/cache, IDE-private config or local Windows/Linux absolute path was found. `.env.example` and `tests/test_deepseek_adapter.py` contain explicit placeholders, not credentials.

No high-confidence `sk-…`, private-key or Bearer secret was found. Therefore **sensitive tracked credential files: NO**.

Tracked content that is not secret but needs public-product judgment:

- `src/xuanyi_npc/resources/cases/*.json` contains `hidden_information`, root causes and valid answers for six game cases. These are package data, not personal secrets, but they spoil cases and make benchmark answers inspectable; keep only if source-open cases are intentional, otherwise publish redacted/demo cases and review packaging impact.
- `docs/benchmarks/m5/m5_12_postfix_real_benchmark.json` is a ~100 KB detailed real-model record; merge metrics into a summary rather than expose every record.
- `docs/archive/evidence/model_runs/*.json` and large historical evaluation docs are tracked in HEAD but deleted locally. They are named sanitized, yet remain publication noise and should leave the public HEAD through a normal cleanup commit.
- `docs/evaluation/VERIFICATION.md` (~105 KB in HEAD, deleted locally) and the broad `docs/archive/**` tree are internal history, not a concise recruitment surface.

### Working tree / ignored data

Concrete non-public paths currently present include:

- `runtime_data/clinic/memories.sqlite3` and `runtime_data/clinic/{players,case_sessions,cooperative_agents,case_dialogues}/**`.
- `runtime_data/phase_b_smoke_v2/**`, `phase_c_*_smoke/**`, `phase_c_receipt_final_acceptance/**` with logs/state/SQLite.
- `runtime_data/phase_b_smoke_venv/**` (a complete nested environment).
- `runtime_models/bge-m3-142964af7e05/**`.
- `.venv/**`, `.pytest_cache/**`, `src/**/__pycache__/**`, `tests/__pycache__/**`.
- `evaluation_results/cross_session_memory_exposure_real_agent_pilot_v1/state/{positive_transfer,irrelevant_negative,empty_history}/memories.sqlite3`.
- `evaluation_results/cross_session_reflection_ofat_real_agent_pilot_v1/control/state/memories.sqlite3`.

The current `.gitignore` correctly covers these general classes, including `.env*`, DBs, logs, model formats, runtime data/models, virtualenvs, caches and IDE folders. One gap for publication workflow is that `evaluation_results/` is not globally ignored; do not change it automatically, but decide whether to ignore the root and whitelist curated samples elsewhere.

### Git history

All-history scan: 120 commits, 1,247 blobs, no private key, Bearer token or DeepSeek-style key; no forbidden `.env`, runtime data/model, database or weight path was found. Only `.env.example` appeared by name and contains a placeholder.

`SECRET HISTORY RISK: none detected.` No history rewrite is indicated by this audit. If a future manual review finds a real credential, deleting it from HEAD is insufficient: rotate it first, then use an approved history-cleaning process.

## 逐文件处置表

| Path | Currently Tracked | Category | Keep Public? | Reason | Recommended Action |
|---|---:|---|---:|---|---|
| `README.md` | YES | Public entry | YES | Recruiter landing page | KEEP |
| `docs/recruitment/evaluation_for_recruitment.md` | NO | A | YES | Evidence-bounded interview narrative | KEEP |
| `docs/archive/evaluation/e6_post_e5_frozen_3x3_reliability_report.md` | NO | B | YES | Final formal reliability result | KEEP_AND_RENAME |
| `docs/archive/evaluation/frozen_3x1_final_acceptance_report.md` + archived P0–P5 | NO | B | SUMMARY ONLY | Capability stabilization history | MERGE_INTO_SUMMARY |
| `docs/archive/evaluation/e2_recruitment_evaluation_freeze.md` + benchmark audit/report | NO | B | SUMMARY ONLY | Protocol identity without document sprawl | MERGE_INTO_SUMMARY |
| `docs/archive/evaluation/e3_frozen_3x3_statistical_evaluation_report.md` | NO | B | SUMMARY ONLY | Historical pre-E5 comparison | MERGE_INTO_SUMMARY |
| `docs/e4*`, P1/P3/P4/P5 diagnostics/retries | NO | B | NO | Internal debugging narrative | REMOVE_FROM_PUBLIC_REPO |
| `docs/e7*`–`docs/e10*` | NO | B | SUMMARY ONLY | Memory design/implementation/result chain | MERGE_INTO_SUMMARY |
| `docs/e11*`–`docs/e13*` | NO | B | SUMMARY ONLY | Reflection mechanism/result/boundary chain | MERGE_INTO_SUMMARY |
| `docs/archive/memory/PHASE_B_MEMORY_IMPLEMENTATION_REPORT.md` | NO | B | NO | Duplicates merged Memory story | MERGE_INTO_SUMMARY |
| `docs/PHASE_C_REFLECTION_*` | NO | B | NO | Duplicates merged Reflection story | MERGE_INTO_SUMMARY |
| `docs/archive/**` | YES | B/D | NO | Large internal historical surface | REMOVE_FROM_PUBLIC_REPO |
| `docs/evaluation/VERIFICATION.md` | YES, deleted locally | B | NO | Oversized internal verification record | REMOVE_FROM_PUBLIC_REPO |
| `docs/benchmarks/m5/m5_12_postfix_real_benchmark.json` | YES | C | NO | Detailed legacy real-model records | MERGE_INTO_SUMMARY |
| `docs/benchmarks/m5/m5_12_pre_post_summary.json` | YES | C | OPTIONAL | Compact legacy evidence | REVIEW_MANUALLY |
| `src/xuanyi_npc/evaluation/agent_task_benchmark.py` | NO | A | YES | Frozen production-equivalent benchmark | KEEP |
| `src/xuanyi_npc/evaluation/cross_session_memory_exposure.py` | NO | A | YES | Cross-session Memory harness | KEEP |
| `src/xuanyi_npc/evaluation/reflection_ofat.py` | NO | A | YES | Clean ON/OFF composition | KEEP |
| `src/xuanyi_npc/evaluation/real_agent_*_pilot.py` | NO | A | YES | Budgeted, confirmation-gated real pilots | REVIEW_MANUALLY |
| `src/xuanyi_npc/evaluation/semantic_holdout_*` | YES | A | YES | Frozen retrieval-quality benchmark | KEEP |
| `tests/test_agent_task_benchmark.py` | NO | A | YES | Benchmark identity/regression | KEEP |
| `tests/test_cross_session_memory_exposure.py` | NO | A | YES | Persistence/exposure/isolation evidence | KEEP |
| `tests/test_reflection_ofat.py` | NO | A | YES | Condition isolation evidence | KEEP |
| `tests/test_real_agent_*_pilot.py` | NO | A | YES | Paid confirmation/config gates | KEEP |
| `tests/test_phase_b_production_memory.py`, `test_m4_reflection_*` | NO/YES | A | YES | Production mechanism coverage | KEEP |
| `tools/experiments/data/evaluation/agent_task_benchmark_v1.json` | NO | A | YES | Frozen task identity | KEEP |
| `tools/experiments/data/evaluation/cross_session_*v1.json` | NO | A | YES | Frozen Memory/Reflection conditions | KEEP |
| `tools/experiments/data/evaluation/m45_*` | YES | A | YES | Paired retrieval fixtures/holdout identity | KEEP |
| `evaluation_results/**/aggregate.json` | NO | C | SELECTIVE | Compact measured results | REDACT |
| `evaluation_results/**/manifest.json` | NO | C | SELECTIVE | Reproducibility identity | REDACT |
| `evaluation_results/**/runs/**` | NO | C/D | SAMPLE ONLY | Too noisy; provider/session telemetry | REDACT |
| `evaluation_results/**/state/**` | NO | D | NO | Player/session state and SQLite | ADD_TO_GITIGNORE |
| `runtime_data/**` | NO | D | NO | Local saves, logs, DBs, nested venv | ADD_TO_GITIGNORE |
| `runtime_models/**` | NO | D | NO | Multi-GB model files | ADD_TO_GITIGNORE |
| `.venv/**`, caches, `__pycache__/**` | NO | D | NO | Generated local environment | ADD_TO_GITIGNORE |
| `src/xuanyi_npc/resources/cases/*.json` | YES | Product data | CONDITIONAL | Required runtime data but contains spoilers/answers | REVIEW_MANUALLY |
| `.env.example` | YES | Safe config | YES | Placeholder only | KEEP |

## Recommended public structure

```text
README.md
src/xuanyi_npc/
  agents/ application/ domain/ engine/ memory/ storage/
  evaluation/
tests/
tools/experiments/data/evaluation/
docs/
  architecture/
    README.md
    technical_overview.md
  evaluation/
    README.md
    capability_stabilization.md
    task_benchmark_and_results.md
    memory_evaluation.md
    reflection_evaluation.md
  recruitment/
    evaluation_for_recruitment.md
examples/evaluation_artifacts/
  e6_manifest.json
  e6_aggregate.json
  e10_sanitized_artifacts.json
  e12_sanitized_control.json
```

Keep raw artifacts outside Git or attach a curated archive to a release only after redaction. Avoid preserving an internal chronological diary in the public documentation tree.

## Final answers

**A. Should all evaluation docs be uploaded? NO.** Merge the phase trail into 5–8 public core documents. Keep raw audits privately or in a non-public archive.

**B. Should new evaluation source/tests/manifests be uploaded? YES.** Recommended exact roots/files are `src/xuanyi_npc/evaluation/{agent_task_benchmark,cross_session_memory_exposure,reflection_ofat,real_agent_memory_exposure_pilot,real_agent_reflection_ofat_pilot}.py`, corresponding `tests/test_*`, and `tools/experiments/data/evaluation/{agent_task_benchmark_v1,cross_session_memory_exposure_v1,cross_session_memory_exposure_real_agent_pilot_v1,cross_session_reflection_ofat_control_v1,cross_session_reflection_ofat_ablation_v1,cross_session_reflection_ofat_real_agent_pilot_v1}.json`.

**C. Are currently uploaded/tracked files unsuitable for a clean public repo? YES.** Concrete examples: `docs/archive/**`, `docs/evaluation/VERIFICATION.md`, `docs/archive/evidence/model_runs/*.json`, and `docs/benchmarks/m5/m5_12_postfix_real_benchmark.json`. They are not proven secret-bearing, but are excessive internal/history/raw-record material. Case JSONs also require an explicit spoiler/open-data decision.
