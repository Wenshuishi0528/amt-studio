# Hyak Klone runbook

## Roles

Use the Mac for code, orchestration, inspection, annotation, and the final application. Use Hyak for large-model inference, batch experiments, sweeps, and training.

## Storage layout

The scripts default to:

```text
Persistent: /gscratch/stf/$USER/amt-studio
Temporary:  /gscratch/scrubbed/$USER/amt-studio
```

Verify these paths with `hyakstorage` and your actual access before relying on them. Keep code, manifests, important results, environment definitions, and selected checkpoints in persistent storage. Use scrubbed for temporary audio, model caches, decompressed datasets, and intermediate arrays. Sync valuable results back to the Mac.

## Never compute on login nodes

Login nodes are for SSH, file transfer, repository updates, scheduler commands, and light inspection only. Submit `sbatch` jobs or use a Slurm allocation.

## Initial setup

On the login node:

```bash
bash scripts/hyak/bootstrap_hyak.sh
```

From the Mac:

```bash
bash scripts/hyak/sync_to_hyak.sh
```

## GPU smoke test

```bash
sbatch slurm/00_gpu_smoke_test.slurm
squeue -u "$USER"
```

Inspect the deterministic log directory rather than relying only on scheduler stdout.

## Baseline job

After the MuScriptor worker is installed and the private project is synced:

```bash
PROJECT_DIR=/gscratch/stf/$USER/amt-studio/projects/private/glass-kiss \
  sbatch --export=ALL,PROJECT_DIR \
  slurm/10_muscriptor_baseline.slurm
```

## Checkpoint partitions

Checkpoint jobs can be interrupted and requeued. Every batch or training command must:

- write atomically;
- skip verified completed artifacts;
- resume from checkpoints;
- use stable run IDs;
- trap termination signals where the framework supports it;
- never treat a partially written output as complete.

Use priority STF GPU partitions for non-resumable validation runs when available. Use checkpoint resources for large resumable batches and sweeps.

## Sync results back

```bash
bash scripts/hyak/sync_from_hyak.sh
```

The sync scripts exclude model caches, environments, and large temporary stems by default. Adjust include/exclude rules deliberately.

## Manifest-driven batch experiments

Task008 batch runs are frozen from `amt-batch-spec/v1` into
`amt-batch-manifest/v1`. The frozen manifest records every input,
configuration, model, runtime-environment, and code artifact hash. Use
`slurm/29_task008_freeze.slurm` as shown in `configs/task008/README.md`; the
manager rejects artifact hashing directly on a Hyak login node. Submit the
result with
`scripts/hyak/submit_batch.py`; the submitter derives the Slurm array range from
the manifest rather than a separate path list.

Named profiles keep resource intent explicit:

- `priority-l40s` uses the STF L40S partition for short validation work;
- `checkpoint-a40` uses requeue-enabled A40 checkpoint resources;
- `cpu-smoke` validates orchestration without model inference.

Each cache entry is content-addressed. Completed stages have atomically written
hash manifests and are skipped only after re-verification. Interrupted stages
restart with their persistent `{checkpoint_dir}`; unpublished temporary stage
directories are removed. Every declared raw and derived output is copied to
persistent storage before the declared scrubbed-cache retention budget is
applied, while `selected_outputs` marks the important subset. Attempt evidence
and its stdout/stderr logs are append-only under the persistent index, so the
finalizer can rewrite the central experiment index and resource/failure
summary after cache cleanup without losing history. Each row preserves its
virtualenv launcher, binds the resolved interpreter and installed packages,
requires a frozen repository Python entry point, and runs only inside an
active `srun` step. Retention reconciles missing persistent archives, uses
global/per-cache locks, protects active work, safely removes terminal
incomplete caches only after their evidence is persistent, and applies the
budget to the entire shared cache root. New unique caches are blocked while
that root is already over budget. The submitter persists the array job ID
before requesting its dependent finalizer.

`scripts/hyak/sync_from_hyak.sh` syncs frozen manifests, logs, indexes, and
persistent output archives. It does not download the full scrubbed cache.
Use `load_batch_manifest(path, verify_source=False)` to inspect a synchronized
manifest on the Mac when its recorded absolute Hyak paths are offline.

## Diagnostics to record

Every Slurm job should record:

```bash
hostname
nvidia-smi
python --version
uname -a
env | sort | grep -E 'SLURM|CUDA|AMT|HYAK'
git rev-parse HEAD
git status --porcelain
```

Do not put secrets in logs.
