# Task 004: Lead-vocal/main-melody baseline

Status: complete

## Objective

Build independent lead-vocal note candidates so main melody does not depend on one full-mix model.

## Candidate paths

- selected vocal stem + GAME;
- selected vocal stem + Basic Pitch;
- selected vocal stem + MuScriptor constrained to voice;
- direct full-mix vocal candidates from Task 002.

## Requirements

- Each worker has a pinned isolated environment.
- Native outputs and confidence/logits are preserved where available.
- Adapters emit canonical events on the original song timeline.
- No fusion or aggressive cleanup before baseline statistics.
- Produce synchronized piano renders for human inspection.

## Acceptance criteria

- At least three independent candidate event sets when technically possible.
- Event counts, fragmentation, pitch range, phrase gaps, and octave behavior are compared.
- At least three representative excerpts are selected for later reference annotation without tuning to them yet.
- A failure taxonomy draft identifies which paths appear complementary.

## Evidence

### Execution boundary

- The selected input stem is the Task 003 `vocal_quality_a` BS-Roformer vocal
  stem, SHA-256
  `e8500bdf08f761a117d167f1cd3852309440661b93ebadde8064f3f90189538a`.
- Its verified parent separator run is
  `separator-task003-full-d332b542-vocal-quality-a-attempt-1`; every stem-based
  melody manifest binds the parent manifest, output path, stem hash, project
  identity, and canonical mix SHA-256.
- Mac performed orchestration, manifest validation, descriptive statistics, and
  piano rendering only. GAME and Basic Pitch model inference ran through Hyak
  Slurm compute allocations.
- No candidate fusion, cleanup tuned to this song, quantization, or Task 005
  export was performed.

### Reproducible workers

- GAME is pinned to upstream v1.0.3 commit
  `475a8ee781fe8cca980b3b12fbe6c80c768a813a`, Python 3.12, Torch
  `2.8.0+cu129`, CUDA 12.9, Lightning 2.6.1, and the official
  `GAME-1.0-medium` release archive. The archive SHA-256 is
  `8c5b3e531e2905b935e664e2f533921cd637243770fab5282413bdb5051ca60c`
  and the model weight SHA-256 is
  `e9904159fb0646e1a352b9d2bc74615547cfa3e32d45c7464d440ac142846d93`.
  Upstream code is MIT; the official model files are
  CC-BY-NC-SA-4.0 and are restricted here to private non-commercial research.
- Basic Pitch is pinned to package `0.4.0`, upstream commit
  `9991303bba609a3b93089d13ec80d1d495083596`, Python 3.10, ONNX Runtime
  `1.23.2`, and `CPUExecutionProvider`. Its bundled ONNX SHA-256 is
  `2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec`.
  The package/code is Apache-2.0; no separate authoritative rights statement
  for the bundled weights or training data was verified in this task.
- Both workers have isolated `uv.lock` files. GAME setup job `37614010` and
  Basic Pitch setup job `37613596` completed successfully. The earlier Basic
  Pitch setup failure `37613496` is retained as diagnostic evidence of the
  missing `pkg_resources` compatibility dependency.

### Full-song baselines

- GAME job `37614448` completed on Hyak node `g3086` with an NVIDIA A100 80 GB.
  Run `game-task004-medium-d332b542` used the pinned Japanese medium-model
  decoding configuration and seed 3407. Inference took `164.445762 s`.
  Native CSV, TXT, and MIDI plus logs and canonical events are retained. The
  CSV and TXT contain the same 391 rows; the MIDI has exactly 391 note-ons.
  GAME v1.0.3 does not serialize confidence, logits, or velocity through this
  CLI, and that absence is explicit in the manifest.
- Basic Pitch job `37614317` completed on Hyak CPU node `n3101`. Run
  `basic-pitch-task004-onnx-d332b542-attempt-2` used
  `CPUExecutionProvider` and took `44.612667 s` for inference and decoding.
  Native note-event CSV, MIDI, and the raw note/onset/contour tensor NPZ are
  retained. The CSV and MIDI both contain exactly 486 note events.
- Both successful run manifests validate against current source hashes,
  model/package pins, input hashes, original-song timeline lineage, and every
  declared output hash.

### Four-path structural comparison

The private comparison report is
`projects/private/glass-kiss/reports/melody-task004-candidates-d332b542.json`
with SHA-256
`0f0a97cba58533ddbdd06b5f2ce00ed3095e2a0ece6a1a2d15252b65892d8242`.
It verifies that all four candidates belong to project `glass-kiss` and share
canonical mix SHA-256
`2c4ef424af20dd1eeb4c17b44ecb8da9a5f640ec26449e972ba4b45cb330ecde`.

| Candidate | Events | Short notes `<0.12 s` | Pitch min / median / max | Phrase gaps `>=1 s` | Polyphonic active time | Octave counts |
|---|---:|---:|---:|---:|---:|---|
| GAME on selected stem | 391 | 3.58% | 55.649 / 65.112 / 78.573 | 9 | 0.00% | O3 12, O4 371, O5 8 |
| Basic Pitch on selected stem | 486 | 0.00% | 57 / 67 / 90 | 18 | 12.03% | O3 8, O4 462, O5 12, O6 4 |
| MuScriptor voice on selected stem | 590 | 1.02% | 50 / 65 / 74 | 4 | 32.52% | O3 26, O4 553, O5 11 |
| MuScriptor voice on full mix | 756 | 4.50% | 44 / 66 / 81 | 8 | 16.05% | O2 5, O3 67, O4 608, O5 76 |

The draft failure taxonomy marks polyphonic output for later review in Basic
Pitch and both MuScriptor paths, and the 37-semitone direct-MuScriptor span for
possible register/octave review. GAME has no threshold-triggered structural
flag. These are review-routing heuristics, not error labels, quality rankings,
or evidence that any candidate is accurate.

### Pre-registered listening package

- The three passages were fixed before melody output inspection:
  `passage-01` at `4–16 s`, `passage-02` at `132–144 s`, and `passage-03` at
  `180–192 s`.
- Review directory:
  `projects/private/glass-kiss/reviews/melody-task004-d332b542`.
- Review manifest SHA-256:
  `02730d1d98e52135133847be5cd4e8e6298d555ce050a46d7a24c5032595f4f6`.
- Each passage contains the original mix and one piano rendering for each of
  the four candidates. All 15 WAV files validate as 44.1 kHz, stereo,
  16-bit PCM, exactly 529,200 frames (12 seconds), and every generated artifact
  is hashed.
- The pack is `awaiting_human_review`; it records
  `human_review_pending=true`, `accuracy_claimed=false`, and
  `task005_export=false`.

### Limitations and gate status

- No human reference note annotations were consumed, no precision/recall/F1
  was computed, and no preferred melody candidate was selected.
- Independent repeatability was not measured for GAME or Basic Pitch.
- Structural disagreement suggests useful annotation targets but does not yet
  prove that the models are complementary.
- Gate 2 remains unpassed. Human references and blind/held-out melody metrics
  belong to Task 006.
- Focused `/review` found no remaining P0–P2 issue, and `make check` passes
  with 90 tests.
