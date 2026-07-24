# Beat This worker

This isolated worker provides the Task005 beat/downbeat baseline. It never
imports Beat This, Torch, Torchaudio, NumPy, or Soxr into the root `amt_core`
environment.

## Verified pin

- package: `beat-this==1.1.0`;
- FLAC fallback: `soundfile==0.13.1`;
- upstream tag commit:
  `ad7974846029835307ba19a3d5cefbf40b243041`;
- checkpoint: official `final0`;
- post-processing: upstream minimal peak selection, no DBN;
- raw framewise beat/downbeat logits: retained with `--activations`;
- runtime target: Python 3.12, Torch/Torchaudio 2.8.0+cu129;
- code and published weights: MIT;
- training-data caveat: upstream notes that some training files have copyright
  or limited Creative Commons terms, so downstream use still needs a separate
  rights assessment.

Exact package and checkpoint hashes are recorded in `pins.json`; the complete
environment is locked in `uv.lock`.

## Hyak setup

Run only through Slurm:

```bash
sbatch slurm/25_beat_this_setup.slurm
```

The setup job creates `workers/beat_this/.venv` and downloads the checkpoint
into private persistent storage after verifying its size and SHA-256.

## Baseline

The baseline job consumes the project's canonical mix:

```bash
sbatch slurm/26_beat_this_baseline.slurm
```

It preserves:

- native `.beats` beat/downbeat timestamps;
- native `.npy` framewise logits;
- normalized `rhythm.json` with tempo/meter derivations and explicit
  uncertainty;
- request/result contracts, environment diagnostics, commands, logs, timings,
  source hashes, model hashes, and output hashes.

Raw rhythm output is never overwritten by tempo smoothing or score-grid
quantization.
