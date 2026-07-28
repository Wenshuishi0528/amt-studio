# Changelog

This project records changes by numbered research task until formal semantic
versions and releases begin. Dates and commit identifiers refer to the local
Git history.

## Task 009B3F — Cache-safe reusable Hyak code sync — 2026-07-27

### Fixed

- Remote `.uv-cache`, worker `.venv`, and model-source `checkouts` directories
  are protected from the code snapshot's `rsync --delete`; traversing these
  non-Git assets caused the observed synchronization timeout.
- A remote code snapshot becomes reusable only after a successful transfer
  writes an atomic `sync_complete: true` marker. A marker copied near the start
  of an interrupted transfer is no longer accepted as proof of completion.
- Submissions on an already completed Git snapshot skip identical code sync.
  New snapshots retain a bounded 15-minute synchronization window.

### Verified

- The existing SSH ControlMaster remains online and the Slurm queue is empty.
  The failed retry stopped before project upload and job submission.
- A regression rejects the old incomplete marker and accepts only the explicit
  completed form.
- Full `make check` passes 294 Python and 50 Swift tests with three expected
  private-integration skips.

## Task 009B3E — Reliable Finder-launched song import — 2026-07-27

### Fixed

- The macOS backend now supplies a deterministic child-process `PATH` covering
  its `uv` directory, both standard Homebrew locations, macOS system tools, and
  the inherited path without duplicates.
- New-song import can therefore locate an installed `ffprobe` and `ffmpeg`
  when AMT Studio was opened from Finder rather than Terminal.
- Missing audio tools and project-ingest errors are returned as structured
  backend responses instead of unreadable Python tracebacks.

### Verified

- The original machine state resolves `ffprobe` and `ffmpeg` from
  `/usr/local/bin` under a minimal GUI-like environment.
- Full `make check` passes 292 Python and 50 Swift tests with three expected
  private-integration skips.
- The observed failure happened before project completion, upload, or Slurm
  submission; no model result was altered.

## Task 009B3D — Zero-candidate recovery and durable continuous notes — 2026-07-27

### Fixed

- Bounded MuScriptor gap recovery now accepts an existing empty native JSONL
  as a valid zero-candidate result and builds an unchanged derived version.
  Whole-song inference retains the strict non-empty-output requirement.
- Targeted task state carries the recovered candidate count, and failed jobs
  fetch available run/log evidence so the app can show an actual worker reason.
- Canonically equivalent NFC/NFD request paths are validated by filesystem
  identity instead of a Unicode-sensitive lexical comparison.
- Every pitched product track can preview and rebuild same-pitch continuous
  fragments across the whole song. The saved edit is immediately reopened and
  verified; drums keep their separate repeated-hit cleanup.

### Verified

- The two preserved failed attempts (`37811672`, `37811709`) both completed
  MuScriptor on an A100 node and produced an empty native event file, proving
  the failure was wrapper classification rather than a GPU/model crash.
- Full `make check` passes 291 Python and 49 Swift tests with three expected
  private-integration skips. Focused regressions cover bounded empty output,
  unchanged recovery packaging, Unicode state restoration, actionable failure
  details, all-track continuous-note planning, and save/reopen persistence.
- The single bounded review found one P1 request-directory symlink escape.
  Project containment is restored while canonically equivalent Unicode paths
  remain accepted.

## Task 009B3C — Visible GAME job progress — 2026-07-27

### Changed

- Active jobs now open a dedicated progress page even if the project already
  contains an editable result.
- Added non-destructive switching between the running-task page and the
  existing result; periodic polling preserves the user's current page.
- GAME large now reports submission, GPU wait, vocal separation, GAME
  transcription, rhythm analysis, and package/fetch as distinct phases.
- Remote artifact polling now names the step currently executing instead of
  lagging behind by one completed artifact.
- Targeted gap recovery retains its own compact phase labels, and progress
  titles remain bound to the active job when another project is open.

### Verified

- Focused Python and Swift regressions cover stage advancement, active-project
  restoration, and progress/result switching.
- Full `make check` passes. This change did not submit, cancel, or replace a
  Hyak or local inference job.
- One focused review found one P1 and two directly related P2 regressions; all
  were fixed without expanding the task.

## Task 009B3B — GAME large and live whole-track repair — 2026-07-27

### Changed

- Added a separately hash-pinned official `GAME-1.0-large` product checkpoint
  while preserving the historical medium experiment pin.
- Product discovery now covers the deployed private model directory, requires
  one matching large provenance, and never silently downgrades to medium.
- Each track menu now keeps a live fragment-scan action instead of caching an
  obsolete disabled state. Pitched tracks scan the full timeline; drums keep
  their distinct conservative tail-repeat treatment.

### Verified

- The official large archive and extracted config, language map, and PyTorch
  weight were independently size/hash checked.
- Focused Python tests and all 44 Swift tests pass. Hyak setup Job `37810626`
  completed on an A40 compute node in 6m59s; CUDA, GAME imports, archive hash,
  and all three extracted-file hashes passed. It performed model setup only.

## Task 009B3A — Optional GAME singing-voice track — 2026-07-27

Commit: this task's final commit

### Added

- Added a persisted recognition-mode choice: MuScriptor full multitrack remains
  the default, while GAME creates one singing-voice melody track on Hyak.
- Added a product Slurm chain that runs the pinned BS-Roformer vocal separator,
  isolated GAME inference, optional Beat This rhythm analysis, and canonical
  one-track MIDI packaging sequentially on a compute node.
- Added an existing-project action that creates a separate GAME version. The
  existing track manager can copy that voice track into a multitrack version
  without changing either source.

### Safety and product boundaries

- GAME never receives the full mix directly, never runs through the local
  MPS/CPU worker, and is not described as an instrumental-melody model. Its
  sequential product chain uses only non-preemptible GPU plans.
- GAME and separator assets are discovered only in the user's private Hyak
  storage. No weights, personal cluster identity, credentials, or Duo data
  enter the repository or application bundle.
- GAME confidence and velocity remain absent rather than invented. The
  official model-weight license is shown as CC-BY-NC-SA-4.0 and the route
  remains private non-commercial research; no automatic fusion or promotion
  over MuScriptor voice occurs.

### Verified

- `make check` passes 278 Python and 44 Swift tests with three expected private
  integration skips. Slurm shell parsing, Python compilation, and
  `git diff --check` pass.
- One isolated `/review` completed; its active-job, checkpoint-plan, bundle
  label, private-path, and evidence findings were resolved without expanding
  into another task.
- No Hyak or local model job was submitted. A real GAME product output and
  listening comparison require an explicit owner-triggered run.

## Task 009B2Z — Cross-version track management — 2026-07-27

Commit: this task's final commit

### Added

- Added a product-facing track manager that copies a track from another
  eligible version, merges selected tracks with an explicit instrument source,
  or removes a track from a newly derived custom version.
- Added atomic `custom-*` canonical bundles with source-bundle/track/event
  provenance, manifest hashes, post-write validation, and no source overwrite.
- Added per-track settings with confirmed, persistent, undoable sustain
  fragmentation repair. Pitched tracks use whole-track same-pitch analysis;
  drums retain the conservative trailing-repeat rule.

### Changed

- Hid rejected experiment bundles and intermediate comparison tracks from
  ordinary product navigation while preserving their immutable evidence.
- Moved note deletion beside note creation in the detailed piano-roll toolbar.
- Applied the selected merged instrument to both canonical track metadata and
  every merged event, refused deletion of the last visible product track, and
  prevented a finishing track operation from reopening a project the user
  already left.

### Verified

- `make check` passes 282 Python and 44 Swift tests with three expected
  private-environment skips. Derived copy/merge/delete, original immutability,
  merged MIDI export, last-track protection, project-switch races, and
  whole-track fragmentation detection have focused regressions.
- Strict Swift formatting, `git diff --check`, signed app packaging, and both
  configured real-project open/export paths pass. No Hyak or local model job
  was submitted.

## Task 009B2Y — Raw gap recovery without a count cap — 2026-07-27

Commit: this task's final commit

### Changed

- Switched automatic and user-selected voice-gap recovery to the raw
  voice-constrained generation chosen by the owner after listening to all
  three saved stages.
- Removed the fixed `max(32, source note count / 10)` candidate admission cap.
  Long selected gaps are no longer rejected solely because they contain more
  notes than a song-length-blind threshold.
- Kept accompaniment-filtered and monophonic-constrained outputs as diagnostic
  alternatives. Historical bundles explicitly rejected by the old policy
  retain that diagnostic status.
- Preserved the remaining safety boundary: recovery still operates only on
  detected or selected empty windows, uses voice-constrained decoding, clips
  events to the canonical audio timeline, and never overwrites source bundles.

### Real-project evidence

- The completed recovery was rematerialized without model inference as
  `gap-recovery-20260728T000154Z-244743c9-raw-product`.
  `voice_auto_enhanced` contains 1,186 notes: 322 preserved source notes plus
  all 864 raw recovery candidates.
- The production loader opened the new bundle and its complete MIDI passed
  validation. Full `make check` passes 282 Python and 39 Swift tests with
  three expected environment-gated skips. The signed app was rebuilt and
  opened; no Hyak or local inference job was submitted.

## Task 009B2X — Three-stage gap-recovery comparison — 2026-07-27

Commit: this task's final commit

### Added

- Added a deterministic comparison-bundle builder for completed targeted
  voice-gap recovery runs. It exposes raw generation, accompaniment-filtered,
  and monophonic-constrained candidates as three independently playable
  diagnostic tracks.
- Added a separate MIDI for each stage and a machine-readable comparison
  report with exact counts, lineage, and explicit no-rerun/no-overwrite claims.
- Added app playback rules that treat the three stage tracks as alternatives,
  so arrangement playback cannot accidentally stack them.

### Real-project evidence

- Recovery run `gap-recovery-20260728T000154Z-244743c9` materialized as 864
  raw notes, 234 notes after 630 accompaniment-shadow removals, and 161 notes
  after 73 additional monophonic-path rejections.
- The new private comparison bundle opens through the production project
  loader and exports valid MIDI. The immutable recovery run, source bundle,
  and existing 322-note product melody were not changed.
- Full `make check` passes 282 Python and 39 Swift tests with three expected
  environment-gated skips. The signed release app was rebuilt and opened on
  the real project; no model inference was submitted.

## Task 009B2W — Automatic Hyak GPU selection — 2026-07-27

Commit: this task's final commit

### Added

- Added a submission-time GPU planner for whole-song and selected-gap jobs.
  It discovers the current user's compatible Slurm associations and compares
  L40, L40S, A40, and A100 with no-allocation `sbatch --test-only` probes.
- Added deterministic selection: earliest estimated start first, then
  `A100 > L40S > L40 > A40` for plans within five minutes of the earliest.
- Added a stable L40 fallback when discovery or scheduling estimates are
  unavailable, so a transient planner failure does not reject an upload.
- Persisted the selected GPU, partition, wait estimate, preemption flag, and
  reason in local job state. The macOS sidebar and settings explain the result
  and visibly warn when a checkpoint route can be preempted.

### Verified

- A live read-only probe compared all four compatible plans and selected an
  immediately schedulable A100. It created no queued test job and did not
  change the existing running job.
- Full `make check` passes 281 Python and 38 Swift tests with three expected
  environment-gated skips. Strict Swift formatting, signed app packaging,
  plist/signature validation, Python compilation, and `git diff --check` pass.

## Task 009B2V — Configurable Hyak wall time — 2026-07-27

Commit: this task's final commit

### Changed

- Changed the default private-Beta whole-song and selected-gap Slurm wall time
  from three hours to one hour.
- Added a persistent 1–24 hour `Hyak 运行时限` control to the app settings.
  The selected value is passed explicitly to new whole-song and selected-gap
  submissions; local GPU and CPU tasks are unchanged.
- Renamed the former appearance-only sheet to `设置` while preserving both
  existing visual modes.

### Live scheduling evidence

- Job `37804031` had no Slurm start estimate because the normal L40 association
  was at its group GPU limit. Same-resource `sbatch --test-only` snapshots
  estimated L40 at 2026-07-28 06:22 PDT and L40S at 2026-07-27 20:19 PDT.
- Checkpoint A40 and A100 tests both reported immediate starts. The pending,
  never-run L40 job was replaced by one A100-only Job `37805247` with a
  one-hour limit; it started on an 80 GB A100 within seconds. Test-only jobs
  did not remain queued.
- Full `make check` passes 277 Python and 38 Swift tests with three expected
  environment-gated skips.

## Task 009B2U — Conservative automatic melody admission — 2026-07-26

Commit: this task's final commit

### Fixed

- Removed the unrestricted residual decode from production main-melody gap
  recovery. Directed `voice` candidates and their immutable diagnostic
  artifacts remain available.
- Added a conservative automatic merge gate. Recovery candidates exceeding
  `max(32, source note count / 10)` are preserved but cannot replace the safer
  melody by default.
- Made the macOS app reject an excessive automatic voice bundle at startup,
  restore its recorded eligible source bundle, and label the rejected bundle
  as diagnostic while retaining manual access.
- Preserved rejected selected-gap candidates as a non-playing diagnostic track,
  kept later manual selections across restarts, and bound cumulative recovery
  decisions to the backend admission recorded for that source version.

### Verified

- The bad completed bundle contains 1,179 automatic voice notes versus 322 raw
  notes; its preceding owner-accepted source contains 338. The app now opens
  that 338-note source and keeps the 1,179-note bundle unchanged.
- Full `make check` passes 276 Python and 38 Swift tests with three expected
  environment-gated skips. A configured real-project integration asserts the
  selected bundle, note count, and existing guitar-tail diagnostic.
- No Hyak or local inference job was submitted.

## Task 009B2T — Organized library and visible tail repair — 2026-07-26

Commit: this task's final commit

### Added

- Added project search and active/completed/incomplete grouping to the sidebar
  music library.
- Added per-project open, Finder reveal, and confirmed move-to-Trash actions.

### Changed

- Library recency now follows job-state and result-bundle updates instead of
  relying only on the project directory timestamp.
- Failed reruns stay in the incomplete/failed group even when a project retains
  an older usable bundle.
- Tail repair remains visible for every selected track and explains
  already-cleaned or no-candidate states instead of disappearing.

### Safety and verification

- Project removal rereads live persisted job state and refuses active jobs,
  unreadable/unknown states, symlinks, manifest mismatches, or targets outside
  the private project root. Removing an open inactive project no longer clears
  monitoring for an unrelated active job.
- Local Job `37754413` is `COMPLETED / complete / succeeded`. The newest real
  bundle opens successfully, and its clean-electric-guitar track still exposes
  five tail groups with 51 fragments. Full `make check` passes 274 Python and
  37 Swift tests with three expected environment-gated skips; the real-project
  integration passes.
- The single bounded review reported two P1 deletion-state defects and one
  failed-rerun grouping defect; all three were fixed with regression coverage.

## Task 009B2S — Durable edits and bounded product postprocessing — 2026-07-26

Commit: this task's final commit

### Added

- Added a visible `保存修改` command, saved-time status, and compatible
  cross-version edit-session migration bound to the selected track artifact.
- Added traceable accompaniment soft masking and a single non-recursive
  unrestricted MuScriptor fallback for residual main-melody gaps.
- Added per-track generated-product cleanup reports and preserved raw sidecars
  for changed pitched sustain fragments and dense drum-tail repeats.

### Changed

- Automatic and user-selected main-melody recovery now merges only filtered
  candidates into the preferred voice track. Raw directed and fallback
  candidates remain immutable diagnostic artifacts.
- New result bundles clean conservative accompaniment-tail artifacts during
  packaging. Pitched tracks derive a sustain; drums retain one short hit rather
  than becoming a long note.

### Verified

- On the current song, read-only application of the new mask keeps 160 of 841
  raw candidates, rejects 606 accompaniment shadows and 75 polyphonic
  competitors, and plans one fallback for the still-empty `0:00–0:15` opening.
- Read-only tail analysis detects the same 51 guitar fragments, 10 bass
  fragments, and 14 drum repeats reported by the app's manual analyzers.
- The newest bundle opens with the prior clean-guitar edit restored as a
  compatible session. Full `make check` passes 274 Python and 37 Swift tests
  with three expected environment-gated skips. No new model job was submitted.

### Limitations

- Soft masking may reject a true melody doubled in unison with accompaniment.
  The fallback and cleanup remain Beta derivations with provenance and no
  accuracy claim.

## Task 009B2R — Task-focused note inspector — 2026-07-26

Commit: this task's final commit

### Changed

- Made pitch, onset, offset, duration, and note deletion the primary inspector
  content.
- Hid the confidence-review panel when a track provides no confidence values;
  tracks with real source confidence keep the existing threshold workflow.
- Collapsed model/run provenance under `来源信息` and cross-track review hints
  under `高级诊断`. Trailing cleanup stays visible only for a flagged current
  track.

### Verified

- The signed app was rebuilt and visually checked on the active private
  project. The submitted Hyak recovery remained running through the app
  restart.
- Full `make check` passes 267 Python and 36 Swift tests with three expected
  environment-gated skips. Strict Swift formatting and `git diff --check`
  pass.

## Task 009B2Q — Instrument-constrained gap decoding — 2026-07-26

Commit: this task's final commit

### Fixed

- Changed automatic voice-gap recovery from an unconstrained full-arrangement
  decode followed by `voice` filtering to MuScriptor's native
  `--instruments voice` constrained decode.
- Changed user-selected recovery to pass the selected track's instrument into
  the same decoding allowlist. This preserves generic accompaniment recovery
  without mixing accompaniment notes into the main melody.
- Recorded the allowlist in recovery requests while retaining immutable source
  bundles, child native output, and prior result versions.

### Verified

- The prior completed five-gap result contains 16 real additions, but three
  selected spans returned zero and the missing audible melody was absent from
  every unconstrained output track. The issue was therefore the recovery
  decoding route, not bundle loading or piano-roll rendering.
- Focused tests pass 15 cases. Full `make check` passes 267 Python and 36 Swift
  tests with three expected environment-gated skips. No replacement model job
  was submitted during this fix.

## Task 009B2P — Per-track tail cleanup — 2026-07-26

Commit: this task's final commit

### Fixed

- Automatically excluded model notes beyond canonical audio from product
  piano rolls, review, MIDI playback, and both single-track and multitrack MIDI
  export while preserving raw model artifacts.
- Added independent tail diagnostics to every track. Melodic tracks merge
  contiguous same-pitch sustain fragments; drum tracks instead collapse
  periodic repeated hits to one short hit per detected drum pitch.

### Added

- Added orange per-track cleanup badges to the mixer and all-track piano roll.
  Selecting a flagged row opens that track's own confirmation action.
- Added conservative percussion-repeat detection and an undoable
  `折叠重复打击` edit. Confirmation warns that a real pattern or roll can look
  similar, so cleanup is never applied silently.

### Verified

- The current drums track reports two groups and 14 in-timeline hits; 28
  predictions after the real audio endpoint are automatically excluded.
  Electric bass reports one 10-fragment sustain group.
- Focused and configured-real-project checks pass. Full `make check` passes
  265 Python and 36 Swift tests with three expected environment-gated skips.
  This change started no compute. The owner's subsequent five-gap request
  passed the corrected boundary and is running separately as Job `37751981`.

## Task 009B2O — Canonical timeline repair — 2026-07-26

Commit: this task's final commit

### Fixed

- Fixed the final selected gap being rejected when accompaniment MIDI extended
  past the canonical audio. Product timing now uses the audio manifest's
  duration rather than the latest predicted note offset.
- Fixed bar/beat position, all-track timeline, gap detection, and
  trailing-sustain cleanup sharing inconsistent song endpoints.
- Clamped new sustain merges to the real audio endpoint and added a narrow,
  undoable repair for legacy app-generated sustain merges that exceed it.

### Verified

- The real audio ends at `271.805147` seconds; model notes extend to `274.96`.
  The corrected fifth gap ends at `271.805147`, and all five current gaps pass
  read-only request planning as one bounded task.
- A true selection beyond the audio endpoint remains rejected. No request file,
  Slurm job, or local model task was created during diagnosis or verification.
- Focused tests, configured real-project checks, and full `make check` pass:
  265 Python and 33 Swift tests with three expected environment-gated skips.

## Task 009B2N — Gap launch repair and trailing sustain cleanup — 2026-07-26

Commit: this task's final commit

### Fixed

- Fixed the installed private-Beta console entry point failing to import the
  repository-owned `workers` package before selected-gap submission.
- Converted worker-loading failures to bounded JSON and separated normal
  backend operation errors from malformed-response diagnostics, preventing raw
  Python tracebacks from being presented as the primary user message.

### Added

- Added conservative detection of same-pitch contiguous fragments at the end
  of the selected track.
- Added an owner-confirmed `合并为延长音` action that merges all detected
  pitch chains as one saved, undoable edit without changing canonical model
  output.

### Verified

- The failed UI attempt occurred before Slurm submission. Existing Job
  `37746586` remains terminal and no recovery request or replacement job was
  created.
- The current song's `clean_electric_guitar` track has five trailing pitch
  groups containing 121 contiguous events. From `270.12` seconds, the same
  five-note chord is split at `0.23`-second intervals. Task 009B2O later
  established that the portion after the `271.805147`-second canonical audio
  endpoint is model spill and must be clamped, not treated as song duration.
- A real-project integration check detects exactly five groups and 121
  fragments. `make check` passes 264 Python and 31 Swift tests with three
  expected environment-gated skips.

### Limitations

- A repeated articulation can resemble a fragmented sustain. Cleanup therefore
  requires owner confirmation, applies only to conservative trailing chains,
  remains undoable, and is never written into the original MuScriptor JSONL.

## Task 009B2M — User-selected targeted gap recovery — 2026-07-26

Commit: this task's final commit

### Added

- Added per-gap checkboxes, select-all/clear controls, confirmation, and one
  action that sends the selected current-track gaps to Hyak GPU, local GPU, or
  local CPU as one recovery task.
- Added a generic MuScriptor targeted-recovery worker and L40 Slurm entry point
  that follow the selected track's instrument label instead of being limited
  to voice.
- Added recovery task state, pipeline progress, reconnect/resume, child-run
  result fetching, previous-job history, and automatic opening of the returned
  bundle and target track.

### Changed

- Current-track coverage now uses the canonical source version and canonical
  audio duration, lists every gap rather than only the first four, and works
  for accompaniment tracks as well as the main voice candidate.
- Selected spans receive bounded context windows and run sequentially in one
  allocation. A successful result creates a new complete multitrack bundle and
  augments only the selected track; the source bundle is never overwritten.

### Verified

- The current `ピカソ-ビギン-ザ-ナイト` voice result plans five safe windows,
  including the two large owner-reported gaps, without writing project state
  or submitting a job.
- `make check` passes 263 Python and 29 Swift tests with three expected
  environment-gated skips. Focused tests cover multi-gap planning, generic
  accompaniment filtering, source preservation, task stages, UI arguments,
  selection controls, and real-project loading.
- One narrowly scoped `/review` was invoked for Task 009B2M only. It returned
  no findings or other output for more than eight minutes after the network
  interruption, so the stalled process was stopped and was not rerun; the
  targeted manual P0/P1 and secret/path checks found no blocking issue.

### Limitations

- Empty spans can be intentional silence. Recovered notes are same-model
  candidates and require listening review.
- One request supports at most 16 bounded target windows. No real GPU or local
  inference job was submitted during implementation.

## Task 009B2L — Beat-aware editing and result acceptance — 2026-07-26

Commit: this task's final commit

### Added

- Added one-click, one-beat note creation at the current playback head with a
  visible current-track button, `Command-Shift-N`, immediate selection, saved
  edit history, and undo/redo support.
- Added Beat This rhythm events to canonical bundles and BPM, meter,
  bar/beat-position, downbeat, and beat-grid displays to the current-track
  editor while retaining second-based timing.
- Added a conservative song-level acceptance summary and navigation across
  low-confidence and abnormally short notes on all normal product tracks.

### Changed

- Future Hyak song jobs now run pinned Beat This after full-song MuScriptor and
  before automatic same-model gap recovery, all sequentially in the same GPU
  allocation.
- Performance MIDI uses the verified Beat This tempo and meter maps when
  available. Older or local bundles without a rhythm run remain compatible
  and visibly retain their default serialization grid. Beat-analysis failure
  also falls back to that grid without discarding successful multitrack work.
- Added a truthful rhythm-analysis stage to job status and fetch the immutable
  Beat This run with completed project results.

### Limitations

- Rhythm is a model estimate, not verified notation. The current Beat This
  normalizer fixes the denominator to four, so compound-meter distinctions
  such as 6/8 are not guaranteed.
- Review items are diagnostic hints and are never automatically deleted or
  counted as confirmed transcription errors.
- Job `37746586` was submitted with the previous code and was not interrupted;
  it completed `0:0` in `00:21:19`, was fetched successfully, and its existing
  result keeps the default rhythm grid.

### Verified

- Focused Python and Swift tests cover verified rhythm binding, pipeline-stage
  detection, bar/beat placement, review classification, note creation,
  persistence, and undo.
- Swift Package and Xcode builds, strict Swift formatting, signed release
  packaging, plist/signature validation, shell syntax, and
  `git diff --check` pass.
- Full `make check` passes 259 Python and 29 Swift tests with three expected
  environment-gated skips. The single focused `/review` found no remaining
  P0/P1 blocker.

## Task 009B2K — Optional local compute backend — 2026-07-26

Commit: this task's final commit

### Added

- Added an explicit per-song compute selector with Hyak GPU as the unchanged
  default plus optional Apple Metal/MPS and local CPU modes.
- Added local readiness reporting for the isolated MuScriptor environment,
  pinned model provenance, ffmpeg, and Apple MPS availability.
- Added a detached per-project local worker with fixed logs, resumable status,
  pipeline stages, lower CPU scheduling priority, and guarded stop support.

### Changed

- Generalized the private-Beta status flow so local execution uses the same
  full-song multitrack, automatic same-model gap recovery, raw fallback, and
  final bundle contract as the Hyak route.
- Kept the existing Slurm/login-node guards as the default for gap recovery;
  only the explicit local worker can select the bounded non-Slurm path.
- Updated the app copy and job view to identify where a task runs without
  implying that an SSH login controls the lifetime of either backend.

### Verified

- `make check` passes 258 Python and 28 Swift tests with three expected
  environment-gated Swift skips. Strict Swift formatting, the signed release
  build, plist/signature validation, and `git diff --check` pass.
- Tests verify local command planning and state/readiness safety without
  spawning MuScriptor. Per owner request, no local model inference or local
  song processing was performed, so local runtime speed and output quality
  remain unmeasured.
- The separate XCUITest launch was blocked by the already-running production
  app with the same bundle identifier. That app was retained because it was
  monitoring live Hyak Job `37744240`; no GUI pass is claimed for this slice.
- A read-only Hyak check found only Job `37744240` on L40. Its full-song
  MuScriptor run completed successfully and the single job continued into
  multitrack/gap processing; no duplicate job was submitted.

## Task 009B2J — All-track piano-roll overview — 2026-07-26

Commit: this task's final commit

### Added

- Added a default full-song overview that renders every normal product track
  as a separate vertically stacked piano-roll lane.
- Added per-lane instrument labels, actual note counts, distinct track colors,
  and a shared transport playhead.
- Added a clear `全部音轨` / `当前音轨` switch. Selecting a lane and entering
  the current-track view preserves the existing drag, resize, inspector,
  undo, and redo workflow.

### Changed

- Kept raw and gap-only voice variants behind the existing diagnostic toggle,
  avoiding duplicate melody lanes in the standard product view.
- Registered the existing appearance source file in the Xcode project so the
  formal UI-test target builds the same theme-enabled app as Swift Package
  Manager and the release packager.
- Synchronized the stable default branch to the public repository with portable
  Hyak placeholders and no tracked personal account name, credential, private
  audio, result bundle, or local Hyak configuration.

### Verified

- Opened the signed release app on the real completed eight-track project and
  visually confirmed all lanes, note distributions, selection, time ruler,
  and shared playhead.
- The formal XCUITest opens the overview, switches to the current-track roll,
  then passes playback, edit, undo/redo, and restart recovery.
- `make check` passes 257 Python and 27 Swift tests with three expected skips.
  Strict Swift formatting, release signing, `git diff --check`, and the
  standalone XCUITest pass.

## Task 009B2I — Precision and Spectrum product UI — 2026-07-26

Commit: this task's final commit

### Added

- Added a restrained Precision theme as the default and a Spectrum theme
  selectable from a dedicated Appearance sheet.
- Added a truthful five-stage Hyak progress view for upload/queue, full-song
  transcription, gap inspection, automatic recovery, and packaging.
- Added local appearance persistence with explicit copy that theme changes do
  not reload projects, rerun Hyak, or alter MIDI.

### Changed

- Consolidated the toolbar into focused Project and Export menus. The first
  export item now explicitly says `整个识别版本（完整多轨 MIDI）`.
- Applied theme tokens to the shell, library, sidebar, real waveform, and
  piano-roll notes while retaining native macOS controls and SF Symbols.
- Preserved one shared layout and functionality set across both modes; the
  Spectrum option adds static color and contrast rather than heavy animation
  or blur.

### Verified

- Confirmed real Job `37743206` as `COMPLETED / succeeded` with exit `0:0`,
  automatic gap recovery, and the final bundle fetched locally.
- Switched both appearance modes in the signed app, relaunched to verify
  persistence, and restored Precision as the current mode.
- `make check` passes 257 Python and 26 Swift tests with three expected skips.
  Strict Swift formatting, release signing, plist validation,
  `git diff --check`, and documented dual-mode design QA pass.

## Task 009B2H — Unicode-safe jobs and explicit version export — 2026-07-26

Commit: this task's final commit

### Fixed

- Accepted canonically equivalent NFC/NFD forms of a macOS project identifier
  without weakening same-file, manifest, remote-path, identifier, or traversal
  validation.
- Restored polling for the Japanese-named real project attached to Job
  `37743206`; the job remained running and was not submitted twice.

### Changed

- Separated `保存修改` from file export and promoted `导出整版 MIDI` to a
  visible toolbar and sidebar action.
- Explained that whole-version export uses the explicitly selected recognition
  bundle, includes every accompaniment track and one preferred melody variant,
  and ignores mixer M/S/volume. Current-mix and current-track exports remain
  available under `其他导出`.

### Verified

- Reproduced the old failure with the decomposed Japanese path, then passed the
  same production status command after the fix.
- The real nine-track automatic `STILL LOVE HER` bundle passed application-level
  whole-version MIDI export with a valid standard MIDI header.
- `make check` passes 257 Python and 25 Swift tests with three expected skips.
  Strict Swift formatting, signed release packaging, plist/signature
  validation, and `git diff --check` pass.

## Task 009B2G — Automatic same-model voice-gap recovery — 2026-07-26

Commit: this task's final commit

### Added

- Added deterministic long-gap planning over the immutable full-song `voice`
  track, with fixed clip, context, target-count, and duration bounds.
- Added a single-job private-Beta continuation that runs contextual
  MuScriptor recovery after the full-song pass without another upload.
- Added `voice_auto_enhanced` with note-level raw/candidate provenance and a
  self-contained product bundle that also retains every accompaniment track.
- Added private-Beta pipeline stages for full transcription, gap planning,
  automatic recovery, packaging, and completion.

### Changed

- Automatic-recovery failure now falls back to a newly built raw multitrack
  bundle instead of discarding a successful full-song transcription.
- Normal mixer display hides raw and gap-only voice diagnostics by default.
  Playback and standard multitrack export include at most one voice variant;
  users can still reveal the preserved alternatives.
- Reconnecting after SSH expiry continues to resume the same remote job and
  now also resumes its current pipeline-stage display.

### Verified

- The automatic planner reproduced four contextual windows over the existing
  `STILL LOVE HER` raw result, covering the same five previously reviewed
  empty targets without new inference.
- Existing immutable candidates produced a private nine-track dry-run bundle:
  438 auto-enhanced voice events, 254 raw voice events, 184 gap candidates,
  and all six original accompaniment tracks. The real Swift project loader
  and selected-track MIDI export pass.
- `make check` passes 256 Python and 25 Swift tests with three expected skips.
  Strict Swift formatting, shell syntax, and `git diff --check` pass.
- The focused P0/P1 review fixed hidden diagnostic-track playback after the
  advanced section is collapsed and found no remaining blocker.
- No Hyak job, model inference, source separation, GAME, training, retuning,
  or new dataset work ran.

## Task 009B2F — Owner-approved enhanced voice — 2026-07-26

Commit: this task's final commit

### Added

- Added an immutable `voice_enhanced` derivation from `voice_raw` plus the
  separately preserved, owner-reviewed `voice_gap_candidate`.
- Added provenance on every enhanced event, including its source variant and
  source event ID.
- Added app preference and display language for the enhanced main-vocal track.

### Changed

- Made raw, gap-only, and enhanced voice variants mutually exclusive during
  mix playback so comparison tracks never stack duplicate notes.
- Updated melody-gap reporting to describe the currently selected voice
  variant rather than an arbitrary first `voice` track.

### Verified

- The owner subjectively estimates that the gap pass recovered more than 95%
  of previously missing notes, with a few omissions remaining. This is
  recorded as single-song listening feedback, not a formal accuracy metric.
- The enhanced bundle contains 254 raw, 184 gap-candidate, and 438 enhanced
  events. Raw SHA-256 remains
  `25725cff2b738bee8d66514dc5fbde51e04cf1a6b5e74c490e52025de4b4d48c`.
- The real project loads and exports selected-track and arrangement MIDI with
  `voice_enhanced`; all 25 Swift tests pass with three expected skips.
- No model job, source separation, GAME, training, or automatic model
  promotion ran.
- Final `make check` passes 254 Python and 25 Swift tests. The focused P0/P1
  review fixed variant mute/solo semantics and found no remaining blocker.

## Task 009B2E — Same-model directed voice-gap probe — 2026-07-26

Commit: implementation `918544b`; compatibility/evidence in this task's final
commit

### Added

- Added a compute-only MuScriptor gap probe over four frozen contextual clips,
  covering five source-`voice`-empty targets without rerunning the full song.
- Added an immutable `voice_gap_candidate` artifact, per-target coverage
  report, and a two-track review bundle that keeps `voice_raw` separate.
- Added legacy rhythm-map compatibility for review MIDI generation.

### Measured

- Hyak Job `37740313` completed all four L40 MuScriptor child runs and produced
  184 candidates: 52 in each middle target, 80 in the first tail target, and
  none in the intro negative control or final tail target.
- Candidate union time is 60.23 seconds across 208.043719 seconds of
  non-control targets (28.95%). This is coverage only; correctness and
  false-positive counts remain unset pending owner listening.
- The original 254-note `voice_raw` remains unchanged at SHA-256
  `25725cff2b738bee8d66514dc5fbde51e04cf1a6b5e74c490e52025de4b4d48c`.

### Fixed and verified

- The parent Slurm job reached review packaging after successful inference but
  exited `1:0` because the older private-Beta rhythm map omitted provenance
  fields required by current MIDI validation. Existing inference artifacts
  were reused; no model run was repeated.
- The recovered review bundle declares no merge, fusion, preferred candidate,
  or accuracy claim and passes the real private-project Swift loader.
- Startup Jobs `37739953`, `37739955`, and `37740294` failed before inference
  while resolving direct imports, the ffmpeg module, and Lmod nounset
  compatibility. They changed no source result and remain diagnostic evidence.
- Source separation, GAME, training, retuning, and automatic merging were not
  started.
- Final `make check` passes 253 Python and 24 Swift tests with three expected
  environment-gated skips; the focused P0/P1 review found no blocker.

## Task 009B2D — Responsive library and voice coverage — 2026-07-26

Commit: this task's final commit

### Added

- Added a project home screen and prior-music sidebar backed by the existing
  private project library, plus remembered security-scoped access for projects
  opened outside the repository.
- Added original-audio and MIDI-master volume controls.
- Added `voice` coverage diagnostics: long-gap count/duration, direct gap
  navigation, and per-gap note counts from other predicted tracks.
- Reworded `voice` as a lead-vocal candidate instead of a complete
  main-melody claim.

### Changed

- Moved project preparation, bundle/track selection, and MIDI-preview export
  off the SwiftUI main actor with stale-result guards.
- Cached editor materialization and melody-gap analysis, avoided reloading the
  same audio for every track click, isolated transport refreshes, and split
  the piano roll into lazy time segments.
- Opened the Hyak login script without AppleScript Terminal control. Release
  builds now use an installed Apple Development identity when available and
  fall back to ad-hoc signing only when necessary.

### Verified

- The fetched 349.85-second `STILL LOVE HER` result has four `voice` gaps of
  at least three seconds (`0.00–33.35`, `63.55–90.69`,
  `104.52–131.41`, and `195.14–349.85`), totaling `242.09` seconds.
  This corroborates the owner's report of high apparent pitch accuracy where
  notes exist but poor time coverage; it is not a formal accuracy score.
- All 24 Swift tests pass with three expected environment-gated skips. Both
  real-project integration tests pass on the private fetched result.
- Final `make check` passes 247 Python and 24 Swift tests. A focused P0/P1
  review found no remaining blocker.
- The release app passes strict Apple Development signature and plist
  validation and launches on the real fetched project.
- No inference, Slurm submission, model retuning, or destructive merge was
  performed.

## Task 009B2C — Reconnectable multitrack mixer — 2026-07-26

Commit: this task's final commit

### Added

- Added explicit current-track versus all-track audition modes and a visible
  mixer with per-track note counts, mute, solo, and MIDI volume.
- Added current audible-mix MIDI export while preserving the existing current
  edited-track and complete-multitrack exports.
- Added mixer persistence across restart and safe filtering/volume validation
  in the multitrack MIDI writer.
- Added Hyak connection state, owner-controlled Terminal relogin, automatic
  ControlMaster detection, active-job persistence, and same-job resume after
  SSH expiry.
- Added duplicate-submission prevention while a job is active and local
  completed-state restore that does not block the next song.

### Verified

- Real Job `37735878` completed `0:0` in `00:24:50` on L40 node `g3096`;
  the production status route fetched the result and the Hyak queue is empty.
- The fetched `STILL LOVE HER` result retains 10,989 events across 7 predicted
  tracks, including 254 `voice` events. Its MIDI has 8 tracks including
  conductor, 6 program changes, and 2,115 percussion note-ons.
- The production Swift loader and selected/full-arrangement integration test
  pass on that private result.
- Swift unit tests cover track selection, volume controller serialization,
  mixer persistence, and completed-job restore. The formal XCUITest passes
  open, real waveform, playback, review, editing, undo/redo, and relaunch
  restoration.
- The single bounded `/review` found no P0 and one P1: direct upload after SSH
  expiry did not enter the explicit reconnect state. That path is fixed; no
  lower-priority review expansion was performed.
- Final `make check` passes 247 Python tests and 21 Swift tests, with two
  expected environment-gated Swift skips.
- The release app builds, passes plist/signature validation, launches with a
  real 13-track project, and visibly exposes the new mixer.

### Scope

- This changes product orchestration and audition only. It does not retrain,
  retune, or alter MuScriptor, claim instrument-label accuracy, restart the
  paused Task 007 route, or run model compute on the Mac/login node.

## Task 009B2B — MuScriptor private Beta workflow — 2026-07-26

Commit: this task's final commit

### Added

- Added a single-song Mac-to-Hyak controller with safe ControlMaster reuse,
  project/code synchronization, L40 Slurm submission, status polling, final
  accounting, and result retrieval.
- Added a one-pass MuScriptor job that skips the redundant native-MIDI decode
  and derives one immutable canonical track per predicted instrument.
- Added native app controls for Hyak login, song selection, progress refresh,
  automatic result opening, default `voice` main-melody selection, and
  current-track versus complete-multitrack MIDI export.
- Added General MIDI program/channel mapping for edited multitrack exports
  while retaining model labels and explicit uncertainty.
- Added an ignored per-machine Hyak configuration with a placeholder-only
  committed example; personal NetIDs and storage roots are no longer compiled
  into the product.
- Added commit-exact `git archive` code synchronization and strict persisted
  job-state boundary validation.

### Verified

- The Task 002 full-song run converts to 9 tracks with all 7,667 events.
- Production Swift loading and the private selected/full-arrangement export
  test pass on that real project; Python bundle and orchestration regression
  tests pass.
- The ad-hoc-signed production app builds successfully.
- Real job `37734361` completed `0:0` in `00:17:28` on L40 node `g3098`.
  The bounded workflow created the project, synchronized code/audio, submitted,
  polled, fetched, and reopened the result without login-node inference.
- The fetched run contains 6,881 valid events in 13 predicted instrument
  tracks. Its complete MIDI has 14 tracks including conductor, 12 program
  changes, and all 1,545 drum notes on the percussion channel.
- The source/canonical hashes, model weight/revision, beam size, and prelude
  setting match Task 002. The old A100 and new L40 event/label counts differ,
  so cross-hardware byte invariance is explicitly not claimed.
- The single final `/review` found no P0 and five P1 issues. All five were
  fixed with targeted coverage: Xcode target membership, state path/identity
  validation, preservation beyond one MIDI port, exact synchronized commit
  provenance, and configurable Hyak identity/root. Three P2 suggestions were
  not expanded under the requested stop rule.
- Final `make check` passed 247 Python and 18 Swift tests with two expected
  environment-gated Swift skips. Seven Python tests came from preserved,
  paused Task 007D worktree files and are excluded from this commit.

### Scope

- This product Beta uses the Task 002 MuScriptor baseline. It does not revive
  rejected fusion, add a dataset, retune a model, claim formal accuracy, or
  run inference on the Mac/login node.

## Task 007C — Instrumental full-mix development rejection — 2026-07-26

Commit: this task's final commit
(`feat: test instrumental melody development route`)

### Added

- Froze a duration-only six-window Phoenix MedleyDB development probe before
  inference, with explicit development provenance and no blind-performance
  claim.
- Added exact canonical full-mix lineage to the Basic Pitch adapter while
  preserving the separator-vocal contract. Direct-mix output is normalized as
  unknown instrument `other`, never mislabeled as voice.
- Added a development-capable melody evaluator path, automatic three-condition
  assessment, Slurm prepare/evaluate jobs, an ADR, configuration, and
  regression coverage.
- Excluded local Swift `.build/` and `dist/` products from Hyak synchronization
  and removed the accidentally synchronized regenerable copies from the remote
  repository mirror.

### Verified

- Prepare job `37732190`, Basic Pitch job `37732191`, and evaluation job
  `37732192` all completed `0:0` on Hyak compute nodes.
- The sealed candidate produced 1,701 `other` events. Across 20,676 frames,
  raw pitch accuracy was `0.6932`, overall accuracy was `0.3339`, and voicing
  false alarm was `0.9648`; all frozen conditions failed.
- Benchmark freeze SHA-256 is
  `e64a30cd6acdfe8064bace7a2872fe36e22056e45939ff07722a39db4ceda5b8`;
  candidate-set payload SHA-256 is
  `cc5b7df33ba9bdc36b020b2461a68b1cdb98827527ff8f855c1f0b880ee168a9`;
  final report SHA-256 is
  `fbe730efde84b8f1cb70c5a81844c1573eca9a8a51cee468d23603525b90a7df`.
- The automatic decision is
  `reject_direct_mix_instrumental_route_for_v1`. Phoenix was not retuned and
  remains development-only.
- Hardened v2 decision SHA-256 is
  `5bb86efc3ee236013b71147d1b54ceea76c3a5e76bd6f1455014dca41805aa13`;
  it authenticates the seals, candidate artifacts, evaluation run manifest,
  reference, 50-cent tolerance, and fixed projection before reading metrics.
- `make check` passed 230 Python and 17 Swift tests, with one expected
  private-integration skip. The single `/review` reported two P1 and two P2
  findings; both P1 findings were fixed with targeted regression tests, while
  the two non-blocking hardening suggestions were left documented without
  expanding Task 007C.

### Decision

- Do not acquire an instrumental blind set for this rejected direct-mix route.
  Scope the v1 research product to lead-vocal main melody around retained GAME
  evidence. Gate 4 remains open, so Task 009B2B and Task 010 stay blocked.

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
