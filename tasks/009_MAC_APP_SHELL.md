# Task 009: Native macOS application shell

Status: in progress — Task 009A editor shell verified; Task 009B backend
integration remains blocked by Gate 4

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

## Task 009B: gated backend work

Not started:

- audio import;
- a versioned local job API;
- background inference progress and cancellation;
- model-pack/worker discovery and failure states;
- audio waveform and confidence review queue;
- formal XCUITest coverage;
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
- Formal XCUITest, import/job failure, waveform, and confidence queue:
  **pending in 009B**.

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
