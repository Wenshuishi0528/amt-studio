# Basic Pitch worker

Task004 uses Spotify Basic Pitch as an independent, instrument-agnostic
lead-vocal candidate generator. It normally receives the selected separator
vocal stem and writes canonical note events without tuning thresholds to the
reference song. Task 007C additionally permits the project's exact canonical
mix through the explicit `direct_canonical_mix` lineage for a fixed
instrumental development probe. Direct-mix output is labeled `other`, not
voice, because Basic Pitch does not infer instrument identity.

## Runtime boundary

- Python: 3.10 only.
- Package: `basic-pitch[onnx]==0.4.0`.
- Compatibility: `setuptools==80.9.0` retains the deprecated
  `pkg_resources` module still imported by Basic Pitch's resampy dependency.
- Serialization: bundled ICASSP 2022 ONNX model.
- Provider: upstream explicitly creates an ONNX Runtime
  `CPUExecutionProvider` session.
- Execution: HYAK Slurm CPU compute node only. Do not install or run this model
  on the Mac and never run it on a `klone-login` node.

The root environment remains model-independent. `scripts/hyak/setup_basic_pitch.sh`
creates the worker environment from `uv.lock`; submit it through
`slurm/21_basic_pitch_setup.slurm`.

## Fixed baseline

The runner explicitly records the upstream 0.4.0 defaults:

```text
onset threshold       0.5
frame threshold       0.3
minimum note length   127.70 ms
minimum frequency     unrestricted
maximum frequency     unrestricted
melodia trick         enabled
multiple pitch bends  disabled
MIDI tempo            120 BPM
```

No song-specific cleanup or threshold sweep occurs in Task004.

Submit one immutable run:

```bash
export AMT_REPO_ROOT=/absolute/path/to/repo
export PROJECT_DIR=/absolute/path/to/private/project
export BASIC_PITCH_AUDIO=/absolute/path/to/selected/vocals.flac
sbatch slurm/22_basic_pitch_baseline.slurm
```

For the Task 007C direct-mix development probe, set `BASIC_PITCH_AUDIO` to the
exact `audio/canonical/mix.flac`. Other arbitrary files remain rejected.

The run preserves all upstream files under `raw/native/`:

- `*_basic_pitch.mid`;
- `*_basic_pitch.npz` containing raw model tensors;
- `*_basic_pitch.csv` containing decoded native note events.

`normalized/events.jsonl` is the canonical source of truth. CSV velocity is
preserved as MIDI velocity, but it is not relabeled as calibrated confidence.
The raw note, onset, and contour model tensors in NPZ remain available for
later confidence research.

## Provenance and license boundary

`pins.json` records the published wheel hash, upstream Git commit, bundled ONNX
model hash, and fixed decoding parameters. Basic Pitch 0.4.0 is Apache-2.0
licensed. The bundled model is distributed with that package; a separate
authoritative training-data or standalone-weight rights statement has not been
established here, so this baseline remains private research evidence rather
than a redistribution claim.
