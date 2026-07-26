# Task 008: Hyak batch experiment system

Status: complete

## Objective

Scale reproducible baseline, ablation, and parameter experiments across authorized songs and excerpts.

## Requirements

- Implement idempotent run caching by input/config/model hashes.
- Add Slurm arrays from a manifest, not hard-coded paths.
- Support priority GPU and resumable checkpoint partitions.
- Trap interruptions and resume safe stages.
- Write central experiment indexes and sync selected results to Mac.
- Add resource use and failure-rate summaries.

## Acceptance criteria

- A failed/interrupted array can resume without duplicating completed runs.
- No heavy computation occurs on login nodes.
- Every output is traceable to a manifest row.
- Storage growth is bounded by retention rules.
- Important results survive scrubbed cleanup.

## Evidence

### Architecture and implementation

- ADR 0007 fixes `amt-batch-spec/v1`, frozen
  `amt-batch-manifest/v1`, content-addressed stage caching, persistent output
  archives with selected-output markers, and retention semantics.
- `src/amt_core/batch.py` validates every boundary; hashes inputs,
  configurations, models, relevant code, and ordered stage definitions;
  preserves the lexical virtualenv launcher while separately binding its
  resolved interpreter and installed-package fingerprint; requires every
  Python entry point to be a frozen repository artifact; rejects
  duplicate work and changed artifacts; atomically publishes
  hash-verified stages; preserves per-stage checkpoint directories; records
  commands, host/device, Slurm allocation, timestamps, wall time, peak RSS,
  and output hashes; removes unpublished temporary stage data after every
  failed/interrupted attempt; and refuses symlink outputs. The final
  `amt-batch-execution/v2` hardening runs stages against cache-local immutable
  copies of every declared input/config/model/code artifact and replaces
  inherited process state with a controlled environment plus only explicitly
  declared, cache-key-bound stage variables.
- `scripts/manage_hyak_batch.py` freezes manifests, runs one array row,
  summarizes the complete experiment, and applies explicit retention.
  `scripts/hyak/submit_batch.py` derives the array bounds from the manifest and
  supports `priority-l40s`, `checkpoint-a40`, and `cpu-smoke` profiles. It
  persists the array job ID before attempting to queue the dependent
  finalizer.
- `slurm/29_task008_freeze.slurm` moves manifest hashing into an active CPU
  `srun` step; the CLI rejects a Hyak login-node freeze.
- `slurm/30_task008_batch_array.slurm` rejects login-node/direct execution,
  launches through a required active Slurm step, forwards termination to the
  row runner through output hashing/publication, and exits with resumable
  status 75.
  `slurm/31_task008_batch_finalize.slurm` publishes an index before and after
  retention. Attempt records and their stdout/stderr logs are append-only
  under the persistent index, so post-retention summaries retain commands,
  resources, timestamps, logs, and output hashes.
- Every declared raw and derived output is copied and re-hashed in persistent
  storage before a scrubbed cache can be removed; `selected_outputs` remains
  an explicit importance marker. Cleanup inventories the complete shared
  cache root, serializes finalizers, skips active cache locks, can evict only
  terminal incomplete caches whose attempt evidence is persistent, and blocks
  admission of new unique work while the root is already over budget. Missing
  persistent archives are rebuilt from verified caches during finalization.
  `scripts/hyak/sync_from_hyak.sh` syncs frozen manifests, logs,
  indexes, and persistent output archives to the ignored local
  `hyak-results/` area.

### Frozen smoke and scheduler verification

- The final project-owned two-row smoke is `task008-smoke-v7`. It contains no
  audio or model inference and exists only to test orchestration. Frozen
  manifest SHA-256:
  `44c265b6f402798d4ed277fb2e7f94524747a432f5fac97f87061dc6f42de18d`.
- Freeze job `37712191` completed on CPU node `n3467`, so artifact and
  environment hashing did not run on a login node. Each row binds base code
  revision `86de5af`, eight exact code artifacts, the repository root, lexical
  virtualenv launcher, resolved Python SHA-256
  `7d43f6e86a6c6dd12005ec77eb2055f1be3f1bb3adedf8afe0a87973fa7371ce`,
  and environment fingerprint
  `663e821f910db6e8bb9802bd2b003b51b7656c9c45464a82f029c081afd30d8c`.
  The content cache keys are
  `bdf8a378f244009bf49b6a9ae60c59439d5746ee98bd2c609c89ca42a26514fe`
  (`resume-once`) and
  `53ea455ba53ffe5d89961d681284527e707b92604f47b4635843f41e8364dc39`
  (`cache-hit`).
- `sbatch --test-only` accepted both real GPU profiles: scheduler probes
  `37712211` for STF `gpu-l40s` and `37712212` for checkpoint A40. They are
  test-only scheduler estimates, not executed GPU jobs.
- First CPU array `37712213` deliberately interrupted row 0 at `infer` with
  exit `75:0`; row 1 completed. Finalizer `37712215` completed with `0:0`.
- Replaying the identical manifest as array `37712227` completed both rows.
  Row 0 recorded `prepare=cached` and `infer=completed`; row 1 recorded an
  entire-row `cached` hit with no stage execution. Finalizer `37712230`
  completed with exit `0:0`.
- The final index reports `2/2` rows completed, four attempts
  (`interrupted=1`, `completed=2`, `cached=1`), execution failure rate `1/3`,
  cache-hit rate `1/4`, `10.399` total recorded stage seconds, peak RSS
  `27,040 KiB`, and `117,938` bytes across all 14 directories in the shared
  cache root against a 64 MiB budget. The failure rate deliberately excludes
  cache hits from successful executions.
- Central experiment-index SHA-256:
  `766d07fedc4c360412b15cd724e7c0d635ebd519a7e259965703e0cdf37dfdb0`.
  Resource/failure-summary SHA-256:
  `81e0b02708e69bac727d4ec9c9962f30ba283c900a3236d8419b59f2145da6ca`.
- All four append-only attempt records, both output archives, and their
  ten attempt log files were persisted and synced to the Mac. The two
  selection-manifest SHA-256 values are
  `ce35e4edf054d530aef0b846da416ca12185aa1c5b7ccd97b75ccb660d9ee409`
  and
  `64f64ebcdbf72de72c9010495e7c5374a335ea260086d170b0b39fb05b964c0c`.
  Selected result
  SHA-256 values remain
  `0233a976490524022e22bd0c0e5f36a8447856604b86418c747a9b4aa82b1661`
  and
  `2cd5e42fe3a8e6234f325b352eef83a16073e95b2d21d7e78e6cf399235684eb`;
  the corresponding prepare-output hashes are
  `a6761372423a3e7e9ebc1048f4da14a03703532997a69ef71450aec858c382a4`
  and
  `5d816c055127de06e28b6f788128abcec7b7102fc4231f8838c901309abbefd6`.
  Interrupted-run `tmp/` is empty. The synced frozen manifest also loads on
  the Mac with `verify_source=False` despite its intentionally unavailable
  Hyak artifact paths.

### Acceptance and limitations

- The interrupted array resumed without re-running its completed stage, and
  the already complete row did not run again.
- All experiment work and manifest hashing ran on Slurm CPU compute nodes;
  login nodes performed only transfer, lightweight inspection, scheduler
  validation, and submission.
- Every completion and selected output resolves to one manifest row,
  authorization ID, cache key, code record, command, and artifact hash.
- Retention removes hash-verified completed caches only after complete
  persistent archives, and terminal incomplete caches only after persistent
  attempt JSON/log evidence. Global and cache locks protect active work; if
  the budget cannot be met safely, the preflight fails before deletion.
- The smoke proves infrastructure behavior, not throughput, GPU performance,
  transcription quality, or real-model checkpoint compatibility.
- The single final `/review` reported two P1 findings and one P2. Both P1
  findings are fixed by immutable artifact snapshots and controlled stage
  environments. Per the Task 008 stop instruction, the P2 root-level stray
  cache-file accounting edge case is documented but not expanded into more
  infrastructure work.
- Smoke v7 predates the final P1 hardening and remains the authoritative
  scheduler/resume/retention evidence. No extra Hyak smoke was run after the
  review; the v2 execution-contract regression coverage is local.
- `make check` passes all 216 tests. Ruff lint, JSON parsing, shell syntax,
  compile, and `git diff --check` also pass. Ruff format is not a repository
  acceptance gate.
