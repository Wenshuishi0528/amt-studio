# Task008 batch manifest

Task008 uses two files:

1. a human-readable `amt-batch-spec/v1` file containing authorized inputs,
   configurations, pinned models, repository/runtime bindings, ordered stages,
   and selected outputs;
2. a frozen `amt-batch-manifest/v1` file containing exact SHA-256 and byte-size
   records for every input, configuration, model, and source spec.

Freeze a spec on a Hyak CPU compute step after code and authorized inputs have
been synced. `sbatch --wait` only waits on the login node; hashing runs inside
the job's `srun` step:

```bash
AMT_ROOT=/mmfs1/gscratch/stf/$USER/amt-studio
sbatch --wait --parsable \
  --account=cpu-g2-stf --partition=cpu-g2 --qos=normal \
  --nodes=1 --ntasks=1 --cpus-per-task=2 --mem=8G --time=00:20:00 \
  --export=ALL,AMT_REPO_ROOT="$AMT_ROOT/repo",AMT_BATCH_SPEC="$AMT_ROOT/repo/configs/task008/smoke_spec.json",AMT_BATCH_MANIFEST="$AMT_ROOT/manifests/task008-smoke-v7.json" \
  --output="$AMT_ROOT/logs/amt-t008-freeze-%j.out" \
  --error="$AMT_ROOT/logs/amt-t008-freeze-%j.err" \
  "$AMT_ROOT/repo/slurm/29_task008_freeze.slurm"
```

Submit the manifest through a named resource profile:

```bash
python scripts/hyak/submit_batch.py \
  --manifest /mmfs1/gscratch/stf/$USER/amt-studio/manifests/task008-smoke-v7.json \
  --repo-root /mmfs1/gscratch/stf/$USER/amt-studio/repo \
  --cache-root /mmfs1/gscratch/scrubbed/$USER/amt-studio/batch-cache \
  --selected-root /mmfs1/gscratch/stf/$USER/amt-studio/selected \
  --index-root /mmfs1/gscratch/stf/$USER/amt-studio/indexes \
  --profile checkpoint-a40
```

Available profiles are:

- `priority-l40s`: dedicated STF L40S GPU for non-resumable validation;
- `checkpoint-a40`: requeue-enabled A40 checkpoint allocation;
- `cpu-smoke`: compute-node-only infrastructure validation without model work.

The submitter derives the array range from the frozen manifest. Each row uses a
cache key derived from its input, configuration, model, and stage definitions.
The cache key also binds the declared code revision, lexical virtualenv
launcher, resolved Python runtime, installed-package fingerprint, and exact
source-file hashes. Every Python entry point and `{repo_root}` executable must
be one of those frozen artifacts, and rows run only inside an active `srun`
step.
Completed stages are hash-verified and skipped after a retry. A stage may write
framework checkpoints to `{checkpoint_dir}`. Every declared raw and derived
output plus append-only attempt evidence is copied to persistent storage before
cache retention is applied; `selected_outputs` marks the important subset.
Retention inventories the complete shared cache root rather than only the
current manifest. A global retention lock and per-cache locks protect active
rows. Terminal incomplete caches are removable only after their attempt JSON
and logs are persistent, and new unique work is rejected while the shared root
is already over budget.

The tracked smoke spec contains only project-owned text fixtures. Its
`resume-once` row deliberately returns interruption code `75` on the first
attempt and succeeds on replay. It is infrastructure evidence, not a model
quality or GPU-performance benchmark.
