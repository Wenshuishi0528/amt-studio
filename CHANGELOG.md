# Changelog

This project records changes by numbered research task until formal semantic
versions and releases begin. Dates and commit identifiers refer to the local
Git history.

## Task 006 — Human references and formal evaluation — 2026-07-25

Commit: this task's final commit (`feat: complete reference evaluation task 006`)

### Added

- Added `CHANGELOG.md` for task-level history.
- Added `HANDOFF.md` for the current Mac/Hyak operating boundary, verified
  artifacts, limitations, and the next-task entry point.
- Added the Task 006 benchmark freeze, human-reference sealing,
  note/timed-event metrics, confidence/coverage reporting, correction-effort
  logging, schemas, and tamper-detecting evaluation outputs.
- Added frozen-audio revalidation, verified worker/canonical-mix lineage,
  single-target-track scoring, annotation-seed exclusion, correction-log
  binding, hashed evaluation run manifests, and an acoustic-piano SoundFont
  preset check for listening reviews.
- Added pre-inspection blind candidate-set sealing, immutable annotation-seed
  binding, worker-verified seed ingestion, mandatory correction review
  evidence, full top-line derivation manifests, and a hash-plus-exact-preset
  allowlist for the acoustic-piano review asset.
- Added semantic seed-copy exclusion, reviewed-artifact hash enforcement,
  frozen-duration correction validation, boundary-offset censoring, and
  lineage-preserving separator-stem normalization recovery.
- Hardened the evaluation harness after focused review: scored-window semantic
  seed fingerprints, minimum-cost maximum matching, honest unavailable
  confidence output, masked high-agreement diagnostics, and boundary-bound
  offset censoring.
- Froze a replacement different-artist blind project before inference,
  predeclared its fixed candidate set, and submitted the complete Hyak Slurm
  dependency chain without inspecting candidate quality.
- Synced and hash-verified the completed checkpoint-A40 formal blind chain and
  its four-candidate preinspection seal.
- Added a Task 006 single-seed review command that binds the benchmark, seed
  policy, candidate seal, worker artifacts, frozen windows, and approved
  acoustic-piano SoundFont without exposing the three candidates that remain
  eligible for primary metrics.
- Allowed a candidate-corrected blind evaluation to consume exactly the sealed
  candidate set minus its uniquely hash-bound annotation seed, while recording
  that exclusion in both the evaluation report and run manifest.
- Hardened evaluation publication against input changes and output-path races
  by revalidating all scored snapshots and claiming a new non-overwriting
  destination before copying verified staged artifacts.
- Preserved the first replacement-blind owner feedback as subjective,
  non-metric evidence and kept known wrong, missing, cluttered, or
  target-role-ambiguous notes unsealed.
- Ran a fixed annotation-only pYIN correction aid on a Hyak checkpoint CPU
  node, hash-verified all outputs, and rendered a narrow `Grand Piano` review
  for the three vocal passages without reading the sealed primary candidates.
- Added professionally annotated MedleyDB predominant-melody and Vocadito
  dual-annotator note benchmarks, with candidate routes and windows frozen
  before inference.
- Added portable Hyak/Mac candidate resolution, same-source external-reference
  binding, complete formal-evaluation run provenance, finite event validation,
  and auditable note-level corrected-seed application.
- Added a private score-guided `blind-04` correction from the owner-supplied
  original printed page 3, retaining source hashes, exact 22-note
  transcription, Beat This alignment, the unchanged old seed, and three
  acoustic-piano review renders without redistributing the score.

### Verified

- MedleyDB A40 candidate job `37690768` and final CPU evaluation job `37692231`
  completed; GAME ranked first with overall accuracy `0.7271`, raw pitch
  accuracy `0.6822`, voicing recall `0.9278`, and voicing false alarm `0.2086`
  at the fixed inclusive 50-cent tolerance.
- Vocadito A40 candidate job `37691274` and final CPU evaluation job `37692232`
  completed; GAME ranked first with macro per-track Amax onset+pitch F1
  `0.7447` and onset+pitch+offset F1 `0.4758`.
- Both trained-musician annotators remain separately reported; GAME aggregate
  onset+pitch F1 is `0.5966` against A1 and `0.7379` against A2.
- All authoritative `v3` outputs and their recorded final source files were
  hash-verified after Mac synchronization.
- The `blind-04` score crop was visually verified against original printed
  page 3, systems 2–3; its 22 notes are monotonic within `180.78–190.00 s`,
  and all three WAV reviews are non-silent PCM stereo at 44.1 kHz.
- Focused `/review` ran and all nine final P1/P2 findings received regression
  fixes.
- `make check` passed with 155 tests.

### Known limitations

- Owner listening percentages remain subjective and pYIN remains rejected;
  neither is reported as formal accuracy.
- MedleyDB frame metrics and Vocadito isolated-vocal note metrics do not
  constitute full-arrangement or private-song accuracy.
- The automated note-object discrepancy rate is not an edit-action lower bound
  or measured human time. Gate 2 remains pending a timed correction session,
  so Task 007 is not yet authorized.
- The private `blind-04` score-guided transcription was performed by Codex,
  not by the owner in a timed editor session; it remains provisional and cannot
  be used to claim that Gate 2 correction-time evidence is complete.

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
