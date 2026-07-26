# Task 009: Native macOS application shell

Status: in progress — Task 009A editor shell, Task 009B1 model-independent
review surfaces, and Task 009B2A formal UI-flow verification are complete;
backend integration remains blocked by Gate 4

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

Not started:

- audio import;
- a versioned local job API;
- background inference progress and cancellation;
- model-pack/worker discovery and failure states;
- MusicXML after notation tests.

These items cannot silently select the rejected fusion route or move model
compute onto the Mac. Research inference remains on Hyak compute nodes.

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
- Import/job failure behavior: **pending in gated 009B2B**.

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
