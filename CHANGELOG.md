# Changelog

This project records changes by numbered research task until formal semantic
versions and releases begin. Dates and commit identifiers refer to the local
Git history.

## Unreleased

### Added

- Added `CHANGELOG.md` for task-level history.
- Added `HANDOFF.md` for the current Mac/Hyak operating boundary, verified
  artifacts, limitations, and the next-task entry point.

### Next

- Task 006: freeze human-reference excerpts and implement the evaluation
  harness before fusion or tuning.

## Task 005 — Beat map and canonical events — 2026-07-24

Commit: this task's final commit (`feat: complete beat and canonical events task 005`)

### Added

- Added the isolated, hash-pinned Beat This `1.1.0` worker, official `final0`
  checkpoint, Hyak setup job, and full-song Slurm baseline.
- Added versioned `amt-worker-request/v1` and `amt-worker-result/v1` contracts
  plus a common loader for current and immutable legacy worker results.
- Added canonical track, provenance, rhythm, tempo, meter, and experimental
  score-grid models and schemas.
- Added a format-1 performance MIDI exporter with original-second timing,
  variable tempo/meter events, separate candidate tracks, and atomic output.
- Added a canonical bundle builder that hashes every input result and refuses
  cross-project, cross-song, duplicate, tampered, or existing output paths.
- Added explicit cross-machine input relocation verification while retaining
  strict path matching by default.

### Verified

- Hyak A40 setup job `37621094` and final baseline job `37621507` completed.
- The final run preserved 567 beats, 143 downbeats, and 13,281 frames of raw
  beat/downbeat logits.
- The real canonical bundle retains four unranked candidate tracks and exports
  2,223 performance notes plus 2,223 separate experimental score-grid records.
- Mido `1.3.3` independently parsed and round-tripped all notes with maximum
  onset/offset error below 0.236 ms.
- `make check` passed with 110 tests.
- No beat, note, melody, score, fusion, or ranking accuracy claim was made
  without human references.

## Task 004 — Lead-vocal melody baselines — 2026-07-24

Commit: `b706d84` (`feat: complete vocal melody baseline task 004`)

### Added

- Added isolated, hash-pinned GAME v1.0.3 and Basic Pitch 0.4.0 workers.
- Added Hyak setup and Slurm baseline jobs for GAME GPU inference and Basic
  Pitch CPU inference.
- Added lineage-verified normalization, native-output preservation, and MIDI
  semantic checks for both workers.
- Added a four-path melody comparison covering GAME, Basic Pitch, MuScriptor on
  the selected vocal stem, and MuScriptor directly on the full mix.
- Added a synchronized three-passage review pack containing the mix and four
  piano-rendered candidate versions.

### Verified

- Full-song GAME and Basic Pitch runs completed on Hyak compute nodes.
- Four candidate sets share the same project identity and canonical-mix
  lineage.
- `make check` passed with 90 tests.
- No melody-accuracy or preferred-candidate claim was made without human
  references.

## Task 003 — Source separation — 2026-07-24

Commit: `71fdc0e` (`feat: complete source separation task 003`)

### Added

- Added an isolated, pinned Audio Separator worker and two source-separation
  candidate presets.
- Added repeatability, stem integrity, timeline, comparison, reuse, and
  listening-review tooling.
- Added controlled downstream MuScriptor voice runs on the mix and separated
  vocal stems.

### Selected

- Selected `vocal_quality_a` (BS-Roformer) as the default vocal stem after
  three-passage owner review.
- Retained `multistem_quality_a` (Demucs) as the fallback when separate drums,
  bass, and residual stems are required.

### Verified

- Full-song separation and downstream MuScriptor inference completed through
  Hyak Slurm allocations.
- Candidate A was preferred on all reviewed passages; candidate B was reported
  to have obvious accompaniment leakage and echo.
- `make check` passed with 45 tests.

## Task 002 — MuScriptor baseline — 2026-07-23

Commit: `5b5fc16` (`feat: complete MuScriptor baseline task 002`)

### Added

- Added the isolated MuScriptor 0.2.2 worker with exact package, source,
  model-revision, weight, and configuration pins.
- Added Hyak Slurm execution, run manifests, normalized canonical events,
  native JSONL/MIDI preservation, and local piano auralization.

### Verified

- Fixed-excerpt repeatability produced byte-identical native JSONL and MIDI.
- A full-song MuScriptor large beam-4 run completed on a Hyak A100 allocation.
- `make check` passed with 9 tests.

## Task 001 — Bootstrap and ingest — 2026-07-23

Commit: `570c29f` (`chore: bootstrap AMT Studio and complete task 001`)

### Added

- Added the dependency-light `amt_core` package, project CLI, schemas, model
  registry, task sequence, documentation, and Mac bootstrap tooling.
- Added private song ingest with immutable source hashing, deterministic
  44.1 kHz stereo FLAC canonicalization, and atomic project manifests.
- Added privacy boundaries for audio, projects, model weights, and generated
  private artifacts.

### Verified

- The initial Japanese, space-containing MP3 path ingested successfully.
- Repeated canonicalization produced the same canonical FLAC SHA-256.
- Non-empty project overwrite was refused.
