# GAME worker

Task004 uses OpenVPI GAME as the singing-voice-specific candidate path. It
receives the selected separator vocal stem and emits native CSV, TXT, and MIDI
plus canonical events on the original mix timeline. Direct full-mix inference
is intentionally refused by this worker.

## Pinned runtime and model

- Upstream source: GAME `v1.0.3`, commit
  `475a8ee781fe8cca980b3b12fbe6c80c768a813a`.
- Model: official `GAME-1.0-medium` archive from the `v1.0.0` release.
- Python: 3.12.
- Torch: `2.8.0+cu129`; CUDA runtime: 12.9.
- Lightning: 2.6.1.
- Execution: HYAK Slurm A40 compute node only. Never run inference on the Mac
  or a `klone-login` node.

`pins.json` records the source commit, archive size/hash, every extracted model
file size/hash, runtime versions, and decoding parameters. The root project
environment is read-only during GAME setup; only `workers/game/.venv` is
rebuilt.

## Setup

The first setup verifies the official archive and reports its extracted file
inventory. That exact inventory must be copied into `pins.json`. A second setup
then refuses any archive or extracted-file mismatch and writes a provenance
record with `expected_files_were_pinned=true`.

```bash
export AMT_REPO_ROOT=/absolute/path/to/repo
export GAME_ASSET_ROOT=/absolute/path/to/private/persistent/game-assets
sbatch slurm/23_game_setup.slurm
```

The persistent asset directory contains the pinned upstream checkout, archive,
model files, and `model-provenance.json`; none belongs in Git.

## Fixed Task004 baseline

The project wrapper seeds Python, NumPy, and Torch with `3407`, then invokes the
official extraction path with:

```text
language             ja
batch size           4
workers              0
segment threshold    0.2
segment radius       0.02
t0                    0.0
diffusion steps      8
estimate threshold   0.2
MIDI tempo           120 BPM
pitch format         numeric float
pitch rounding       disabled
```

No song-specific threshold sweep, note deletion, fusion, or octave correction
occurs in Task004. GAME uses stochastic diffusion decoding; recording a seed
improves repeatability but is not a claim of byte-identical CUDA determinism.

Submit one immutable run:

```bash
export AMT_REPO_ROOT=/absolute/path/to/repo
export PROJECT_DIR=/absolute/path/to/private/project
export GAME_AUDIO=/absolute/path/to/selected/vocals.flac
export GAME_MODEL_PROVENANCE=/absolute/path/to/model-provenance.json
export GAME_RUN_ID=game-task004-medium
export GAME_SEED=3407
sbatch slurm/24_game_baseline.slurm
```

Native `*.csv`, `*.txt`, and `*.mid` files are retained under `raw/native/`.
The numeric CSV is normalized separately into `normalized/events.jsonl`.
The official CLI does not expose calibrated per-note confidence or logits, so
canonical confidence remains absent rather than being invented.

## License boundary

The pinned GAME source is MIT licensed. The official released model files are
CC-BY-NC-SA-4.0, so this worker and its weights remain private,
non-commercial research evidence. Do not redistribute the model archive or
claim commercial deployment rights from this setup.
