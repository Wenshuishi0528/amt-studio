# ADR 0007: Use frozen manifests and stage caches for Hyak batches

Status: accepted

## Context

Single-run Slurm scripts established reproducible baselines, but a plain array
of project paths cannot safely distinguish completed, interrupted, stale, or
configuration-changed work. Checkpoint resources may stop a job between
pipeline stages, and scrubbed storage cannot be the only copy of an important
result.

## Decision

Task008 freezes authorized batch specifications into
`amt-batch-manifest/v1`. Every row records exact input, configuration, model,
source-spec, Python-runtime, and code-artifact hashes plus a code revision. Its
cache key also binds the ordered stage commands. The Python record preserves
the lexical virtualenv launcher while separately hashing the resolved
interpreter and an installed-package fingerprint. Every Python entry point and
expanded `{repo_root}` file must be a frozen code artifact, the runtime must
match `{python}`, and execution must use the frozen repository root. Manifest
artifact hashing on Hyak runs in a Slurm CPU step, not on a login node.

Each stage writes into a temporary directory and becomes reusable only after
its declared outputs and completion marker are atomically published and
hash-verified. Framework-specific state may persist in the row's
`{checkpoint_dir}`. A retry re-verifies and skips completed stages, then
restarts only unfinished work. Unpublished stage directories are removed on
failure or interruption; checkpoint state is the only resumable mutable state.

Slurm array bounds come from the frozen manifest. Every declared raw and
derived output is copied to persistent storage before an explicit retention
policy may remove scrubbed cache entries; `selected_outputs` marks the
important subset without authorizing loss of the rest. Per-attempt records are
append-only with their stdout/stderr logs in the persistent index and feed
separate execution-failure, cache-hit, wall-time, memory, host, and device
summaries. Attempt telemetry is filtered by batch ID, manifest hash, row ID,
and cache key even when the content cache is shared across manifests. Cleanup
uses a global retention lock plus per-cache activity locks, computes a complete
plan across the shared content-addressed root, and fails before deletion when
it cannot meet the budget safely. A terminal incomplete cache becomes
removable only after every attempt and log is persistent; new unique work is
not admitted while the root is already over budget. Finalization rebuilds a
missing persistent archive from a verified complete cache.

Cache completion records bind only the content cache key and its exact payload,
not a batch ID, manifest hash, or row label. Identical work can therefore be
reused safely by a later frozen manifest, while each persistent selection
record binds that reuse to its own manifest row and authorization ID.
Synchronized manifests support structural offline loading when their absolute
Hyak artifact paths are intentionally unavailable.

## Consequences

- Changing input, configuration, model, relevant source code, or stage
  definitions produces a different cache key.
- Raw and derived outputs remain traceable after scrubbed cleanup through
  their frozen manifest, selection record, and append-only attempt index.
- Cache hits are not counted as successful executions when calculating the
  failure rate.
- Array submission identity is persisted before dependent-finalizer
  submission, so a finalizer scheduling failure cannot erase the running
  array's recovery metadata.
- A stage that cannot safely restart must provide its own checkpoint behavior
  or use a non-resumable priority profile.
- Batch rows require an active Slurm compute step, not merely a job ID.
- The generic batch layer stays model-agnostic and adds no third-party model
  dependency to `amt_core`.
