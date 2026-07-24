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
