# Task 009: Native macOS application shell

Status: private Beta usability implementation complete — Task 009A, 009B1,
009B2A, bounded 009B2B MuScriptor inference, 009B2C reconnect/mixer, and
009B2D responsiveness/library/voice-coverage work are complete. Task 009B2E
same-model directed gap recovery and Task 009B2F owner-approved enhanced voice
productization are complete. Task 009B2G single-upload automatic same-model
gap recovery is complete for future private-Beta jobs.

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
