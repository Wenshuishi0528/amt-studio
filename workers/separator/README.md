# Source-separation worker

Task 003 evaluates two pinned `audio-separator` presets:

- `vocal_quality_a`: a two-stem BS-Roformer candidate for vocal quality;
- `multistem_quality_a`: a four-stem `htdemucs_ft` candidate for vocals,
  drums, bass, and residual audio.

The model choice remains a benchmark hypothesis until the objective checks,
downstream note statistics, and user-confirmed listening notes are complete.

## Compute boundary

Do not install or run either model on the Mac. The Mac is only the front end
and may sync code, submit jobs, inspect manifests, hash files, and play short
review clips. Environment installation, model download, separation, and
MuScriptor inference must run on a Slurm GPU compute node. The login node is
only for transfer, `sbatch`, `squeue`, and light inspection.

The separator has its own uv environment and Linux lock file. It must not share
the root environment or the MuScriptor environment. HYAK jobs load the pinned
`weirdlab/ffmpeg/8.1` module because both the wrapper and objective metrics
require `ffmpeg` and `ffprobe`.

## 1. Set up the worker and download models

Choose persistent locations owned by the project, export them on the login
node, and submit the setup job:

```bash
export AMT_REPO_ROOT="/persistent/group/amt-studio/repo"
export SEPARATOR_MODEL_DIR="/persistent/group/amt-studio/weights/separator"
export SEPARATOR_MODEL_PROVENANCE="/persistent/group/amt-studio/manifests/separator-models.json"
export UV_BIN="/persistent/group/tools/uv"
export UV_PYTHON_INSTALL_DIR="/persistent/group/tools/python"
sbatch --export=ALL "$AMT_REPO_ROOT/slurm/15_separator_setup.slurm"
```

`scripts/hyak/setup_separator.sh` rejects direct login-node execution. The
Slurm job creates the isolated environments with `uv sync --locked`, downloads
both model families into `SEPARATOR_MODEL_DIR`, and records every downloaded
file's size and SHA-256 in `SEPARATOR_MODEL_PROVENANCE`.
It uses a uv-managed Python 3.12 runtime so native dependencies build against
an interpreter that includes its matching development headers.
The evaluated BS-RoFormer and Demucs candidates run through PyTorch CUDA. The
wrapper's unconditional ONNX import is intentionally satisfied by the pinned
CPU ONNX Runtime; this avoids coupling these PyTorch baselines to an unrelated
ONNX Runtime CUDA-major ABI.

Before inference, review that provenance and copy the verified files and hashes
into each preset's `expected_files` in `pins.json`. `run_baseline.py` refuses
to run when hashes are absent or when a cached model file differs.

## 2. Run both separation baselines

Export the private project and model paths, then submit:

```bash
export PROJECT_DIR="/persistent/group/amt-studio/projects/private/project-id"
export SEPARATOR_RUN_ID_PREFIX="separator-benchmark-001"
sbatch --export=ALL "$AMT_REPO_ROOT/slurm/16_separator_baseline.slurm"
```

The job runs the two presets sequentially with distinct immutable run IDs. By
default they are derived from the Slurm job ID; setting
`SEPARATOR_RUN_ID_PREFIX` makes an experiment label explicit. Existing run
directories are never overwritten. Each successful run contains raw FLAC
stems, diagnostics, objective audio metrics, the exact command, model hashes,
source hashes, and a run manifest under:

```text
<PROJECT_DIR>/runs/<run-id>/
```

Set `SEPARATOR_AUDIO` only when intentionally benchmarking a fixed authorized
excerpt instead of the project's canonical mix.

Checkpoint requeues are idempotent. A run with a succeeded manifest and
verified output hashes is skipped only when its input path/SHA-256, current
pins, model provenance, decoding configuration, and execution-source hashes
still match the submitted request. An incomplete, stale, or invalid immutable
run is retained as evidence, and the next attempt uses an `-attempt-N` suffix.

## 3. Check repeatability on a fixed excerpt

Submit the same authorized excerpt twice with distinct prefixes:

```bash
export SEPARATOR_AUDIO="$PROJECT_DIR/audio/excerpts/repeatability.flac"
export SEPARATOR_RUN_ID_PREFIX="separator-repeat-a"
sbatch --export=ALL "$AMT_REPO_ROOT/slurm/16_separator_baseline.slurm"
export SEPARATOR_RUN_ID_PREFIX="separator-repeat-b"
sbatch --export=ALL "$AMT_REPO_ROOT/slurm/16_separator_baseline.slurm"
```

After syncing the two small immutable run directories to the Mac, compare each
preset's decoded PCM. This step only decodes and hashes existing stems; it does
not run a model:

```bash
uv run python workers/separator/compare_repeatability.py \
  --run-a "$PROJECT_DIR/runs/separator-repeat-a-vocal-quality-a" \
  --run-b "$PROJECT_DIR/runs/separator-repeat-b-vocal-quality-a" \
  --output "$PROJECT_DIR/reports/separator-repeat-vocal.json"
```

Repeat the command for `multistem_quality_a`. The comparator rejects two paths
to the same run, mismatched inputs or configurations, duplicate manifest
records, and current stem files that no longer match their recorded hashes and
sizes.

## 4. Prepare the human listening review

Choose fixed canonical-timeline timestamps from the objective candidate
windows. Render at least three mix/vocal-A/vocal-B passages on the Mac:

```bash
uv run python workers/separator/prepare_listening_review.py \
  --mix "$PROJECT_DIR/audio/canonical/mix.flac" \
  --candidate "vocal_quality_a=$PROJECT_DIR/runs/separator-benchmark-001-vocal-quality-a" \
  --candidate "multistem_quality_a=$PROJECT_DIR/runs/separator-benchmark-001-multistem-quality-a" \
  --start 30 --start 90 --start 150 \
  --duration 12 \
  --output-dir "$PROJECT_DIR/reviews/separator-benchmark-001"
```

The package remains `awaiting_user` until a human records vocal deletion,
instrument leakage, artifacts, preference, and notes for every passage.
Automated timestamps are selection aids, not confirmed audible defects.
Candidate labels are restricted to safe, unique filename components and
cannot shadow the reserved `mix` reference.

## 5. Compare downstream vocal transcription

After both stem runs succeed, run the same MuScriptor configuration on the
canonical mix and the two vocal stems:

```bash
export MUSCRIPTOR_WEIGHT_PROVENANCE="/persistent/group/amt-studio/weights/muscriptor/provenance.json"
export DIRECT_MIX_AUDIO="$PROJECT_DIR/audio/canonical/mix.flac"
export VOCAL_A_AUDIO="$PROJECT_DIR/runs/separator-benchmark-001-vocal-quality-a/raw/stems/vocals.flac"
export VOCAL_B_AUDIO="$PROJECT_DIR/runs/separator-benchmark-001-multistem-quality-a/raw/stems/vocals.flac"
export MUSCRIPTOR_COMPARE_RUN_ID_PREFIX="muscriptor-voice-compare-001"
export MUSCRIPTOR_COMPARE_REPORT="$PROJECT_DIR/reports/muscriptor-voice-compare-001-comparison.json"
sbatch --export=ALL "$AMT_REPO_ROOT/slurm/17_muscriptor_stem_compare.slurm"
```

All three paths use beam size 4, the `voice` instrument constraint, prelude
forcing, and JSONL-only output. This is a descriptive candidate-note
comparison, not an accuracy result; accuracy requires the Task 006 human
reference. After the three runs succeed, the same job invokes `compare_amt.py`
with their immutable run directories. It verifies manifests, input lineage,
artifact hashes, and the shared decoding configuration before writing
descriptive event counts and cross-path agreement to
`MUSCRIPTOR_COMPARE_REPORT`.

The report path must be a safe path directly under the project's `reports`
directory. A matching completed report is reused; an existing corrupt or
mismatched report is preserved and the next attempt uses an `-attempt-N`
suffix. If `MUSCRIPTOR_COMPARE_REPORT` is omitted, its deterministic base is:

```text
<PROJECT_DIR>/reports/<MUSCRIPTOR_COMPARE_RUN_ID_PREFIX>-comparison.json
```

The job prints `amt_comparison_report=<path>` after verifying that the report
was created.

## Rights and listening limits

The `audio-separator` wrapper is MIT-licensed. That does not establish the
license, training-data authorization, or commercial-distribution rights for
every downloaded weight. The selected UVR and Demucs pretrained-weight terms
have not been independently verified. Keep weights and generated stems in
private research storage and out of distributable builds until that review is
complete.

Objective metrics may identify possible leakage, deletion, silence, clipping,
or reconstruction-error windows. Those timestamps are review candidates, not
confirmed audible defects. A user must perform the A/B listening check and
explicitly confirm the subjective notes before Task 003 can claim that
requirement is complete.
