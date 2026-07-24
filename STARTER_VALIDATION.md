# Starter package validation

Validation date: 2026-07-23

The starter was checked in a Linux build environment. This validates repository mechanics, not Mac M4, Hyak, model installation, or transcription quality.

## Passed

- `PYTHONPATH=src python -m unittest discover -s tests -v`
  - 4 tests passed.
- `python -m compileall -q src tests`
- `bash -n` for every shell and Slurm script.
- Both JSON schema files parsed successfully.
- Actual ingest of `姫乃樹リカ - 硝子のキッス.mp3` through a path containing spaces and Japanese characters.
- Source SHA-256: `3464cdb850fdb1796c2cc48e0580640f04c39062eb236143e1ff0f2bdc0d1dbe`.
- Source metadata: MP3, 44.1 kHz, stereo, 265.639184 seconds.
- Canonical result: FLAC, 44.1 kHz, stereo, 265.614127 seconds.
- Re-initialization into the same non-empty project returned an error instead of overwriting data.
- Git ignore rules hide private audio and private project outputs while retaining their README/.gitkeep files.

## Not run

- `uv sync` with Python 3.12, because the build environment had no network access to download Python/build dependencies.
- Any third-party model.
- Any Mac MPS or Hyak CUDA operation.
- Any accuracy evaluation.

Task 001 must repeat the environment-specific checks on the user's Mac.
