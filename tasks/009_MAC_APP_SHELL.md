# Task 009: Native macOS application shell

Status: private Beta usability implementation complete — Task 009A, 009B1,
009B2A, bounded 009B2B MuScriptor inference, 009B2C reconnect/mixer, and
009B2D responsiveness/library/voice-coverage work are complete. Task 009B2E
same-model directed gap recovery and Task 009B2F owner-approved enhanced voice
productization are complete. Task 009B2G single-upload automatic same-model
gap recovery and Task 009B2H Unicode-safe polling/explicit whole-version export
are complete for the private Beta. Task 009B2I/J complete the dual-mode product
shell and all-track overview. Task 009B2K adds optional local MPS/CPU execution
while retaining Hyak as the default. Task 009B2L adds beat-aware editing,
manual note creation, and song-level result acceptance. Task 009B2M–O add
selectable gap recovery, launch repair, conservative sustain cleanup, and one
canonical product timeline. Task 009B2P applies that boundary to every product
consumer and adds instrument-aware cleanup on every track. Task 009B2Q fixes
gap recovery to constrain MuScriptor during decoding instead of discarding
non-target instruments only after an unconstrained decode. Task 009B2R makes
the inspector task-focused by hiding empty confidence controls and collapsing
diagnostic provenance. Task 009B2S makes compatible edits survive a newer
result version, filters recovery candidates against accompaniment, performs at
most one residual fallback, and derives instrument-aware tail cleanup while
preserving raw events. Task 009B2T organizes the local music library, adds
recoverable project deletion, and keeps tail-repair status visible. Task
009B2U removes unrestricted main-melody fallback, rejects excessive automatic
voice growth, and restores the latest eligible source version by default.
Task 009B3A adds an optional Hyak-only GAME singing-voice single-track route
while retaining MuScriptor full multitrack as the persisted default. Task
009B3D closes the real zero-candidate recovery failure and makes whole-track
continuous-note rebuilding a durable per-track product operation. Task 009B3E
restores new-song import for Finder-launched app processes whose inherited
environment omits Homebrew audio tools. Task 009B3F makes the following
Mac-to-Hyak code snapshot transfer cache-safe and reusable. Task 009B3G adds a
persistent multi-song queue. Task 009B3H adds the selected product artwork plus
visible, bundle-backed version and author identity. Task 009B3I adds
non-destructive cross-song track copying and removes the client's single-active
Hyak submission gate while retaining serialized uploads and local compute.
Task 009B3M adds an owner-triggered, read-only view of current Hyak scheduler
capacity without creating or changing jobs.
Task 009B3N publishes the first bilingual product introduction and v0.2.0
developer/tester Private Beta while preserving the previous README.
Task 009B3O treats Slurm active-queue expiry as an accounting lookup rather
than an SSH failure.
Task 009B3P adds a persistent collapsible completed-song library group.

## Task 009B3P: collapsible completed-song library

Goal:

- keep a growing local music library readable without removing completed
  songs or changing project state.

Frozen rule:

- the “最近完成” heading toggles only the visibility of its rows;
- the collapsed preference persists locally across app restarts;
- active and failed groups remain visible and unchanged;
- a non-empty search overrides the collapsed presentation so matching
  completed songs remain discoverable;
- no project, queue, inference, or Hyak state changes.

## Task 009B3O: completed-job accounting fallback

Goal:

- keep result retrieval working after Slurm removes a completed job from
  `squeue`;
- avoid hiding real SSH or scheduler failures.

Frozen rule:

- only the exact `Invalid job id specified` response from the active-job query
  is converted into an empty queue result;
- refresh then uses the existing `sacct` path and preserves the recorded state
  and exit code;
- every other `PrivateBetaError` remains visible;
- the fallback never submits, retries, or modifies a Hyak job.

Evidence:

- the regression test reproduces the exact rejected active-queue lookup,
  returns a completed accounting row, and verifies result retrieval;
- the affected real project recovered as `COMPLETED / 0:0` and fetched its
  result without resubmission;
- final `make check` passes 297 Python and 60 Swift tests with three expected
  private-environment skips.

## Task 009B3N: public bilingual v0.2.0 release

Goal:

- present the real current product to Chinese- and English-speaking users;
- preserve the previous project introduction as an exact historical document;
- publish the verified source and an honestly labeled Mac Private Beta without
  leaking private compute or music data.

Frozen publication boundary:

- include source, tests, schemas, public documentation, selected brand artwork,
  and the packaged Apple Silicon app;
- exclude private songs/results, datasets, model weights, credentials,
  personal Hyak identity/storage/session data, and cluster logs;
- label the app as unnotarized and dependent on the repository/lightweight
  Python backend rather than claiming a standalone consumer installer;
- preserve the old README byte-for-byte under `docs/archive/`.

## Task 009B3M: read-only Hyak resource status

Goal:

- let a beginner inspect current compatible Hyak GPU availability without
  leaving AMT Studio;
- preserve a truthful distinction between node state and likely scheduling
  time;
- keep the check observational and independent from task submission.

Frozen product rule:

- the check is user-triggered and uses only `sinfo`, owner-scoped `squeue`, and
  `sbatch --test-only`;
- it must not create a placeholder job, reserve a GPU, cancel, resubmit, or
  otherwise alter any task;
- node state is a momentary cluster snapshot, while estimated start is a
  non-reserving Slurm test for the wall time currently configured in Settings;
- only compatible GPU classes are shown, the existing scheduling policy marks
  one recommendation, and private username, host, and account identifiers do
  not enter the product UI.

Evidence:

- the backend test proves all scheduling probes contain `--test-only` and
  validates node-state counts, owner queue counts, wait time, and
  recommendation;
- the Swift test validates the complete typed capacity response;
- final `make check` passes 296 Python and 60 Swift tests with three expected
  private-environment skips;
- the formal Xcode project and packaged release app both build successfully;
- no Hyak job, inference, dataset experiment, or training work ran.

## Task 009B3I: cross-song tracks and concurrent Hyak submissions

Objective:

- copy one selected track from one song/version into a chosen version of
  another song without changing either source model bundle;
- preserve every copied note's absolute timing, including events beyond the
  target song's normal playback timeline;
- remove the Mac client's one-active-Hyak-job restriction without claiming or
  bypassing any live Slurm/QOS account limit.

Implemented and verified:

- `管理版本与音轨` now selects a completed destination song and an eligible
  destination version. Copying creates and verifies a new `custom-*` bundle in
  the destination project, opens the copied track, and leaves both source and
  target recognition bundles byte-unchanged;
- copied notes receive new event and track IDs while retaining source project,
  bundle, track, event, model, and edit lineage. Onset and offset seconds are
  preserved exactly; events after the target song ending remain stored but are
  outside its original-audio playback timeline. Single-track and whole-version
  MIDI exports preserve those imported events instead of clipping them;
- Hyak song uploads remain serialized, but every successful submission
  immediately releases the next Hyak queue item. Slurm decides whether jobs
  run together or remain `PENDING`; local CPU/GPU jobs remain serialized;
- one persistent fleet monitor polls every submitted project and retrieves
  terminal results instead of monitoring only the last submission. Interrupted
  submission remains manual-retry-only, so the duplicate-job safety boundary
  is unchanged;
- the single `/review` invocation was stopped when it expanded into the paused
  Task 007D research files. The resulting focused state review found and fixed
  two directly relevant P1 issues: background terminal jobs now release queued
  local work, and removing the currently viewed project preserves monitoring
  for every other active Hyak project. No second or expanded review was run;
- `make check` passes 294 Python and 56 Swift tests with three expected private
  integration skips. Strict Swift formatting and `git diff --check` pass. No
  song, model, or Hyak job was submitted by this implementation.

## Task 009B3H: product artwork and identity

Objective:

- adopt the owner-selected bright sky-blue and champagne-gold cover;
- expose one truthful application version and author identity in normal UI;
- package the exact artwork in both Swift Package and Xcode application builds.

Implemented and verified:

- `AMTStudioCover.png` is shown on the library home, sidebar brand header, and
  Settings about card, with a deterministic fallback if a test host has no app
  resources;
- the visible identity is `AMT Studio 0.2.0`, build `2`, by
  `wenshuishi26`. `Info.plist`, Xcode marketing/build settings, and the root
  Python package metadata agree;
- the signed release app contains the exact selected 1254 x 1254 PNG under
  `Contents/Resources`; its packaged and source SHA-256 values both equal
  `ea9d44fd188d9a9ab915633ba06ec3171ea338fc7b69791670d20f2bddf26c23`;
- `make check` passes 294 Python and 52 Swift tests with three expected private
  integration skips. Strict Swift formatting, plist validation, release
  packaging, resource hashes, signing, and `git diff --check` pass.

## Task 009B3G: persistent sequential multi-song queue

Objective:

- let a normal user select several songs once and process them one by one;
- keep only one active local or Hyak model task at a time;
- survive app restarts without silently duplicating an ambiguous submission.

Implemented and verified:

- the audio picker accepts multiple files and stores an ordered queue. Each
  item freezes the recognition mode, compute target, and Hyak time limit that
  were selected when it entered the queue;
- pending items and security-scoped bookmarks persist in local user defaults.
  A prior `submitting` item is restored as failed/manual-retry-only so a crash
  window cannot automatically create a duplicate remote task;
- a terminal task advances the first waiting item. Failed local submissions
  remain visible and retryable but are skipped when later waiting items exist;
  expired Hyak authentication pauses instead of repeatedly attempting login;
- the sidebar exposes queue order, configuration, state, retry, and removal.
  Settings can change for later additions while an active task continues;
- full `make check` passes 294 Python and 52 Swift tests with three expected
  private integration skips. The signed app was rebuilt and relaunched with no
  persisted queue, so no model job was submitted or replaced.

## Task 009B3F: cache-safe reusable Hyak code sync

Objective:

- prevent a new-song submission from timing out while synchronizing an
  unchanged or small committed code snapshot;
- never classify a partially copied snapshot as complete.

Implemented and verified:

- `rsync --delete` now excludes persistent `.uv-cache`, worker `.venv`, and
  model-source `checkouts` directories in addition to private assets. This
  removes the real shared-filesystem traversal that exceeded 180 seconds;
- the transfer no longer copies its trust marker near the start. After a
  successful sync, the backend writes `sync_complete: true` atomically;
- later songs on the same commit verify that completed marker and skip
  identical code sync. A new commit has a bounded 15-minute transfer window;
- the failed real retry created a local manifest but stopped before project
  upload and Slurm submission. The existing SSH master is healthy and the
  queue is empty;
- `make check` passes 294 Python and 50 Swift tests with three expected private
  integration skips.

## Task 009B3E: Finder-launched audio-tool discovery

Objective:

- make a new-song submission use installed `ffprobe` and `ffmpeg` even when
  the macOS application was launched outside Terminal;
- report a genuinely missing local dependency as a concise product error,
  never as a Python traceback.

Implemented and verified:

- child processes receive a deterministic, de-duplicated `PATH` containing the
  resolved `uv` directory, both standard Homebrew binary locations, macOS
  system binary locations, and the inherited path;
- the real machine's `/usr/local/bin/ffprobe` and `ffmpeg` resolve under a
  minimal GUI-like environment. Audio-tool and project initialization failures
  now use the backend's structured JSON error contract;
- the observed import failed before upload and Slurm submission. No raw model
  bundle or existing recognition version was changed;
- `make check` passes 292 Python and 50 Swift tests with three expected private
  integration skips.

## Task 009B3D: zero-candidate recovery and durable continuous notes

Objective:

- repair the latest selected-gap task without mistaking “the model found no
  notes” for a GPU or inference crash;
- make the owner's same-pitch continuous-note repair reusable on every similar
  pitched track, with truthful preview and verified persistence.

Implemented:

- only bounded child decodes invoked by targeted recovery pass the new
  `--allow-empty-jsonl` contract. A present zero-byte native event file becomes
  a valid zero-candidate run; missing output and empty whole-song inference
  remain failures;
- zero-candidate recovery produces an immutable derived bundle whose product
  track is unchanged and whose manifest records zero recovered candidates.
  Swift status text reports that result directly;
- failed Hyak refreshes fetch available run/log artifacts and expose the
  worker's recorded reason. Targeted success records the recovered candidate
  count in validated local state;
- request-path validation uses the resolved file's identity and requires it to
  be a direct member of the project's requests directory, fixing canonical
  NFC/NFD spelling differences without weakening containment;
- the per-track menu rescans the selected track, reports the actual number of
  fragments and replacement groups, rebuilds all conservative same-pitch
  groups, saves once, reopens the editor, and verifies new IDs exist while old
  fragments do not. This path is available for every pitched product track;
  percussion retains its distinct repeated-hit treatment.

Evidence:

- preserved Jobs `37811672` and `37811709` both ran on an A100 compute node,
  exited MuScriptor successfully, and wrote an empty native events JSONL for
  the selected intro. That is the exact case covered by the new bounded
  contract;
- `make check` passes all 291 Python and 49 Swift tests, with three expected
  skips requiring private live integration. New regressions cover empty child
  output, unchanged packaging, state summaries, NFC/NFD paths, exact fragment
  counts, multi-voice grouping, and save/reopen persistence;
- the single bounded review found one P1 request-directory symlink escape.
  Resolved paths must remain inside the project before their filesystem
  identity is accepted, preserving Unicode compatibility without weakening
  containment;
- original model bundles and both failed attempts remain unchanged. A corrected
  real retry is submitted only after this committed worker is synchronized.

## Task 009B3C: visible GAME job progress

Objective:

- make an active GAME task visibly answer “currently running which step?”
  without requiring the user to infer state from a Job ID;
- keep an older editable result available while the new version runs.

Implemented:

- unfinished submissions and restored active projects automatically select a
  dedicated progress page, even when the project already contains an editor;
- the toolbar and progress page switch non-destructively between the running
  task and the existing result. Periodic polling updates status without
  overriding the user's selected page;
- GAME exposes six truthful milestones: submit, GPU wait, BS-Roformer vocal
  separation, GAME large transcription, Beat This rhythm analysis, and
  package/fetch;
- backend polling maps existing separator, GAME, rhythm, and bundle manifests
  to the step currently executing. It does not invent a completion percentage.
- targeted gap recovery retains a distinct compact phase sequence, and the
  progress title remains bound to the active job if another project is open.

Evidence:

- the backend phase test advances through separation, GAME, rhythm, and
  packaging artifacts;
- the Swift regression restores an active GAME project that already has an
  editor, verifies progress is initially visible, and verifies both directions
  of the progress/result switch;
- full `make check` passes. No inference job was submitted, cancelled, or
  replaced for this task.
- the single focused review found one P1 polling regression and two directly
  related P2 display regressions; all three were fixed without a second or
  expanded review.

## Task 009B3B: GAME large deployment and reliable whole-track repair

Implemented:

- new GAME product submissions require a uniquely verified official
  `GAME-1.0-large` provenance from the actual private Hyak model layout;
  historical Task 004/007 medium pins and evidence remain unchanged;
- the product Slurm chain passes `pins-large.json` explicitly and refuses an
  absent or medium-only installation instead of silently downgrading;
- every track settings menu always exposes a live fragment scan. Pitched
  tracks scan interior and trailing same-pitch fragmentation across the whole
  song. Drums keep the separate conservative trailing-repeat rule;
- invoking repair refreshes current diagnostics before confirmation, saves
  the edit immediately, and retains undo plus immutable source output.

Evidence:

- official large archive and all three extracted files were independently
  size/hash checked before pinning;
- focused Python tests cover deployed-path discovery and medium rejection;
  existing Swift core coverage proves interior fragmentation is found, while
  the full Swift suite compiles the always-available menu path;
- setup attempt `37810417` failed before setup because `AMT_REPO_ROOT` was not
  exported. Attempt `37810443` was cancelled after a duplicated asset-root
  component was detected, and only that attempt's newly created wrong-path
  directory was removed. Corrected Job `37810626` completed on an A40 compute
  node in 6m59s: CUDA and GAME imports passed, the official large archive and
  all three extracted files matched their pins, and product discovery found
  one large provenance plus the separator model. No song inference was part
  of any setup job.

## Task 009B2U: conservative automatic main-melody admission

Implemented:

- automatic and selected main-melody recovery keep MuScriptor constrained to
  `voice` and no longer launch the unrestricted residual fallback;
- raw directed candidates and soft-mask reports remain immutable diagnostic
  artifacts, but automatic merge additionally requires candidate growth no
  greater than `max(32, source note count / 10)`;
- rejected candidates do not alter the product melody. Existing rejected
  bundles remain manually inspectable and are labeled as diagnostic in the
  version list. New rejected selected-gap candidates are exposed as a
  non-playing diagnostic track;
- on startup and result retrieval, the macOS app refuses an ineligible
  automatic bundle and restores the eligible `source_bundle_id` recorded by
  the completed recovery job. Later manual selection of another eligible
  historical bundle remains the saved restart state;
- cumulative recovery uses the admission decision recorded against its
  immediate source version instead of reapplying the threshold against the
  original raw voice.

Evidence:

- completed Job `37754413` used `--instruments voice`, yet added 841 candidates
  to the prior 338-note melody and produced 1,179 notes. The earlier
  owner-accepted recovery added 16 notes to the 322-note raw voice;
- the configured real-project test now opens
  `gap-recovery-20260727T035419Z-c5001346-multitrack` with 338 notes and retains
  the clean-guitar five-group/51-fragment tail diagnostic;
- full `make check` passes 276 Python and 38 Swift tests with three expected
  environment-gated skips. No model job was submitted.

## Task 009B2T: organized music library and persistent tail-repair entry

Implemented:

- the sidebar music library now searches all projects and groups them into
  active, completed, and incomplete/failed sections instead of truncating one
  undifferentiated recent list;
- every project row exposes open, Finder reveal, and move-to-Trash actions.
  Deletion is recoverable, requires confirmation, revalidates the manifest and
  direct-child path, rejects symlinks/out-of-library targets, and requires the
  latest persisted Slurm state to be explicitly terminal. Unreadable, unknown,
  suspended, or requeued states fail closed;
- deleting the open inactive project preserves polling and result retrieval
  when another project owns the active task. Failed reruns remain under
  incomplete/failed even if the project retains an older result bundle;
- library ordering uses the newest manifest, job-state, or result-bundle time,
  so a newly completed task does not remain buried by an old directory mtime;
- the tail-repair panel is always present for a selected track. It distinguishes
  a current repair candidate, an already saved/automatic repair, and a checked
  track with no conservative candidate.

Verification:

- local state records Job `37754413` as
  `COMPLETED / complete / succeeded` for targeted gap recovery; no live SSH
  master was available, so no new Duo prompt or Slurm action was started;
- the newest private bundle opens on `voice_auto_enhanced`. Its selected voice
  has no conservative tail candidate, while `clean_electric_guitar` still
  exposes five groups containing 51 fragments. The prior disappearing control
  was therefore a UI visibility condition, not removal of the analyzer;
- full `make check` passes 274 Python and 37 Swift tests with three expected
  environment-gated skips; the configured real-project integration passes;
- the single bounded review found two P1 deletion-state issues and one
  user-facing failed-rerun grouping issue; all three are fixed with targeted
  regression coverage.

## Task 009B2S: durable edits and bounded product postprocessing

Implemented:

- every saved edit session records the selected-track artifact hash. A newer
  bundle restores the latest session only when that track is unchanged; legacy
  sessions must carry before-state operations that replay exactly;
- compatible migrated edits are immediately saved under the new bundle. The
  toolbar exposes `保存修改` with `Command-S`, and the sidebar reports the last
  persisted time;
- directed main-melody candidates remain in raw JSONL. The preferred product
  candidate removes strong same-pitch/time copies of verified accompaniment
  and selects a monophonic non-overlapping path;
- residual target gaps of at least three seconds receive one and only one
  contextual decode without an instrument allowlist. Non-percussion events
  retain the model's original instrument label in provenance before entering
  the same soft mask;
- every generated accompaniment track is processed independently at packaging
  time. Conservative pitched fragments derive one sustain; conservative dense
  drum repeats derive one short hit. Changed pre-cleanup events are copied to
  `raw_tracks/`, and a JSON report records source IDs and counts;
- all raw worker runs, source bundles, and prior canonical bundles remain
  unchanged. None of these derived tracks claim formal accuracy.

Verification:

- read-only validation of the owner's current 841-note recovery keeps 160
  filtered candidates, removes 606 accompaniment shadows and 75 overlapping
  alternatives, then plans four residual windows including the owner-reported
  `0:00–0:15` opening. The real result itself was not rewritten;
- the current accompaniment yields five clean-guitar groups/51 fragments, one
  bass group/10 fragments, and two drum groups/14 hits under the shared
  conservative rules;
- focused Python and Swift suites pass, including source preservation,
  one-pass fallback planning, percussion-as-short-hit behavior, and
  cross-version edit migration;
- the configured newest private bundle opens with the prior clean-guitar edit
  restored. Full `make check` passes 274 Python and 37 Swift tests with three
  expected environment-gated skips;
- no Hyak or local inference was submitted during implementation.

## Objective

Build a native SwiftUI application around the stable project format and backend API without embedding model-specific assumptions.

## Task 009A: existing-project editor shell

Implemented:

- foreground `.app` packaging and project open/save;
- explicit canonical bundle and candidate-track selection;
- hash/size/path validation without inference or a Hyak connection;
- piano roll, cursor, original/MIDI transport, and source toggles;
- mouse move plus left/right note resizing with a usable hit target for short
  notes;
- non-destructive, atomically persisted edit history with undo/redo and
  restart restoration;
- selected-track performance MIDI export;
- actionable project, audio, and MIDI-preview errors.

The overview is explicitly labeled as note density, not an audio waveform.
Candidate tracks remain unranked and are never described as a final accurate
melody.

## Task 009B1: model-independent review surfaces

Implemented:

- a fixed-size peak envelope decoded from the verified canonical audio on a
  cancellable utility task;
- an original-audio waveform synchronized with the transport cursor;
- a selected-track confidence threshold and previous/next review navigation;
- explicit exclusion and counting of events whose source model did not
  provide confidence;
- source-model confidence labels that forbid cross-model comparison.

This slice reads existing project artifacts only. It does not import audio,
launch a worker, contact Hyak, or promote a transcription route.

## Task 009B2A: formal UI-flow verification

Implemented:

- a committed Xcode application target and UI-test bundle that build the same
  production Swift sources;
- a runtime-generated project under a non-ASCII path with canonical audio,
  two notes, one low source confidence, and one explicitly unknown confidence;
- end-to-end interaction coverage for project open, unique-track selection,
  real waveform, playback advancement, review navigation, note editing,
  undo/redo, process restart, and restored edit history;
- `--no-recent-project` isolation so the fixture neither reads nor replaces
  the user's remembered project.

The fixture contains only a generated three-second PCM waveform. No private
audio, model artifact, inference process, or Hyak job is involved.

## Task 009B2B: gated backend work

Implemented for the private Beta:

- audio import and deterministic local project creation;
- a bounded `amt-private-beta` start/status interface;
- safe reuse of a user-authenticated SSH ControlMaster without storing a
  password, OTP, or Duo response;
- L40 Slurm submission, status/accounting checks, and automatic result
  retrieval;
- one-pass full-song MuScriptor JSONL inference followed by lossless
  per-instrument bundle derivation;
- default `voice` main-melody selection while keeping every original predicted
  accompaniment track;
- selected-track and complete edited multitrack MIDI export.

Cancellation, MusicXML, training, generic model-pack discovery, and new
research datasets are outside this private Beta. The workflow does not select
the rejected fusion route or move model compute onto the Mac/login node.

## Task 009B2C: reconnect and multitrack mixer

Implemented:

- active private-Beta jobs are remembered independently of the most recently
  edited project and reopen after an app restart;
- the app reports Hyak connection state and distinguishes an expired SSH
  login from a failed Slurm job;
- `连接 Hyak` opens the existing local Terminal login script, then polls for
  the authenticated ControlMaster and resumes the same job without duplicate
  submission;
- completed/failed jobs clear the active-job marker, while a completed project
  does not block submission of a later song;
- multitrack results default to `合奏`, with visible note counts and per-track
  mute, solo, and MIDI volume controls;
- `当前音轨` isolates the selected editor track, `全部启用` restores the full
  arrangement, and mixer state survives app restart;
- current audible mix export applies the same track selection and volume
  controls; complete multitrack export remains unchanged.

The mixer is a non-destructive MIDI audition surface. It does not claim the
predicted instrument names are correct and does not change MuScriptor.

## Task 009B2K: optional local compute

Implemented:

- each new song has three explicit compute choices: default Hyak GPU, local
  Apple GPU through Metal/MPS, and local CPU;
- the choice is persisted locally, but cannot change while a task is active;
- readiness checks the existing isolated MuScriptor environment, pinned model
  provenance, ffmpeg, and—when requested—MPS availability before launch;
- local work runs in a detached per-project process with reduced scheduling
  priority, bounded CPU-thread environment variables, a fixed project log,
  restart-visible status, and a user-confirmed stop action;
- PID, process-group, project identity, state path, log path, and bundle/run
  relationships are validated before status or cancellation actions;
- the local worker uses the same full-song MuScriptor decoding, lossless
  multitrack bundle, automatic bounded same-model gap recovery, and raw-result
  fallback contract as the Hyak private Beta;
- Slurm requirements remain enabled by default in gap recovery. A non-Slurm
  route is admitted only by the explicit local worker and records `local`
  execution provenance.

Verification boundary:

- the owner explicitly requested that the Mac remain available. No local
  MuScriptor inference, model load, or song processing was run;
- unit tests cover default-Hyak persistence, local command construction,
  readiness without GPU probing, state/path validation, and UI mode selection;
- `make check` passes 258 Python and 28 Swift tests with three expected skips.
  Strict Swift formatting and the signed release package pass;
- standalone XCUITest was attempted once but could not open its fixture while
  the already-running production app with the same bundle identifier was
  monitoring a live Hyak task. The production app was intentionally retained,
  and this slice does not claim GUI-session validation;
- read-only Hyak inspection found only Job `37744240` on L40. Its full-song
  MuScriptor pass succeeded before the job continued into bundle/gap
  processing. No job was submitted, cancelled, or altered for this task.

## Task 009B2P: canonical product notes and per-track tail cleanup

Implemented:

- a shared canonical-timeline projection clips crossing notes and excludes
  predictions beginning after the audio endpoint from UI, review, preview, and
  MIDI exports without rewriting source events;
- each track independently receives a cached cleanup diagnostic and orange
  badge. Selecting the track exposes only that track's action;
- pitched tracks retain conservative sustain merging. Drum tracks use a
  separate dense periodic-short-hit detector and collapse each flagged drum
  pitch to one short hit. Both are one-operation, undoable corrections.

Current-song evidence:

- the drums track has two candidate pitches and 14 in-timeline repeated hits.
  Twenty-eight additional drum events begin after the audio endpoint and are
  excluded automatically;
- electric bass has one 10-fragment sustain candidate. The already corrected
  clean-electric-guitar track remains a five-note sustained ending;
- the distinction is necessary: merging repeated drum hits into long MIDI
  notes would be musically incorrect. The UI separately warns that real drum
  patterns and rolls can resemble model repetition.

Verification:

- canonical clipping, melodic and percussion detection, both cleanup modes,
  undo, configured real-project diagnostics, and real drum-track MIDI export
  pass;
- full `make check` passes 265 Python and 36 Swift tests with three expected
  environment-gated skips. This implementation started no compute; the
  owner-triggered corrected five-gap request is running separately as Job
  `37751981` and was not altered.

## Task 009B2Q: instrument-constrained gap decoding

Implemented:

- automatic voice-gap recovery now passes `--instruments voice` into
  MuScriptor, so the model is constrained while generating notes rather than
  producing a full arrangement and discarding every non-voice event afterward;
- user-selected recovery passes the selected canonical track's instrument as
  the same allowlist, retaining the generic guitar, bass, and other-track path;
- the parent request and immutable child run record the instrument allowlist.
  Source bundles and previous recovery results remain unchanged.

Current-song diagnosis:

- completed Job `37751981` used the previous unconstrained route. It produced
  16 accepted voice candidates: two at `129.571–130.271` seconds and fourteen
  at `209.261–215.261` seconds. Three selected gaps returned zero;
- the child model did not place the owner-audible missing melody on any output
  track. Correct accompaniment output is therefore not a melody substitute;
- this change fixes the directed-decoding contract but does not claim the
  constrained rerun will recover every note. A new selected-gap run is needed
  to measure that result before considering a separated-vocal fallback.

Verification:

- focused automatic and selected-gap tests pass 15 cases, including exact
  `voice` and accompaniment allowlists;
- full `make check` passes 267 Python and 36 Swift tests with three expected
  environment-gated skips. No Hyak or local model job was submitted.

## Task 009B2R: task-focused note inspector

Implemented:

- the selected note's pitch, onset, offset, duration, and delete action now
  occupy the primary inspector surface;
- the confidence-review panel is absent when the selected model provided no
  confidence values. It remains available for tracks with real source
  confidence;
- model ID, run ID, and confidence provenance are retained under a collapsed
  `来源信息` disclosure;
- cross-track short-note and low-confidence hints are retained under one
  collapsed `高级诊断` row. Per-track trailing cleanup appears only when the
  current track actually has a candidate.

Verification:

- the rebuilt signed app was visually checked on the active private project.
  The previous `待复核 0/0` and full-height `整曲验收` blocks are gone, while
  direct note editing remains visible;
- the owner-submitted Hyak recovery remained `RUNNING` across the app restart;
- full `make check` passes 267 Python and 36 Swift tests with three expected
  environment-gated skips. Strict Swift formatting and `git diff --check`
  pass.

## Task 009B2O: canonical timeline repair

Implemented:

- canonical audio metadata is authoritative for product time. MIDI predictions
  can no longer extend the all-track timeline, bar/beat position, gap list, or
  trailing-sustain boundary;
- selected gaps ending at the audio boundary remain valid, while the backend
  still rejects genuinely out-of-range input;
- sustain merges end at the canonical timeline. Legacy `app-sustain-merge`
  corrections from the affected build are narrowly clamped on track open as
  one saved and undoable update.

Current-song evidence:

- canonical audio ends at `271.805147`; accompaniment events extend to
  `274.96`. The old UI therefore created a false `4:34` endpoint and an invalid
  fifth interval;
- the corrected five enhanced-voice gaps end no later than `271.805147`. A
  real-project `plan_selected_gaps` call accepts all five without writing a
  request or starting compute;
- the owner had already used the old sustain merge, so the legacy correction
  contains five app-generated notes ending at `274.96`; the targeted migration
  repairs only those tagged notes and preserves canonical output.

Verification:

- boundary, UI-duration, sustain-clamp, legacy-repair, and real-project checks
  pass;
- full `make check` passes 265 Python and 33 Swift tests with three expected
  environment-gated skips. No Hyak or local inference was started.

## Task 009B2N: gap launch repair and trailing sustain cleanup

Implemented:

- private-Beta startup now adds the validated repository root before dynamic
  worker imports, so the installed console entry point does not depend on its
  executable directory or inherited `PYTHONPATH`;
- import failures become bounded backend JSON, while readable operation errors
  are distinguished from malformed backend output in the Mac UI;
- the current-track review analyzes only conservative trailing same-pitch
  chains. An owner-confirmed action replaces each chain with one long note in
  a single reversible `.merge` operation, preserving all source event IDs and
  leaving canonical files untouched.

Current-song evidence:

- the failed click stopped at local request preparation with
  `ModuleNotFoundError`; Job `37746586` and its succeeded result were not
  replaced, and no recovery request was written;
- `clean_electric_guitar` has five ending pitch chains containing 121 events.
  The last portion repeats pitches `46, 58, 62, 65, 70` every `0.23` seconds
  from `270.12` through `274.96`. This confirms fragmentation rather than a
  drawing-only issue, while B2O establishes that predictions after
  `271.805147` also exceed the real audio timeline;
- the shipped detector reports exactly five groups and 121 fragments on this
  private result. It requires a tail-reaching chain, at least four notes, at
  least two seconds, a maximum 30 ms join gap, and predominantly short notes.

Verification:

- focused worker-import, gap-planning, conservative-detection, merge/undo, and
  source-preservation tests pass;
- the configured real-project test passes without saving a correction;
- full `make check` passes 264 Python and 31 Swift tests with three expected
  environment-gated skips. No compute job or model inference was started.

## Task 009B2M: user-selected targeted gap recovery

Implemented:

- every ≥3-second empty span of the selected canonical track is now shown with
  a checkbox. The owner can select all, clear all, or choose any subset and
  submit one recovery task;
- the selected compute mode is respected. Multiple gaps become bounded
  four-second-context windows inside one Hyak Slurm job or one local worker;
  neither the whole song nor one separate job per gap is required;
- recovery selects child MuScriptor events using the current track's
  instrument, so voice and normal accompaniment tracks share the same path;
- the source bundle is verified and immutable. The returned bundle preserves
  every track, adds only recovered candidates to the selected track, records
  their source windows, opens automatically, and can itself be used for a
  later targeted pass;
- one active project task is allowed. Previous terminal state is archived,
  login-node and non-allocation inference are refused, unsafe or nonempty
  target intervals are rejected, and Hyak reconnect uses the existing
  Terminal/Duo boundary.

Current-song evidence:

- `voice_auto_enhanced` contains 322 notes and five ≥3-second gaps:
  `0.00–60.51`, `81.75–120.09`, `123.34–130.72`, `209.26–215.73`, and
  `254.04–271.81` seconds;
- the previous UI exposed only the first four because of a display prefix.
  The new UI exposes all five. The first automatic `voice_gap_candidate` has
  zero notes, so an explicit user-selected second pass is a real missing
  product control rather than a duplicate of a successful result;
- a read-only plan over all five spans produced five bounded windows. No
  recovery job was submitted because the owner must choose the desired subset.

Verification:

- `make check` passes 263 Python and 29 Swift tests with three expected
  environment-gated skips;
- focused tests cover two selected gaps in one request, target-instrument
  filtering for accompaniment, rejection of overlapping or nonempty spans,
  immutable source bundles, task-stage reporting, UI command construction,
  selection controls, and real-project loading.
- one focused `/review` was invoked only for these Task 009B2M files. It
  returned no output for over eight minutes after the network interruption,
  so the stalled process was stopped rather than repeated. The bounded manual
  P0/P1 and secret/path review found no blocker.

## Task 009B2L: beat-aware editing and result acceptance

Implemented:

- an explicit current-track note-creation command inserts a one-beat note at
  the playback head, selects it, and records the action in the existing
  reversible correction log without changing canonical events;
- Beat This beat events are preserved with the tempo and meter maps. The
  detailed piano roll shows both second labels and musical bar/beat lines,
  while the transport reports representative BPM, meter, and current
  `bar/beat` position;
- old bundles with only the serialization defaults continue to load and are
  explicitly labeled as unanalyzed instead of being presented as detected
  rhythm;
- the Hyak private-Beta workflow runs the already pinned Beat This worker
  sequentially between full-song MuScriptor and automatic gap recovery. The
  rhythm run is canonical-audio-bound, included in worker provenance, used by
  performance MIDI, and fetched with the final result. A rhythm-only failure
  falls back to the explicit default grid while preserving the valid
  multitrack result;
- a whole-song acceptance panel summarizes and navigates low-confidence and
  unusually short note candidates across every normal product track. It does
  not auto-delete, reclassify, or count them as ground-truth errors.

Verification boundary:

- Beat This currently estimates beat count between downbeats with a
  denominator fixed to four. Common simple meters are useful estimates, but
  6/8 versus related compound groupings is not a verified distinction;
- old-code Job `37746586` was checked read-only and left unchanged. It
  completed `0:0` in `00:21:19`, was fetched successfully, and its result keeps
  the default rhythm grid; the next song submitted from this implementation
  receives the new analysis stage;
- tests cover rhythm binding, bar/beat math, cross-track issue classification,
  note create/save/undo, and pipeline-stage reporting. Swift Package and Xcode
  builds, strict formatting, signed packaging, and shell syntax pass;
- full `make check` passes 259 Python and 29 Swift tests with three expected
  environment-gated skips. The single focused `/review` found no remaining
  P0/P1 blocker.

## Task 009B2D: responsiveness, music library, and voice coverage

Implemented:

- existing local song projects appear on the start screen and in the sidebar,
  while external project access can persist through security-scoped bookmarks;
- project open, bundle/track selection, and MIDI preview generation prepare in
  background work with generation guards so stale results cannot replace a
  newer selection;
- editor materialization and melody gaps are cached, the same audio is not
  reloaded for every track click, transport observation is isolated, and the
  piano roll uses lazy 10-second sections;
- original and MIDI preview volume are independently adjustable;
- `voice` is labeled as a lead-vocal candidate. Gaps of at least three seconds
  are listed with seek controls and same-time activity from other tracks;
- login uses LaunchServices rather than AppleScript control of Terminal, and
  builds prefer a stable installed Apple Development signing identity.

The gap display is intentionally diagnostic. It never treats another predicted
track as ground-truth melody or changes canonical model events.

Task 009B2D evidence:

- the 349.85-second `STILL LOVE HER` result has 254 `voice` notes and four
  gaps of at least three seconds: `0.00–33.35`, `63.55–90.69`,
  `104.52–131.41`, and `195.14–349.85`, totaling `242.09` seconds;
- owner listening reports that detected voice notes are mostly accurate but
  long passages are missing. This supports a high-precision/low-coverage
  product diagnosis, not a formal accuracy percentage;
- all 24 Swift tests pass with three expected environment-gated skips, and
  both private real-project tests pass;
- final `make check` passes 247 Python and 24 Swift tests, a focused P0/P1
  review has no remaining blocker, and the Apple Development-signed release
  passes strict signature/plist validation and launches on the real project;
- no Hyak/model job, new dataset, retuning, or automatic cross-track merge was
  run.

## Task 009B2E: same-model directed voice-gap probe

Objective:

- keep the fetched full-song `voice` track immutable as `voice_raw`;
- rerun the same pinned MuScriptor model, beam size 4, prelude forcing, and
  no instrument allowlist only on frozen shorter clips around empty spans;
- shift any newly predicted `voice` events back to the original song timeline
  and store them only as `voice_gap_candidate`;
- measure added time coverage, then require owner listening before counting
  correct recovered notes or false positives;
- stop before source separation, GAME, training, fusion, or automatic merge.

Frozen preflight:

- canonical audio duration is `349.153719` seconds. The previous 349.85-second
  editor timeline came from predicted events extending beyond the audio and is
  not used as a clip boundary;
- four decode windows cover five target intervals using 279.223719 seconds of
  audio: one possible-instrumental intro negative control, the two middle
  omissions in one contextual clip, and the long tail split into two shorter
  clips;
- each clip carries four seconds of available context at its outer edges. The
  two middle target gaps keep the intervening detected phrase as model context;
- the private, ignored frozen config is
  `reports/task009b2e-muscriptor-gap-v2/config.json` inside the fetched project;
- preflight verifies all five targets contain zero overlapping `voice_raw`
  notes. No assumption that every target actually contains singing is made.

Acceptance:

- clipping and MuScriptor inference run only inside a Slurm compute
  allocation, never on the Mac or a login node;
- every child run preserves native output and an immutable manifest with the
  same model/decoding settings as the full-song private Beta;
- the parent probe binds the canonical audio, source `voice_raw`, frozen
  config, exact code snapshot, clip hashes, child manifests, and original-time
  mapping;
- the review bundle exposes `voice_raw` and `voice_gap_candidate` as separate
  tracks and explicitly records `automatic_merge_performed=false`;
- correct-recovery and false-positive counts remain `null` until the owner
  reviews the target spans.

Task 009B2E evidence:

- startup Jobs `37739953`, `37739955`, and `37740294` stopped before inference
  while fixing direct-script imports, the Hyak ffmpeg module, and Lmod
  `nounset` compatibility. They did not alter the source bundle;
- Job `37740313` ran for `00:18:49` on L40 node `g3115`. Its four child
  MuScriptor runs all succeeded with the frozen model and decoding settings:
  intro control 823 total events, middle gaps 2,686, tail A 4,039, and tail B
  2,582;
- the child results yielded 184 target-overlapping `voice_gap_candidate`
  notes: `0`, `52`, `52`, `80`, and `0` across the five ordered targets.
  Candidate union coverage is respectively `0`, `18.70`, `20.25`, `21.28`,
  and `0` seconds;
- total candidate coverage is 60.23 of 208.043719 seconds (28.95%) across the
  four non-control targets. This measures presence of candidate notes, not
  whether those notes are musically correct;
- Job `37740313` itself ended `FAILED 1:0` after successful inference because
  review MIDI generation tried to parse the older private-Beta minimal rhythm
  map as a fully provenanced canonical tempo/meter map. The compatibility fix
  enriched only the in-memory MIDI serialization points. It reused the
  fetched candidate JSONL on the Mac and did not repeat inference;
- `task009b2e-muscriptor-gap-v2-review` was then generated successfully and
  passed the real-project Swift loader with `voice_gap_candidate` explicitly
  selected. It exposes `voice_raw` and `voice_gap_candidate` separately and
  records `automatic_merge_performed=false`;
- the original `voice_raw` remains 254 events with SHA-256
  `25725cff2b738bee8d66514dc5fbde51e04cf1a6b5e74c490e52025de4b4d48c`;
- correct-recovery and false-positive counts are still `null`. Owner listening
  is the next and only decision point before considering BS-Roformer. GAME,
  source separation, training, fusion, retuning, and automatic merge were not
  run;
- final `make check` passes 253 Python and 24 Swift tests with three expected
  environment-gated skips. The single focused P0/P1 review found no remaining
  blocker.

## Task 009B2F: owner-approved enhanced voice

Objective:

- record the owner's listening decision without turning a subjective estimate
  into a formal accuracy metric;
- derive `voice_enhanced` from the immutable 254-note `voice_raw` plus the
  separately preserved 184-note `voice_gap_candidate`;
- expose raw, gap-only, and enhanced variants while preventing those three
  representations from sounding simultaneously in the mixer;
- prefer the owner-approved enhanced variant when its bundle is opened;
- stop without a separator, GAME, another model run, training, or hidden
  replacement of source events.

Evidence:

- the owner reports that the gap candidate subjectively recovers more than 95%
  of the previously missing notes, with a few notes still absent, and judges
  the overall recovery useful. This is an owner listening estimate on one
  song, not formal note recall or accuracy;
- ignored private evidence is stored in
  `reports/task009b2e-muscriptor-gap-v2/owner_review.json`;
- `task009b2f-owner-approved-enhanced` contains three explicit variants:
  `voice_raw` 254 notes, `voice_gap_candidate` 184 notes, and
  `voice_enhanced` 438 notes;
- every enhanced event has a new stable ID, retains the source event ID,
  identifies whether it came from raw or gap candidate, and records
  `owner_approved_derivation=true` plus
  `automatic_model_promotion=false`;
- the source `voice_raw` SHA-256 remains
  `25725cff2b738bee8d66514dc5fbde51e04cf1a6b5e74c490e52025de4b4d48c`.
  The enhanced JSONL SHA-256 is
  `db58e8c845e3cce0094899253001cfe1f64bbd8058f051a2c6e5d52e1ffda59b`;
- the app prefers `voice_enhanced` and treats the three voice variants as
  mutually exclusive during mix playback. Selecting raw or gap-only switches
  the audible variant instead of stacking duplicates;
- the real private-project loader and selected-track/arrangement MIDI export
  pass with `voice_enhanced`. All 25 Swift tests pass with three expected
  environment-gated skips;
- no Hyak job or model inference was submitted. BS-Roformer, GAME, training,
  and automatic model promotion remain unstarted;
- final `make check` passes 254 Python and 25 Swift tests with three expected
  environment-gated skips. Strict Swift formatting and `git diff --check`
  pass. The focused P0/P1 review found and fixed variant mute/solo semantics;
  no blocker remains.

## Task 009B2G: single-upload automatic voice-gap recovery

Objective:

- require only one user upload and one private-Beta Slurm job;
- preserve the immutable full-song MuScriptor run and every accompaniment
  track before attempting recovery;
- automatically plan bounded contextual reruns only for long empty spans in a
  non-empty `voice` track;
- keep raw, gap-only, and automatic-enhanced voice variants separately
  traceable while presenting one default main-melody track to ordinary users;
- publish the raw multitrack result if automatic planning, inference, or
  packaging fails;
- stop without source separation, GAME, training, new datasets, or an
  accuracy claim.

Implemented:

- `slurm/40_private_beta_muscriptor.slurm` now builds a raw source bundle,
  invokes the same pinned MuScriptor worker for conditional gap recovery
  inside the existing allocation, and rebuilds the raw final bundle on any
  recovery failure;
- the automatic planner uses a fixed eight-second minimum gap, four seconds
  of context, an 80-second target maximum, a 90-second window maximum, and an
  eight-target cap. These are bounded engineering defaults, not fitted quality
  thresholds;
- target events are clipped to source-empty intervals. `voice_auto_enhanced`
  uses new event IDs and records the source event, raw/candidate origin,
  automatic recovery status, absence of owner approval, and absence of model
  promotion;
- the self-contained final bundle contains auto-enhanced, raw, gap-only, and
  all original accompaniment tracks. Its convenience MIDI and the app's
  standard multitrack export contain only one voice representation;
- the private-Beta state remains backward compatible and reports
  `queued`/`full_transcription`/`gap_planning`/
  `automatic_gap_recovery`/`packaging`/terminal stages;
- the app prefers `voice_auto_enhanced`, hides raw and gap-only variants until
  the diagnostic toggle is enabled, and switches back to the preferred voice
  before hiding a selected diagnostic track.

Evidence:

- read-only planning on the fetched `STILL LOVE HER` raw bundle produced four
  clips and five targets matching the already reviewed manual probe shape:
  intro, the two middle gaps in one clip, and two bounded tail clips;
- no new model job ran. Reusing the completed 184 candidates produced ignored
  private bundle `task009b2g-automatic-product-dryrun` with nine tracks:
  `voice_auto_enhanced` 438, `voice_raw` 254,
  `voice_gap_candidate` 184, plus all six original accompaniment tracks;
- the real private-project Swift loader and selected-track MIDI export pass
  with `voice_auto_enhanced`;
- focused regression tests cover automatic derivation/provenance, bounded
  planning, accompaniment retention, self-contained paths, raw-state
  migration, phase detection, automatic-track preference, and mutually
  exclusive voice playback;
- final `make check` passes 256 Python and 25 Swift tests with three expected
  environment-gated skips. Strict Swift formatting, Slurm shell syntax, and
  `git diff --check` pass;
- the single focused P0/P1 review fixed one hidden-diagnostic playback issue
  and one failed-recovery status label. No blocker remains.

## Task 009B2H: Unicode-safe polling and explicit whole-version export

Implemented:

- project state accepts NFC/NFD-equivalent macOS project identifiers while
  preserving same-file local-path, manifest, remote-path, Job ID, identifier,
  symlink, and traversal validation;
- `保存修改` no longer looks like the file-download route. `导出整版 MIDI` is
  directly visible in the toolbar and selected-version sidebar, while
  current-track/current-mix exports remain under `其他导出`;
- the save panel names the selected recognition version and explains that the
  full export contains all accompaniment tracks with only one preferred
  melody representation.

Evidence:

- the old status failure was reproduced by passing the real
  `大沢誉志幸-ゴーゴーヘブン` project in decomposed Unicode form. The same
  production command passes after the fix;
- real Job `37743206` remained `RUNNING` in `full_transcription`, and the
  rebuilt app resumed polling the same job without another submission;
- the application-level whole-version export passed on the private nine-track
  `task009b2g-automatic-product-dryrun` bundle and wrote a valid MIDI file;
- `make check` passes 257 Python and 25 Swift tests with three expected skips.
  Strict Swift formatting, Apple Development-signed release packaging,
  plist/signature validation, and `git diff --check` pass.

Task 009B2C evidence:

- real owner-uploaded Job `37735878` completed `0:0` in `00:24:50` on L40
  node `g3096`; the production status command fetched it and the queue is
  empty;
- the new-song bundle retains 10,989 events across 7 predicted tracks:
  `voice` 254, `acoustic_guitar` 6,066, `acoustic_piano` 28,
  `clean_electric_guitar` 1,265, `drums` 2,115, `electric_bass` 1,231, and
  `synth_pad` 30;
- its convenience MIDI has 8 tracks including conductor, 10,989 note-ons, 6
  program changes, 2,115 percussion note-ons, and a 349.85-second timeline;
- production Swift selected-track/full-arrangement integration passes on this
  fetched project;
- normal Swift tests pass 21 cases with two expected environment-gated skips,
  and the formal XCUITest passes the complete editor/restart flow;
- the rebuilt ad-hoc-signed release app was launched with the prior 13-track
  real result and visually verified to show the all-track mixer.
- the single bounded Task 009B2C `/review` found no P0. It found one P1 in the
  direct-upload path after SSH expiry; that path now enters the same explicit
  relogin/resume state as background polling. No P2 expansion was performed.
- final `make check` passes 247 Python tests and 21 Swift tests, with two
  expected environment-gated Swift skips.

## Acceptance status

- Existing projects open without inference: **passed for 009A**.
- Editing, preview playback, and the piano-roll cursor stay synchronized:
  **passed for 009A application-flow verification**.
- Projects survive app restart: **passed**.
- Exported MIDI opens in two external applications: **passed**.
- Model/application unit tests cover failure, move/resize projection,
  edit/undo/redo, restart, and export: **passed**.
- Real waveform and confidence queue behavior: **passed for 009B1**.
- Formal XCUITest editor flow: **passed for 009B2A**.
- Import/job failure behavior: **implemented; real Hyak E2E passed**.
- Hyak login recovery and duplicate-submission prevention:
  **covered by persisted-state and production-flow tests**.
- All-track/current-track playback, mute/solo/volume, and mix export:
  **implemented and tested for 009B2C**.
- Prior-project reopening, responsive full-song loading, independent audition
  levels, and explicit `voice` gap navigation:
  **implemented and tested for 009B2D**.

### Task 009B2B evidence

- The immutable Task 002 run
  `muscriptor-large-beam4-hyak-37604080` was converted without inference into
  9 predicted instrument tracks containing all 7,667 events.
- `voice` is first/default and contains 493 events; other sparse or possibly
  incorrect accompaniment labels remain visible rather than being hidden or
  relabeled as ground truth.
- The resulting production bundle passes hash/path validation and the real
  Swift private integration test for both selected-track and complete
  arrangement export.
- Real Job `37734361` completed `0:0` in `00:17:28` on L40 node `g3098`.
  Its fetched output has 6,881 events across 13 predicted instrument tracks;
  `voice` is the default with 469 events.
- The final complete MIDI has 14 MIDI tracks including conductor, 12 program
  changes, and all 1,545 drum notes on percussion channel 10 (zero-based
  channel 9).
- The production `.app` builds and is ad-hoc signed. No credential entered the
  repository or project, and no model ran on the Mac or login node.
- Identical canonical audio/model/configuration produced different A100 versus
  L40 full-song event/label counts, so only the L40 product route is pinned;
  cross-hardware byte invariance is not claimed.
- Hyak host/root values are explicit local configuration, excluded from Git;
  the committed example contains placeholders only. Future jobs synchronize a
  clean `git archive` and bind the exact commit in the worker manifest.
- Persisted job fields are validated against the selected project and reject
  unsafe identifiers, path escape, mismatched identity, and symlinked state.
  Canonical tracks are never dropped merely because a result exceeds one
  General MIDI port.
- The single final `/review` found no P0 and five P1 issues. All five P1s were
  fixed with targeted regression coverage; three P2 suggestions were not
  pursued under the owner-directed closeout boundary.
- Final `make check` passed 247 Python tests and 18 Swift tests, with two
  expected private-environment skips. Seven of those Python tests are from
  preserved paused Task 007D worktree files and are not included in this Task
  009 commit.

Remaining non-blocking review notes:

- a failed terminal Slurm job does not yet fetch its remote logs automatically;
- the completion message can be more precise when fetched artifacts fail to
  open or a result has no `voice` label;
- the bundle limitation text still mentions preserved native MIDI even when
  the private job deliberately used `--skip-midi`; raw JSONL and normalized
  events are preserved, but that run has no native MIDI file.

## Evidence

- Hyak was reconnected only for a lightweight status check. The queue was
  empty; no Slurm task or model inference was submitted.
- `apps/AMTStudioMac` contains separate `AMTStudioCore`, `AMTStudioUI`, and
  `AMTStudio` targets. `scripts/build_app.sh` produced an ad-hoc-signed
  foreground `AMT Studio.app`; LaunchServices reported bundle
  `com.amtstudio.editor` as `Foreground`, and the window was visible.
- The real private project exposed three explicit canonical bundles. The
  selected `canonical-task005-d332b542` bundle opened four unranked tracks
  with `391/486/590/756` notes (`2,223` total). All bundle outputs,
  canonical audio, and source JSONL size/SHA-256 checks passed. Omitting the
  bundle ID correctly failed as ambiguous.
- Selecting `game` loaded 391 notes and a `4:25` original timeline. Automated
  accessibility verification started playback, observed the transport move
  from `0.0` to `6.512789...` seconds, and paused it.
- The original candidate JSONL remained untouched. App state is stored under
  `app/workspace.json`; the materialized correction and atomically rewritten
  immutable operation log live under `annotations/corrections/`.
- The real selected-track export is standard MIDI format 1, 960 PPQ, two MIDI
  tracks, 391 note-ons, 8,233 bytes, and SHA-256
  `5c16d7323b55d8d6f59172e5b3eaab30405e6660b633921bcb24f16c296295ce`.
  Mido parsed its full 252.799917-second timeline. GarageBand opened it as an
  imported track project, and Logic Pro opened it as a track window; both
  were then closed without saving.
- The focused review found no P0. All implementation-safety P1 issues were
  fixed: app-bundle foreground launch, workspace hash binding, optional v1
  event defaults and schema rejection, nested transport observation,
  short-note hit targets, visible preview errors, symlink-safe write paths,
  atomic operation logs, duplicate track IDs, and bounded MIDI tick
  conversion. The review's full-task formal-XCUITest evidence gap remains
  explicit in 009B rather than being misreported as complete.
- `swift test` passes 16 tests (the environment-gated private integration test
  is skipped in the normal run); the same private integration test passes
  when its explicit project/bundle/track variables are supplied.
- Repository-level `make check` passes all 216 Python tests plus the Swift
  suite.
- `xcrun swift-format lint --strict`, `codesign --verify --deep --strict`,
  `plutil -lint`, and `git diff --check` pass.

### Task 009B1 evidence

- The real private project's 4:25 canonical FLAC decoded into a visible,
  non-empty waveform without blocking playback or launching a subprocess.
  Accessibility exposed the label `原曲真实音频波形`; visual inspection showed
  the full-song envelope and synchronized red cursor.
- The selected GAME track exposed `0 / 0` review items and explicitly reported
  all 391 events as missing confidence. Direct artifact inspection confirmed
  that all four current canonical tracks contain zero non-null confidence
  values (`391/486/590/756` events respectively), so the app did not invent
  uncertainty or mix unknown values into the queue.
- A PCM fixture verifies peak placement. Queue regression coverage verifies
  threshold filtering, uncertainty-first ordering, time ordering for ties,
  exclusion of missing confidence, non-ASCII audio paths, and audio/timeline
  alignment when an edited note extends past the recording.
- Hyak was live on a login node with an empty queue during the lightweight
  status check. No Slurm job, model inference, or login-node compute ran.
- The single focused `/review` found no P0/P1 and four P2 issues. All four
  were fixed: audio-timeline scaling, generic login-node evidence, distinct
  confidence-order coverage, and non-ASCII waveform-path coverage.
- Final `make check` passes all 216 Python tests plus 17 Swift tests, with the
  one private integration test skipped by design. Strict Swift formatting,
  app packaging, plist/signature validation, and `git diff --check` pass.

### Task 009B2A evidence

- Xcode 26.1.1 built a real macOS application target plus
  `AMTStudioAppUITests`; `make mac-ui-test` executed one formal UI test with
  zero failures.
- The UI test generated a three-second WAV and a complete canonical project at
  runtime under a path containing Chinese text and spaces. The fixture was
  removed after the test and no private media entered Git.
- XCUITest observed the verified project and unique candidate track, real
  waveform with 2,048 decoded samples, piano roll, and source-confidence
  filter; playback advanced the transport slider before being paused.
- XCUITest navigated the one low-confidence note while leaving the
  no-confidence note outside the queue, edited its onset, exercised undo and
  redo, terminated the app, relaunched it, and confirmed both project and undo
  history restoration.
- The UI-test launch flag disables recent-project read/write, so the automated
  fixture does not replace the user's actual recent project.
- Repository-level `make check` still passes 216 Python tests plus 17 Swift
  tests with one expected private-integration skip. The XCUITest remains a
  separate explicit target because it requires full Xcode and a GUI session.
- The single focused `/review` found no P0/P1. Its two P2 findings were fixed:
  the UI test now waits for a non-empty decoded-waveform state, and the README
  returns to the repository root before invoking `make mac-ui-test`.

### Task 009B2I evidence

- Real Job `37743206` is locally sealed as `COMPLETED / succeeded`,
  `pipeline_stage=complete`, and `slurm_exit_code=0:0`; its final canonical
  bundle and automatic gap-recovery report are present. No duplicate job or
  new inference was submitted for the UI work.
- A fresh user defaults to Precision mode. A focused unit test switches to
  Spectrum, reconstructs `AppModel`, and verifies persistence without a
  project or active Job ID appearing.
- The signed app opened the real completed Japanese-named project in a
  1400 x 900 point window. Precision and Spectrum were both rendered and
  switched in the Appearance sheet without project reload.
- The final visual comparison is recorded in `design-qa.md`. The first pass
  identified toolbar density and system-blue rendering as P2 issues; the
  consolidated menus and theme-bound waveform/note colors removed both.
- `make check` passes 257 Python and 26 Swift tests with three expected
  environment-gated Swift skips. `swift-format --strict`, release signing,
  plist validation, and `git diff --check` pass.

### Task 009B2J evidence

- The signed release app opened the real completed Japanese-named project and
  rendered all eight normal product tracks as vertically stacked piano-roll
  lanes. Each lane showed its real note count and full-song note distribution;
  one shared red playhead aligned every lane to the decoded waveform timeline.
- Selecting a lane changes the current track without rewriting source events.
  The explicit detail action returns to the existing editable piano roll, so
  note drag, left/right resize handles, inspector editing, undo, and redo are
  retained rather than duplicated in the dense overview.
- Raw and gap-only voice diagnostic variants remain available through the
  existing advanced switch but are excluded from the default overview. This
  matches standard arrangement playback and export, which use at most one
  melody representation.
- A unit test checks full-song time clamping, pitch normalization, and note
  geometry inside a lane. The XCUITest verifies the overview/detail switch and
  then completes playback, edit, undo/redo, termination, and restart recovery.
- The pre-existing appearance source file is now included in the Xcode project;
  the formal UI-test target and Swift Package Manager therefore compile the
  same theme-enabled application.
- The public default branch was synchronized after replacing the remaining
  tracked account-specific Hyak path with portable placeholders. Local Hyak
  configuration, credentials, private media, and result bundles remain ignored.
- `make check` passes 257 Python and 27 Swift tests with three expected
  environment-gated Swift skips. Strict Swift formatting, `make mac-app`,
  signature/plist validation, `git diff --check`, real-project visual QA, and
  the standalone XCUITest pass.

## Task 009B2V: configurable Hyak wall time

Objective:

- reduce unnecessary queue cost from the former three-hour default;
- let the owner set the maximum runtime for future Hyak whole-song and
  selected-gap tasks without editing Slurm files;
- keep local GPU/CPU behavior and the reproducible standard L40 route
  unchanged;
- move the currently blocked, never-started job only when a live read-only
  scheduling comparison identifies a materially faster compatible GPU.

Evidence:

- Job `37804031` was pending with `AssocGrpGRES` and no start estimate.
  Test-only submissions estimated normal L40 at
  `2026-07-28T06:22:38 PDT`, L40S at `2026-07-27T20:19:38 PDT`, and
  checkpoint A40/A100 immediately;
- the old job had zero runtime before cancellation. Replacement Job `37805247`
  requests exactly one A100, uses a one-hour limit, and began on an 80 GB A100
  within seconds. The app state follows the replacement job and reports
  `RUNNING / full_transcription`;
- both product Slurm entrypoints now default to `01:00:00`. The Swift setting
  persists a bounded 1–24 hour value and passes it through the Python CLI to
  `sbatch` for both new task kinds;
- local compute arguments do not contain the Slurm time option. Unit tests
  cover the default, persistence, command construction, and Python boundary;
- `make check` passes 277 Python and 38 Swift tests with three expected
  environment-gated skips. Strict Swift formatting, Slurm shell syntax,
  Python compilation, and `git diff --check` pass.

## Task 009B2W: automatic Hyak GPU selection

Objective:

- move the repeated manual GPU queue comparison into the product submission
  path so a normal user does not need Codex or Slurm expertise;
- compare only resource routes already verified for the MuScriptor workload;
- keep the selected resource auditable and preserve a safe stable fallback.

Frozen rule:

- discover the current user's compatible Slurm associations immediately before
  each whole-song or selected-gap submission;
- probe L40, L40S, A40, and A100 using no-allocation `sbatch --test-only` with
  the same account, partition, QOS, GPU, and wall-time arguments that the real
  job will receive;
- choose the earliest estimated start. For candidates within five minutes of
  that earliest start, use the fixed performance order
  `A100 > L40S > L40 > A40`;
- mark checkpoint A100/A40 as preemptible. If discovery or every estimate
  fails, submit through the existing stable L40 route.

Evidence:

- the live planner compared four compatible resource plans at
  `2026-07-27T16:54` PDT and selected checkpoint A100 with a one-second
  estimated wait. No test job was left queued, and existing Job `37805247`
  continued unchanged;
- a first live check exposed that Hyak writes the test-only estimate to stderr.
  The backend now captures that channel explicitly, and a regression fixture
  fails if the redirection is removed;
- state validation and Swift decoding preserve GPU, partition, estimated wait,
  preemption risk, and the human-readable selection reason across refresh and
  app restart. The sidebar displays those fields; settings describe the
  eligible GPU set and stable fallback;
- local-only jobs do not enter this planner. It adds no personal Hyak identity,
  host login, private path, credential, password, or Duo data to public source;
  candidate accounts come from live Slurm associations;
- `make check` passes 281 Python and 38 Swift tests with three expected
  environment-gated skips. Strict Swift formatting, signed `make mac-app`,
  plist/signature validation, Python compilation, and `git diff --check` pass.

## Task 009B2X: three-stage gap-recovery comparison

Objective:

- let the owner hear the exact effect of each existing recovery filter instead
  of changing thresholds from aggregate counts;
- preserve the completed model run, source bundle, and current product melody;
- make raw generation, accompaniment filtering, and monophonic constraint
  directly comparable as separate tracks.

Frozen comparison:

- source recovery run:
  `gap-recovery-20260728T000154Z-244743c9`;
- `gap_raw_candidate`: all 864 saved directed MuScriptor candidates;
- `gap_accompaniment_filtered`: 234 candidates reconstructed by removing the
  exact 630 `shadowed_event_ids` recorded by the saved soft-mask report;
- `gap_monophonic_candidate`: the 161 constrained candidates already saved by
  the completed run after another 73 path rejections;
- diagnostic tracks are alternatives, not an arrangement, and none may become
  the default product melody from this comparison alone.

Evidence:

- the deterministic builder rejects incomplete runs, mismatched config/audio
  hashes, unknown shadow IDs, inconsistent counts, and a final set that is not
  a subset of the accompaniment-filtered set;
- each comparison track receives unique derived event IDs while retaining its
  original event ID and model lineage. This satisfies the production loader's
  global event-ID contract without modifying source JSONL;
- real private bundle
  `gap-recovery-20260728T000154Z-244743c9-stage-comparison` contains exactly
  864 / 234 / 161 notes plus three independently valid MIDI files;
- the production project loader opened the real raw stage and exported a valid
  MIDI. Swift playback regression proves selection of one stage excludes the
  other two;
- full `make check` passes 282 Python and 39 Swift tests with three expected
  environment-gated skips. The signed release app was rebuilt and opened on
  the real project. No Hyak job, local model, dataset experiment, or training
  work ran.

## Task 009B2Y: raw gap recovery without a count cap

Objective:

- apply the owner's listening decision that the raw generated recovery stage
  is better than the accompaniment-filtered and monophonic alternatives;
- remove the fixed 32-note-derived admission ceiling that rejects long empty
  spans independently of their duration;
- keep recovery bounded, reproducible, non-destructive, and auditable.

Frozen product rule:

- automatic and user-selected voice-gap runs use every raw voice-constrained
  candidate inside the planned windows as the product candidate set;
- no candidate-count cap is applied;
- accompaniment-filtered and monophonic-constrained stages remain saved
  diagnostic alternatives and do not control the product merge;
- historical bundles carrying `rejected_excessive_voice_growth` remain
  diagnostic, while new bundles record
  `accepted_owner_selected_raw_generation`;
- the source bundle is immutable, canonical audio bounds remain authoritative,
  and no result is represented as an accuracy claim.

Evidence:

- the owner listened to the exact 864 / 234 / 161-note comparison tracks and
  selected the 864-note raw generation as best;
- Python regressions accept 841 new notes without a maximum field and merge
  33 candidates into a two-note source. Swift regression accepts a 1,179-note
  uncapped new bundle while continuing to reject an explicitly historical
  old-policy bundle;
- the completed real recovery was rematerialized without inference as
  `gap-recovery-20260728T000154Z-244743c9-raw-product`.
  Its `voice_auto_enhanced` contains 1,186 notes, exactly 322 source notes plus
  864 raw candidates. Its claims record raw selection, no soft-mask use for
  the product, an automatic merge, and no source overwrite;
- the production project loader opened the real product track and the complete
  MIDI passed validation. The signed app was rebuilt and opened on the project;
- full `make check` passes 282 Python and 39 Swift tests with three expected
  environment-gated skips. No Hyak job, local inference, dataset experiment,
  or model training ran.

## Task 009B2Z: cross-version track management and per-track repair

Objective:

- remove experiment-only “diagnostic version” concepts from the ordinary
  product workflow without deleting their immutable evidence;
- let a user assemble a preferred arrangement from tracks in different
  recognition versions without overwriting any model output;
- put create/delete note actions together and expose conservative fragment
  repair from each track's own settings.

Implemented:

- the product version list now contains only eligible bundles. Rejected
  historical recovery and stage-comparison artifacts remain on disk and
  traceable but are not ordinary navigation choices;
- `管理版本与音轨` copies a materialized track from another eligible version,
  merges at least two current tracks with a participant chosen as the resulting
  instrument, or deletes a track. Each action atomically writes and verifies a
  new `custom-*` canonical bundle; no source bundle is modified;
- copied and merged notes receive unique derived IDs while preserving source
  bundle, source track, source event IDs, model lineage, and saved edits.
  Merge is an explicit union with no hidden overlap deletion. The selected
  instrument is applied to both track metadata and every merged event;
- deletion refuses the last visible product track. Generation guards prevent
  a completed background operation from reopening an old project after the
  user has switched projects;
- the detailed piano-roll toolbar now places `删除音符` beside `新增音符`.
  Every visible track has an `音轨设置` menu. Pitched tracks can confirm a
  whole-track same-pitch sustain-fragment repair; drums retain the separate
  trailing-repeat collapse. Both are persisted as one undoable edit.

Evidence:

- focused tests cover copy/merge/delete, immutable source bytes, merged MIDI,
  instrument consistency, last-visible-track protection, cross-project
  completion races, and interior versus separated same-pitch patterns;
- both configured real-project tests open
  `gap-recovery-20260728T000154Z-244743c9-raw-product` on
  `voice_auto_enhanced` and export valid MIDI;
- final `make check` passes 282 Python and 44 Swift tests with three expected
  private-environment skips. Strict Swift formatting, `git diff --check`,
  release packaging, plist validation, signing, and signed-app launch pass;
- the one `/review` invocation was stopped when it expanded into paused
  Task 007D. Its two relevant P1 findings were fixed with targeted regressions;
  no second or expanded review was run;
- no Hyak job, local inference, dataset experiment, or training work ran.

## Task 009B3A: optional GAME singing-voice product route

Objective:

- expose the already pinned and evaluated GAME worker as an optional
  singing-voice product path without changing the default MuScriptor
  multitrack workflow;
- let an existing project add one GAME voice version non-destructively;
- keep heavy compute, private model assets, licensing, and model-specific
  limitations explicit.

Frozen product rule:

- `multitrack` remains the default next-song recognition mode;
- `game_vocal` runs only on a Hyak Slurm compute node and produces one `voice`
  product track;
- GAME always receives the pinned BS-Roformer `vocal_quality_a` stem, never the
  canonical full mix;
- GAME output is an alternative singing-voice candidate. It is not
  automatically fused with, stacked over, or promoted above MuScriptor voice;
- an existing project's GAME version can be combined only through the
  explicit cross-version copy workflow;
- confidence and velocity stay unavailable, and no transcription accuracy is
  claimed from model output alone;
- submission rejects an existing active project job before remote mutation and
  excludes preemptible checkpoint GPUs because the sequential chain is not
  checkpoint-resumable;
- source and app code may remain public, but GAME weights remain private
  non-commercial research assets under CC-BY-NC-SA-4.0.

Implemented:

- `RecognitionMode` is persisted in the Mac app and exposed in the toolbar,
  sidebar, and settings. Selecting GAME automatically chooses Hyak and blocks
  later MPS/CPU selection while that mode is active;
- `amt-private-beta start --recognition-mode game_vocal` creates a new project,
  while `start-game-vocal` adds a new version to an existing project;
- submission discovers exactly one pinned GAME provenance file and exactly one
  BS-Roformer model directory in the user's private Hyak storage. Ambiguous or
  missing assets fail before submission;
- `slurm/43_private_beta_game_vocal.slurm` sequentially runs source separation,
  GAME seed 3407, optional Beat This analysis, and canonical single-track
  packaging. It refuses login-node execution;
- job state, progress polling, result fetch, automatic project reopening, and
  product labeling understand source-separation and GAME phases.

Evidence:

- focused Python tests cover the GAME bundle, one-track claims, CLI modes,
  Hyak-only state validation, private asset fields, and pipeline phase
  reporting;
- Swift tests cover default/persisted recognition mode, automatic Hyak
  selection, local-compute refusal, new-song CLI arguments, and the
  existing-project GAME command;
- `make check` passes 278 Python and 44 Swift tests with three expected private
  environment skips. Slurm shell parsing, Python compilation, and
  `git diff --check` pass;
- one isolated `/review` found two P1 submission-safety issues and three
  directly related P2 contract/evidence issues. Active-job preflight,
  non-preemptible GAME planning, bundle labeling, absolute private-asset
  validation, and the isolated test count were corrected; no second or
  expanded review ran;
- no Hyak or local inference job was submitted. Real source-separation/GAME
  quality remains an explicit owner-triggered listening check.
## Task 009B3J: duration-aware wall time and timeout continuation

Objective:

- avoid predictable Slurm TIMEOUT failures for longer songs without forcing a
  beginner to estimate runtime for ordinary uploads;
- require an explicit owner choice for unusually long audio;
- resume a timed-out product job only when a completed, immutable stage can be
  proven and reused.

Frozen product rule:

- the configured Hyak wall time is a minimum;
- `duration <= 7 min` uses at least 1 hour, `7 < duration <= 14 min` uses at
  least 2 hours, and `14 < duration <= 21 min` uses at least 3 hours;
- `duration > 21 min` must display a modal and receive a 1–24 hour user
  confirmation before it enters the queue;
- only `TIMEOUT` MuScriptor full-multitrack jobs with an existing raw canonical
  bundle are resumable in this task;
- continuation archives partial automatic-gap artifacts with the failed Job
  ID, reuses the full transcription and raw bundle, and restarts automatic gap
  recovery. It never overwrites raw evidence or silently reruns full-song
  inference;
- GAME and pre-checkpoint timeouts remain explicit full retries until they gain
  their own verified checkpoint contract.

Evidence:

- Swift boundary tests cover exactly 7, just above 7, exactly 14, just above
  14, exactly 21, above 21, configured minimums, and manual suggestions;
- Python tests prove raw-bundle reuse, old-attempt preservation, new Job
  lineage, and the dedicated continuation Slurm entry point;
- final `make check` passes 295 Python and 57 Swift tests with three expected
  private-environment skips;
- the formal Xcode project build and packaged release app both succeed;
- no new Hyak job, local inference, dataset experiment, or training work ran.

## Task 009B3K: install the selected macOS application icon

Goal:

- keep the owner-selected cover artwork unchanged;
- use that artwork as the actual Finder, Dock, and application-dialog icon;
- ensure both supported build paths package the same icon.

Frozen product rule:

- `AMTStudioCover.png` remains the single visual source selected by the owner;
- `AMTStudioIcon.icns` is a mechanical multi-resolution conversion of that
  source, not a new design;
- `Info.plist` declares `CFBundleIconFile=AMTStudioIcon`;
- both the formal Xcode resource phase and `build_app.sh` must include the icon.

Evidence:

- `make check` passes 295 Python and 57 Swift tests with three expected
  private-environment skips;
- the formal Xcode project build and packaged release app both succeed;
- the packaged Info.plist resolves `AMTStudioIcon`, the 2.4 MB `.icns` resource
  is present, and strict code-signature verification succeeds;
- no Hyak job, model inference, or product-data change ran.

## Task 009B3L: stable active-task timing and coarse completion estimate

Goal:

- stop active-task elapsed timers from resetting during background refresh;
- show a useful but scientifically cautious completion estimate on the
  processing-flow page.

Frozen product rule:

- elapsed time is anchored to backend `submitted_at`; filesystem modification
  time remains only a library sorting and inactive-project recency signal;
- missing legacy timestamps show no fabricated elapsed counter;
- completion is presented as a range, not an exact promise;
- the range may use audio duration, task type, GPU, initial queue estimate, and
  current pipeline stage, and the UI must disclose congestion and recovery
  uncertainty;
- the feature is presentation-only and must not query, cancel, resubmit, or
  otherwise alter Hyak work.

Evidence:

- tests prove two refreshed project snapshots with different `modifiedAt`
  values produce the same elapsed time from one `submittedAt`;
- tests cover fractional Python ISO-8601 timestamp parsing and verify that a
  packaging-stage estimate is earlier than an otherwise identical
  full-transcription estimate;
- `make check` passes 295 Python and 59 Swift tests with three expected
  private-environment skips;
- the formal Xcode project and packaged release app both build successfully;
- no Hyak job, model inference, or product-data change ran.
