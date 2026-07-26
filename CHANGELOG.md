# Changelog

This project records changes by numbered research task until formal semantic
versions and releases begin. Dates and commit identifiers refer to the local
Git history.

## Task 007B — Gate 4 recovery rejection — 2026-07-26

Commit: this task's final commit (`feat: add Gate 4 recovery experiment`)

### Added

- Froze a new five-singer development and six-singer blind Vocadito split,
  disjoint from Task 006 and Task 007 v1.
- Added a constrained GAME plus Basic Pitch fusion plan, A40/CPU Slurm chain,
  sealed two-candidate evaluation support, automatic Gate 4 precondition
  assessment, and regression coverage.
- Preserved official annotation CSVs while explicitly accepting at most 5 ms
  of end-boundary timestamp/PCM quantization drift.

### Verified

- Preparation `37720512`, A40 candidates `37720513`, calibration `37720514`,
  final seal `37722126`, and evaluation/assessment `37722127` completed `0:0`.
- Candidate, fusion, scoring-source, and benchmark seals verified. Final report
  SHA-256 is
  `ea66e1b20b3739478a56b89a0c5e104af55b959de15007de7f34dbded507a1f7`.
- GAME scored `0.7814` onset+pitch F1 and `0.3676`
  onset+pitch+offset F1. Fusion scored `0.6924` and `0.3276`, regressions of
  `0.0891` and `0.0400`.
- The frozen assessment emitted `reject_v2_without_blind_retuning`. Local
  ignored evidence was synchronized and its hashes match Hyak.
- Full `make check` passed before submission. Final infrastructure fixes pass
  the affected 19-test suite plus Slurm syntax, compile, and diff checks. The
  single `/review` was run but stopped after it expanded into unrelated old
  code without a completed P0/P1 report.

### Limitations

- Gate 4 remains open. No matched human-correction comparison is justified for
  rejected v2, and neither Task 009B2B nor Task 010 may start from this result.
- This result is limited to the fixed solo-vocal Vocadito excerpts and must not
  be generalized to full songs or used for blind retuning.

## Task 009B2A — Formal macOS UI-flow verification — 2026-07-25

Commit: this slice's final commit

### Added

- Added a committed Xcode application target and XCUITest bundle that compile
  the production Swift sources.
- Added a runtime-generated non-ASCII canonical fixture containing synthetic
  PCM audio, a low-confidence note, and a note with unknown confidence.
- Added a `make mac-ui-test` entry point and isolated test launches from the
  user's recent-project preference.

### Verified

- The formal UI test opens the project, observes the real waveform, piano roll,
  and confidence controls, advances playback, navigates review, edits a note,
  exercises undo/redo, relaunches, and confirms persistent history.
- `make mac-ui-test` passes one UI test with zero failures. Separate final
  `make check` passes 216 Python plus 17 Swift tests with one expected private
  integration skip.
- The single focused review found no P0/P1. Both P2 findings were fixed by
  waiting for decoded waveform samples and making the README command
  working-directory safe.
- No private media, local inference, Hyak compute, worker, or model pack was
  used.

### Limitations

- This closes the formal editor-flow test gap only. Import, background job
  progress/cancellation, worker/model-pack discovery, production inference,
  and MusicXML remain gated.

## Task 009B1 — Existing-project waveform and review queue — 2026-07-25

Commit: this slice's final commit

### Added

- Replaced the note-density placeholder with a cancellable 2,048-bin peak
  envelope decoded from verified canonical audio.
- Added selected-track confidence thresholding, uncertainty-first navigation,
  transport seek, and explicit missing-confidence accounting.
- Added ADR 0009 to permit model-independent review surfaces while keeping
  import, workers, inference, and model packs behind Gate 4.

### Verified

- The real 4:25 private-project waveform rendered in the foreground app.
- All four current canonical tracks contain zero non-null confidence values;
  GAME therefore correctly reports `0 / 0` review items and 391 unknowns.
- Swift tests cover PCM peak placement, threshold/order behavior, and unknown
  exclusion, including non-ASCII paths and audio/timeline alignment.
- The single focused review found no P0/P1. Its four P2 findings were fixed,
  and final `make check` passes 216 Python plus 17 Swift tests with one
  expected private-integration skip. No Hyak or local model job ran.

### Limitations

- Source-model confidence is not calibrated across tracks and is never labeled
  as accuracy.
- Audio import, background job progress/cancellation, worker/model-pack
  discovery, formal XCUITest, and production inference remain blocked.

## Task 009A — Gated native existing-project editor — 2026-07-25

Commit: this task's final commit (`feat: add gated native editor task 009a`)

### Added

- Added a Swift 6/macOS 14 package with model-free `AMTStudioCore`, SwiftUI
  `AMTStudioUI`, and a foreground `AMT Studio.app` packaging script.
- Added explicit canonical bundle and candidate-track selection with
  project-root-relative path, file size, SHA-256, schema, event count,
  duplicate-ID, and symlink checks.
- Added original/MIDI transport, live piano-roll cursor, short-note-safe mouse
  move and left/right resize gestures, source toggles, and actionable preview
  errors.
- Added non-destructive create/update/delete/split operations, undo/redo,
  atomic operation-log/current-state/session writes, restart restoration, and
  selected-track performance MIDI export without changing base JSONL.
- Added ADR 0008 and separated Task 009A editor work from the still-gated
  Task 009B import/background-job/model-pack boundary.

### Verified

- The signed app bundle launched as a foreground application with a visible
  window. The real private project required an explicit one of three bundles
  and one of four unranked tracks; all 2,223 events and referenced hashes
  validated.
- Selecting GAME loaded 391 notes on a 4:25 timeline. Accessibility-driven
  playback advanced the transport from 0 to 6.512789 seconds and paused.
- The real export is standard MIDI format 1, 960 PPQ, two tracks, and 391
  note-ons; Mido parsed it, GarageBand imported it, and Logic Pro opened it.
  Its SHA-256 is
  `5c16d7323b55d8d6f59172e5b3eaab30405e6660b633921bcb24f16c296295ce`.
- Normal Swift tests pass 16 tests with one expected private-integration skip;
  the explicit real-project integration run passes. Repository-level
  `make check` passes 216 Python tests plus the Swift suite. Swift format
  lint, plist, ad-hoc signature, and diff checks pass.
- Focused review found no P0. All implementation-safety P1 launch, contract,
  observation, hit-target, error-display, path-safety, atomicity,
  duplicate-track, and MIDI-overflow findings were fixed with regression
  coverage. Formal XCUITest remains an explicit Task 009B gap.

### Limitations

- This does not pass Gate 4 or select a production transcription model.
- Audio import, waveform, progress/cancellation, confidence review, model
  packs, formal XCUITest, and MusicXML remain Task 009B or later work.

## Task 008 — Hyak batch experiment system — 2026-07-25

Commit: this task's final commit (`feat: complete Hyak batch task 008`)

### Added

- Added ADR 0007 and the `amt-batch-spec/v1`,
  `amt-batch-manifest/v1`, `amt-batch-complete/v1`, selection, and index
  contracts.
- Added content-addressed batch rows that bind input, configuration, model,
  relevant code, code revision, virtualenv launcher, resolved interpreter,
  installed-package fingerprint, and ordered stage definitions, with safe
  reuse across later manifests containing identical work. Python entry points
  must be frozen repository artifacts.
- Added `amt-batch-execution/v2`: stages now consume cache-local immutable
  snapshots of every declared input, configuration, model, and code artifact.
  Stage processes use a controlled environment; only explicitly declared
  stage values are cache-key-bound and forwarded.
- Added atomic, hash-verified stage completion; persistent per-stage
  checkpoints; cleanup of unpublished stage data; termination forwarding;
  persistent raw/derived output archives with selected-output markers; and
  fully preflighted fail-closed retention.
- Added manifest-derived Slurm arrays with STF L40S, checkpoint A40, and CPU
  smoke profiles, compute-node manifest freezing, durable array submission
  records before dependent-finalizer submission, and centralized experiment
  indexes.
- Added execution-failure, cache-hit, wall-time, peak-RSS, allocation,
  host/device, and storage-budget summaries backed by manifest-filtered,
  append-only persistent attempt records and stdout/stderr logs.
- Added global retention serialization, active-cache protection, safe cleanup
  of terminal incomplete caches after evidence persistence, and new-work
  admission blocking while the shared root is already over budget.
- Added Hyak-to-Mac synchronization for frozen manifests, logs, indexes, and
  selected results while excluding complete scrubbed caches.

### Verified

- Final smoke manifest `task008-smoke-v7` has SHA-256
  `44c265b6f402798d4ed277fb2e7f94524747a432f5fac97f87061dc6f42de18d`;
  freeze job `37712191` completed on CPU compute node `n3467`.
- Hyak scheduler test-only probes accepted the real STF L40S and checkpoint
  A40 profiles as `37712211` and `37712212` without executing GPU work.
- First CPU array `37712213` deliberately interrupted one row after its
  prepare stage and completed the other. Replay array `37712227` reused the
  completed prepare stage, finished only the interrupted stage, and returned
  an entire-row cache hit for the already completed row.
- Finalizers `37712215` and `37712230` completed on Slurm compute nodes. The
  final index reports both rows completed, execution failure rate `1/3`, and
  cache-hit rate `1/4`.
- All four append-only attempts, ten attempt logs, selected and prepare
  outputs, manifests, scheduler logs, and indexes were synchronized to the Mac
  and re-hashed. Central index
  SHA-256 is
  `766d07fedc4c360412b15cd724e7c0d635ebd519a7e259965703e0cdf37dfdb0`.
- The synchronized manifest loaded offline, and shared-root retention counted
  all 14 cache directories (`117,938` bytes), not only the v7 rows.
- The single final `/review` reported two P1 findings and one P2. Both P1
  findings were fixed with regression coverage; the requested P0/P1-only stop
  rule left the P2 root-level stray cache-file accounting edge case unchanged.
- No post-review Hyak smoke was run. Smoke v7 remains the scheduler/resume/
  cache/finalizer/retention evidence and predates the final execution-v2
  hardening.
- `make check` passed with 216 tests; Ruff lint, JSON, Slurm shell, compile,
  and diff checks passed.

### Limitations

- The smoke uses only project-owned text fixtures. It proves orchestration,
  interruption recovery, caching, provenance, retention, and sync behavior;
  it does not measure model quality, GPU throughput, or compatibility of a
  specific model's internal checkpoint format.
- Gate 4 remains open because Task 007 fusion quality was rejected. Task 009
  remains blocked by stable backend gates.
- Retention does not account for arbitrary regular files placed directly at
  the cache root; managed cache directories remain covered. This P2 review
  finding is documented rather than expanded after Task 008's stop instruction.

## Task 007 — Deterministic fusion and confidence v1 — 2026-07-25

Commit: this task's final commit (`feat: complete deterministic fusion task 007`)

### Added

- Added ADR 0005 to distinguish assisted correction, owner final review, and
  unavailable direct owner editing while authorizing bounded fusion research.
- Added ADR 0006 for deterministic main-melody fusion and pre-scoring blind
  fusion sealing.
- Added deterministic onset/pitch/duration clustering, one-event-per-source
  agreement, profile-weighted representatives, eight explicit features,
  main-melody competition, survivor-aware overlap handling, rejected-candidate
  provenance, and development-only isotonic confidence.
- Added development calibration with worker-route binding, source reliability,
  frozen raw-score threshold selection, calibration diagnostics, and immutable
  input/output hashes.
- Added immutable fusion runs that verify worker manifests, project/canonical
  lineage, stable worker/model/input/decoding identities, complete candidate
  accounting, and final-note provenance.
- Added blind fusion sealing and evaluation that bind the candidate seal, all
  fusion/provenance/rejection artifacts, calibration, metric and acceptance
  protocol, and 11 scoring-source hashes before loading blind references.
- Added four worker ablations, eight feature ablations, evaluated-window-only
  precision/coverage, separate main-melody/multi-track states, and explicit
  unavailable human correction time.
- Added a fixed Vocadito v3 development/blind split with 12 unique singers,
  all disjoint from Task 006 blind singers, plus Hyak Slurm entrypoints for
  preparation, A40 candidate inference, calibration, fusion/sealing, and
  evaluation.

### Verified

- Preparation jobs `37705519`/`37705562`, A40 candidate job `37705578`,
  calibration job `37705582`, blind fusion/seal job `37706932`, and evaluation
  job `37706934` all completed on Hyak compute nodes with exit code `0:0`.
- Blind candidate-set SHA-256 is
  `e2584762d81911d8685b45aecbbdf4949d1f4d9c2824289d9a6d6312ca6bb403`;
  fusion evaluation-seal payload SHA-256 is
  `50181e0c74a22396b9d1fe2770c0750351f890dc17a2c6039332794cfa12f520`.
- GAME remained strongest at blind macro Amax onset+pitch F1 `0.7797` and
  onset+pitch+offset F1 `0.4316`; fusion scored `0.7410` and `0.4332`.
- At confidence threshold `0.75`, fusion retained `41/293` evaluated-window
  notes with onset+pitch precision `0.8556` and recall `0.1225`.
- All synchronized calibration, fusion, seal, and evaluation artifacts match
  their manifests; all 11 scoring-source hashes match the sealed values.
- Final focused `/review` found no remaining P0–P2 issue.
- `make check` passed with 186 tests; Ruff, Slurm shell syntax, Task 007 JSON,
  compile, and `git diff --check` validation also passed.

### Decision and limitations

- Rejected deterministic fusion v1 as the default route: a `0.0016`
  offset-aware gain does not justify a `0.0387` onset+pitch regression.
- GAME remains the main-melody baseline. Blind ablation findings are diagnostic
  only and were not used for retuning.
- Fusion and GAME share the same automated discrepancy rate, `85.3723/min`.
  Matched human correction time and multi-track reference metrics remain
  unavailable, so Gate 4 does not pass.
- The authoritative evaluation report SHA-256 is
  `8d529a72cdd9119f7eabf97cf64b6c4010c96d668de8a592a2a0cd896d0c5f75`.

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
- Added non-overwriting `blind-04-v2` evidence after tracing the owner's
  obvious-wrong-note report to six V1 staff-position errors; V2 records the
  corrected score pitches, existing Hyak vocal-F0 support, MIDI, and three
  regenerated review WAVs.

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
- V2 corrects the two affected measures to
  `D-Bb-Bb-Bb / D-Bb-D-C`; the eight existing vocal pYIN interval medians
  support those score pitches, and all V2 artifact hashes and MIDI/WAV
  structure validate.
- Focused `/review` ran and all nine final P1/P2 findings received regression
  fixes.
- `make check` passed with 155 tests.

### Known limitations

- Owner listening percentages remain subjective and pYIN remains rejected;
  neither is reported as formal accuracy.
- MedleyDB frame metrics and Vocadito isolated-vocal note metrics do not
  constitute full-arrangement or private-song accuracy.
- The automated note-object discrepancy rate is not an edit-action lower bound
  or measured human time. At Task 006 close, the original Gate 2 wording still
  blocked Task 007; Task 007's later ADR 0005 authorized only the explicitly
  named assisted workflow and did not create a direct-edit efficiency claim.
- The private `blind-04` score-guided transcription was performed by Codex,
  not by the owner in a timed editor session; it remains provisional and cannot
  be used to claim that Gate 2 correction-time evidence is complete.
- The owner estimated the first score-guided audition at roughly 80% correct
  and heard obvious wrong notes; the value is subjective, and the artifact is
  explicitly marked `needs_revision` rather than accepted or sealed.
- After the six-note V2 correction, the owner informally estimated accuracy
  above 95% and accepted V2 as the current private reference. This remains
  subjective listening evidence, not a formal metric, seal, or timed
  correction record.
- Invalidated a masked timed-review mix, then completed a piano-forward
  replacement with one full 12-second playback and owner acceptance in 41
  seconds wall-clock time. The full six-pitch assisted correction took 449
  seconds end to end; direct owner note-edit time remains unavailable, so the
  strict Gate 2 was not redefined or marked complete.

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
