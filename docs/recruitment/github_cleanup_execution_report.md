# GitHub Recruitment Publication Cleanup — Execution Report

## 1. Files added

- Core public evaluation docs: `docs/evaluation/{capability_stabilization,task_benchmark_and_results,memory_evaluation,reflection_evaluation}.md`.
- Curated examples: `examples/evaluation_artifacts/README.md`, E6 manifest/aggregate, one success and one failure sample, E10 Memory sample, and E12 Reflection CONTROL sample.
- This execution report.

`docs/evaluation/README.md` was replaced with the current evaluation entry point. `docs/recruitment/evaluation_for_recruitment.md` remains the resume/interview-facing summary.

## 2. Files merged

- `capability_stabilization.md` condenses the initial frozen 0/3, P0–P5 root causes/generic fixes, and final 3/3 without the debugging diary.
- `task_benchmark_and_results.md` consolidates E2 protocol identity, E3 historical comparison, and the E6 current 3×3 reliability baseline.
- `memory_evaluation.md` consolidates E8–E10 protocol, implementation evidence, controls, and claim boundaries.
- `reflection_evaluation.md` consolidates E11–E13 deterministic proof, OFAT identity, real generation/repair, safe `no_write`, and root-cause boundary.

No new evaluation conclusion was created and no experiment was rerun.

## 3. Tracked files removed from the public surface

- `docs/benchmarks/m5/m5_12_postfix_real_benchmark.json` was copied byte-for-byte to ignored `private/research_archive/docs/benchmarks/m5/`, verified with SHA-256, then removed from its tracked public path.
- The worktree already marked `docs/archive/**`, `docs/evaluation/VERIFICATION.md`, legacy R6 evaluation reports, and other historical material deleted before this cleanup. Those existing user changes were preserved, not recreated or staged.
- Untracked P0–P5/E2–E13 source reports remain local and were not added to the public candidate surface.

## 4. Files intentionally kept private

- `evaluation_results/**`: complete manifests, aggregates, runs, retries, diagnostics, state, provider metadata, and four evaluation SQLite databases.
- `runtime_data/**`, `runtime_models/**`, `.venv/**`, caches, logs, saves, and local `.env`.
- `private/research_archive/**`: retained local research evidence removed from public paths.

No original evaluation artifact, runtime data, or runtime model was deleted.

## 5. Evaluation code selected

Static publication review selected:

- `src/xuanyi_npc/evaluation/agent_task_benchmark.py`
- `src/xuanyi_npc/evaluation/cross_session_memory_exposure.py`
- `src/xuanyi_npc/evaluation/reflection_ofat.py`
- `src/xuanyi_npc/evaluation/real_agent_memory_exposure_pilot.py`
- `src/xuanyi_npc/evaluation/real_agent_reflection_ofat_pilot.py`

The real-Agent pilots contain no credential or absolute local path, do not dump raw prompts/responses, require explicit `--confirm-paid-agent`, and load hard CNY budgets plus output-token caps from frozen configs. They are suitable to keep. This was a static audit only; no model or test was run.

## 6. Tests and manifests selected

Keep the corresponding benchmark, cross-session Memory, Reflection OFAT, and real-pilot tests, plus production Memory/Reflection regression tests. Keep the six formal frozen configs under `tools/experiments/data/evaluation/`:

- `agent_task_benchmark_v1.json`
- `cross_session_memory_exposure_v1.json`
- `cross_session_memory_exposure_real_agent_pilot_v1.json`
- `cross_session_reflection_ofat_control_v1.json`
- `cross_session_reflection_ofat_ablation_v1.json`
- `cross_session_reflection_ofat_real_agent_pilot_v1.json`

Existing M4.5 semantic Gold/Holdout fixtures remain public mechanism evidence. No retry/debug config was selected.

## 7. Artifact samples selected

The six JSON samples preserve hashes, bounded metrics, outcomes, sanitized sample IDs, telemetry, and failure codes. They remove provider request IDs, system fingerprints, raw player/session/memory IDs, timestamps, machine paths, prompts/responses, secrets, and hidden truth. All JSON files parse successfully.

The E10 sample includes positive, irrelevant-negative, and empty-history controls. The E12 sample records trigger/generation, grounding error, successful bounded repair, persisted receipt, safe `no_write`, and zero derived write without raw model content.

## 8. Case-spoiler decision

`src/xuanyi_npc/resources/cases/*.json` is production package data consumed by CaseEngine, so it was not removed or edited. Code evidence shows that `CooperativeRuntime` constructs `GameNPCAgentInput` from public case observations and `application/action_contract.py` projects only public legal actions. Projection/repository tests inject hidden sentinels and assert they are absent from Agent-facing Memory/view data; the benchmark runner also avoids direct CaseEngine/hidden-truth access.

The public task-benchmark doc now states that ground truth remains in CaseEngine resources while model-visible observations pass through the public-state boundary. Publishing source cases still reveals spoilers to human repository readers; that is an intentional open-source product-data tradeoff, not an Agent-input leak.

## 9. `.gitignore` changes

Added only two non-duplicate roots:

- `evaluation_results/`
- `private/`

Existing rules already cover `runtime_data/`, `runtime_models/`, SQLite/DB files, `.env*` except `.env.example`, virtualenvs, Python/pytest caches, model files, logs, and temp files. Curated examples live outside the ignored evaluation-results root.

## 10. README changes

The root README now has a compact Evaluation section with the E6 3×3 metrics, bounded Memory/Reflection claims, and a link to `docs/evaluation/README.md`.

## 11. Final security scan

- Curated JSON: valid; no provider/system identifiers, raw identity, absolute path, raw prompt/response, hidden truth, or credential pattern.
- Selected code/tests/manifests: no credential or absolute local path. One textual `raw_prompt` hit is a test assertion enforcing its absence from artifacts.
- Tracked generated/sensitive path scan: only `.env.example`, which contains a placeholder; no tracked SQLite/DB, runtime data/model, venv/cache, key/pem, log, or model weight.
- Oversized tracked files over 1 MiB: none found in the present worktree.
- Prior all-history audit found no credential and no forbidden sensitive path; history rewrite is not indicated.
- Sensitive/private material does exist locally (`.env`, databases, state, raw artifacts, models), but it is ignored and intentionally retained outside the public candidate set.

## 12. Current Git status summary

The repository was heavily dirty before this task. Final porcelain summary is 90 modified, 240 deleted, and 71 untracked entries, with **0 staged entries**. These counts include substantial pre-existing user work unrelated to this cleanup. Human review must select the intended public changes explicitly; do not use `git add .`.

PUBLIC DOCS CURATED: YES
PUBLIC EVALUATION CODE READY: YES
PUBLIC TESTS/MANIFESTS READY: YES
RAW ARTIFACTS EXCLUDED: YES
SANITIZED SAMPLE ARTIFACTS READY: YES
CASE HIDDEN TRUTH AGENT-ISOLATED: YES
SENSITIVE MATERIAL FOUND: YES
GIT HISTORY REWRITE REQUIRED: NO
READY FOR HUMAN DIFF REVIEW: YES
READY TO COMMIT: NO
