# Task 009: Native macOS application shell

Status: private Beta usability implementation complete — Task 009A, 009B1,
009B2A, bounded 009B2B MuScriptor inference, 009B2C reconnect/mixer, and
009B2D responsiveness/library/voice-coverage work are complete. Owner product
acceptance is next.

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
