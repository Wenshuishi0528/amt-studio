# Task 005: Beat/downbeat map and canonical project model

Status: complete

## Objective

Finalize the worker request/result contract, canonical events, tempo/meter maps, and exporters without changing the raw baseline results.

## Requirements

- Integrate Beat This as an isolated worker.
- Store raw beat/downbeat timestamps.
- Implement versioned worker request and result manifests.
- Implement canonical note, tempo, meter, track, and provenance models.
- Add performance MIDI export.
- Add a first score-grid experiment, but keep score timing separate.
- Round-trip tests through at least one independent MIDI parser.

## Acceptance criteria

- All baseline workers normalize through one interface.
- Canonical events validate and retain source provenance.
- Performance MIDI exports without time drift.
- Raw versus quantized outputs are distinguishable.
- Tempo/downbeat uncertainty is recorded.

## Evidence

- Upstream and runtime pins:
  - Beat This `1.1.0`, upstream commit
    `ad7974846029835307ba19a3d5cefbf40b243041`;
  - PyPI wheel SHA-256
    `3f2b2d1e027c6dac380bf80c71555e3c28a4036a7f1af20129a945915a72a645`;
  - official `final0.ckpt`, 81,058,141 bytes, SHA-256
    `8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331`;
  - isolated Python 3.12 worker with Beat This `1.1.0`,
    SoundFile `0.13.1`, Torch/Torchaudio `2.8.0+cu129`, and CUDA 12.9.
- Hyak compute evidence:
  - setup job `37621094` completed on an NVIDIA A40 with exit `0:0`;
  - the first baseline job `37621020` was preserved as a failed run after
    exposing the missing FLAC fallback dependency;
  - final baseline job `37621507` completed on an NVIDIA A40 with exit `0:0`;
  - final immutable run:
    `beat-this-task005-final0-d332b542-attempt-4`;
  - inference wall time was 19.565915 seconds with peak child RSS
    1,405,800,448 bytes;
  - the canonical input SHA-256 was
    `2c4ef424af20dd1eeb4c17b44ecb8da9a5f640ec26449e972ba4b45cb330ecde`.
- Rhythm artifacts:
  - 567 raw beat timestamps and 143 raw downbeat timestamps were preserved;
  - 13,281 frames of two-channel 50 Hz raw logits were preserved with zero
    expected-frame delta;
  - the observed adjacent-interval median was 136.363636364 BPM;
  - event confidence is explicitly `null` because the CLI does not provide
    calibrated per-event confidence;
  - the raw-logit reference is portable run-relative path
    `raw/native/mix.npy`;
  - local tempo uncertainty, raw-logit provenance, and inferred/defaulted meter
    status are recorded instead of presented as accuracy.
- Contracts and canonical output:
  - `amt-worker-request/v1` and `amt-worker-result/v1` validate new workers,
    while immutable Task 002–004 results load through the same interface;
  - canonical note, track, rhythm, tempo, meter, provenance, and experimental
    score-grid models are implemented and schema-backed;
  - the real private bundle is
    `projects/private/glass-kiss/exports/canonical-task005-d332b542/`;
  - it retains four separate candidate tracks containing 391 GAME, 486 Basic
    Pitch, 590 stem-MuScriptor, and 756 direct-MuScriptor notes;
  - `performance.mid` contains all 2,223 performance notes, while
    `score-grid-experiment.jsonl` contains 2,223 separate derived records;
  - no candidate fusion, ranking, notation-quality claim, or transcription
    accuracy claim was made.
- Independent validation:
  - all three bundle output sizes and SHA-256 values match
    `bundle_manifest.json`;
  - Mido `1.3.3` independently parsed the format-1 MIDI, all four tracks, and
    all 2,223 note pairs;
  - maximum external onset/offset round-trip error was
    `0.00023577097474003494` seconds;
  - `make check` passes with 110 tests;
  - focused review and `git diff --check` passed before the Task 005 commit.
