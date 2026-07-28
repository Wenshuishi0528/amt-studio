# Project status

Current product milestone: Task 009B3I adds cross-song track copying and
multi-project Hyak submission/monitoring to AMT Studio 0.2.0
Research status: Gate 4 remains not passed for the rejected fusion routes; no
new dataset, fusion, retuning, or training work is in the product critical path
Current task: complete and package non-destructive cross-song track reuse plus
Slurm-controlled multi-job Hyak operation
Next task: owner workflow confirmation; do not submit music or resume model
work without a new request
Current branch: `main`

Implemented for Task 009B3I:

- the current selected track can be copied into a chosen eligible version of a
  different completed song. The destination receives a verified `custom-*`
  version; source and target recognition versions remain immutable;
- copied events preserve absolute onset/offset times even beyond the target
  song ending, including single-track and whole-version MIDI export, while
  provenance records the source project, bundle, track, events, and model/edit
  lineage;
- the prior one-active-Hyak-job guard was a client restriction, not a proven
  Hyak quota. Hyak uploads remain serialized, but successful submissions now
  immediately advance the next Hyak item. Slurm controls actual parallel
  running versus `PENDING`; local CPU/GPU work remains serialized;
- all active project paths persist locally and one fleet monitor refreshes and
  retrieves every submitted job rather than only the most recent one;
- focused state review also verifies that a background terminal job releases
  queued local work and removing the viewed project does not stop monitoring
  other active Hyak projects;
- `make check` passes 294 Python and 56 Swift tests with three expected private
  integration skips. No model or Hyak job was launched.

Implemented for Task 009B3H:

- the selected sky-blue/champagne-gold artwork is now a project-owned resource
  shown on the library home, sidebar brand header, and Settings about card;
- the app visibly reports `v0.2.0 · wenshuishi26`, while Settings also reports
  build `2`. The same version and author are present in the plist, Xcode build
  settings, and Python package metadata;
- the signed release app contains a byte-identical copy of the 1254 x 1254
  cover. Both source and package resource hashes are
  `ea9d44fd188d9a9ab915633ba06ec3171ea338fc7b69791670d20f2bddf26c23`;
- `make check` passes 294 Python and 52 Swift tests with three expected private
  integration skips. Formatting, plist, packaging, resource, signature, and
  diff validation pass.

Implemented for Task 009B3G:

- the song picker accepts one or many audio files. Every selection becomes a
  local queue item with its recognition mode, compute target, and Hyak time
  limit frozen at enqueue time;
- only one project task is active. A succeeded, failed, cancelled, timed-out,
  preempted, or otherwise terminal task automatically releases the next
  waiting song; a failed local submission is retained for retry but does not
  block later waiting items;
- pending items and security-scoped bookmarks persist locally across app
  restarts. An item interrupted during submission confirmation is restored as
  manual-retry-only, preventing an ambiguous restart from creating a duplicate
  Hyak job;
- the sidebar shows the ordered queue, frozen configuration, submission state,
  retry, and removal controls. Recognition and compute settings remain
  editable for future queue additions while an existing task runs;
- the release app was rebuilt and relaunched with no saved queue, so the
  owner's already active task was monitored rather than replaced. No model job
  was submitted by this implementation;
- `make check` passes 294 Python and 52 Swift tests with three expected private
  integration skips.

Implemented for Task 009B3F:

- code synchronization now protects persistent remote `.uv-cache`, worker
  `.venv`, and model-source `checkouts` directories from `rsync --delete`,
  removing the expensive traversal/deletion path that caused the timeout;
- a code snapshot is marked complete only after `rsync` exits successfully.
  The marker is written atomically and carries `sync_complete: true`; the old
  marker written at transfer start is never trusted as completion;
- songs submitted from the same committed app version reuse the verified
  remote snapshot instead of synchronizing identical code again. A genuinely
  new commit receives a 15-minute bounded first-sync window;
- the failed retry completed local ingestion but did not upload the project or
  submit Slurm work. SSH remains online and the user's queue is empty;
- `make check` passes 294 Python and 50 Swift tests with three expected private
  integration skips.

Implemented for Task 009B3E:

- the macOS backend now launches `uv` with a deterministic child `PATH` that
  includes the executable's own directory, Apple Silicon and Intel Homebrew
  locations, macOS system locations, and the inherited path without duplicates;
- this fixes the real Finder-launch failure where `ffprobe` existed at
  `/usr/local/bin/ffprobe` but the GUI process could not discover it. The failure
  occurred during local ingestion, before upload or Slurm submission;
- true audio-tool and project-ingest failures are returned as structured JSON,
  so the app shows a concise operation error instead of a Python traceback;
- `make check` passes 292 Python and 50 Swift tests with three expected private
  integration skips. A minimal GUI-like environment resolves both `ffprobe`
  and `ffmpeg`.

Implemented for Task 009B3D:

- the latest selected-gap attempts reached MuScriptor successfully but emitted
  an existing empty native JSONL. Bounded recovery now treats that as a valid
  zero-candidate outcome and creates an unchanged derived version; whole-song
  recognition still fails closed on an empty model output;
- targeted result state records the recovered candidate count. The app now
  distinguishes “completed with no new notes” from infrastructure failure, and
  fetched failed-run evidence can expose the model's actual error instead of a
  generic dialog;
- canonically equivalent NFC/NFD request paths are validated by filesystem
  identity, removing the second local status-reading failure seen on the
  Japanese project name;
- every pitched track can rescan and preview all interior or trailing
  same-pitch continuous-note fragments, report the exact replacement count,
  rebuild them as one saved undoable edit, and reopen the project to verify
  persistence. Drums retain their separate repeated-hit rule;
- full `make check` passes 291 Python and 49 Swift tests with three expected
  private-integration skips. The single bounded review found one P1
  request-directory symlink escape; containment is restored without losing
  NFC/NFD compatibility. The latest real task retry is recorded separately
  after the corrected committed worker is synchronized.

Implemented for Task 009B3C:

- submitting or restoring an unfinished task now opens the task-progress page
  even when an older bundle already provides an editor. The task continues
  while the user switches between `查看已有结果` and `任务进度`;
- GAME large shows six explicit phases: submit, GPU wait, BS-Roformer vocal
  separation, GAME transcription, rhythm analysis, and package/fetch;
- remote artifact polling now reports the phase currently executing rather
  than the preceding completed artifact. A focused backend regression and a
  Swift restore/switch regression pass;
- full `make check` passes. No model job was submitted, cancelled, or changed
  by this UI/state repair.
- the single focused review found one P1 polling regression and two directly
  related P2 display errors. Polling now preserves the user's selected page,
  targeted recovery has truthful phases, and the progress title stays bound
  to the active job project.

Implemented for Task 009B3B:

- official `GAME-1.0-large` is independently hash-pinned for product jobs;
  historical medium research pins remain unchanged;
- discovery includes the deployed private Hyak model layout and gives separate
  errors for absent versus duplicate large provenances;
- the track settings menu no longer caches a disabled “no fragments” state.
  Every pitched track can rescan the whole timeline and repair confirmed
  sustain fragmentation; drums retain conservative tail-repeat handling;
- focused Python and all 44 Swift tests pass. Hyak setup Job `37810626`
  completed on an A40 compute node in 6m59s with CUDA, GAME imports, and every
  pinned large file verified. Product discovery resolves the unique large
  provenance and separator model; no song inference was submitted.

Implemented and verified for Task 009B3A:

- the next-song recognition setting now offers `完整多轨（MuScriptor）` and
  `主唱旋律单轨（GAME）`. MuScriptor remains the persisted default. Choosing
  GAME automatically selects Hyak because this route is not supported by the
  Mac MPS/CPU worker;
- one product Slurm job runs the pinned BS-Roformer `vocal_quality_a`
  separator, then the isolated GAME worker with seed 3407, then optional Beat
  This rhythm analysis and one-track canonical MIDI packaging. No model runs
  on the Mac or a Hyak login node;
- an existing project can create a new GAME-only recognition version without
  modifying any current bundle. The existing cross-version track manager can
  then copy its `voice` track into a chosen multitrack version; no automatic
  fusion or double-voice playback is introduced;
- GAME output is labeled singing-voice-only, carries no invented confidence or
  velocity, and remains bounded to private non-commercial research. Public
  source code contains neither GAME/BS-Roformer weights nor personal Hyak
  identity, paths, passwords, or Duo data;
- GAME submission refuses to replace an active project job and excludes
  preemptible checkpoint GPU plans because this sequential chain is not
  checkpoint-resumable;
- `make check` passes 278 Python and 44 Swift tests with three expected
  private-environment skips. Slurm shell syntax, Python compilation, and
  `git diff --check` pass. One isolated `/review` completed and its two P1 plus
  three directly related P2 findings were fixed. No Hyak or local model job
  was submitted, so real source-separation/GAME output quality remains for an
  owner-triggered run.

Implemented and verified for Task 009B2Z:

- old rejected and three-stage experiment bundles remain immutable evidence
  but are hidden from the ordinary version list. The app no longer asks a
  normal user to understand a “diagnostic version”;
- `管理版本与音轨` copies one product track from another version into the
  current arrangement, merges two or more current tracks while letting the
  user choose the resulting instrument, or removes a track. Every action
  creates a new `custom-*` canonical bundle; source versions and saved edits
  are materialized but never overwritten;
- merged tracks keep every source note and provenance without automatic
  overlap deletion. The selected instrument is applied consistently to both
  the track and its events. The app refuses to remove the last visible product
  track and cannot jump back to an old project if the user changes projects
  while an arrangement operation finishes;
- `删除音符` now sits beside `新增音符` in the current-track editor. Each track
  has an `音轨设置` menu with a confirmed, saved, undoable repair for detected
  same-pitch sustain fragmentation; drums retain their separate conservative
  trailing-repeat collapse instead of being converted to long tones;
- final `make check` passes 282 Python and 44 Swift tests with three expected
  private-environment skips. Strict Swift formatting, `git diff --check`, the
  signed app build, and both configured real-project open/export paths pass.
  No Hyak or local model job ran.

Implemented and verified for Task 009B2Y:

- after hearing all three saved stages, the owner selected the 864-note raw
  generation as the best gap-recovery result. Automatic and user-selected
  voice-gap recovery now use that raw stage for the product while continuing
  to save accompaniment-filtered and monophonic-constrained alternatives only
  as diagnostic evidence;
- the former `max(32, source / 10)` admission rule has been removed end to end.
  Candidate admission records `raw_generated` and applies no count limit;
  historical bundles explicitly rejected under the old rule remain diagnostic
  and are not silently reclassified;
- the change does not make recovery unrestricted across the song: decoding
  remains voice-constrained, only detected or user-selected empty windows are
  processed, canonical audio bounds are enforced, and source bundles remain
  immutable;
- without rerunning a model, the completed real recovery was materialized as
  `gap-recovery-20260728T000154Z-244743c9-raw-product`. Its enhanced voice has
  1,186 notes: the preserved 322-note source plus all 864 raw candidates.
  The production loader opened it and its complete MIDI is valid;
- full `make check` passes 282 Python and 39 Swift tests with three expected
  environment-gated skips. The signed app was rebuilt and opened on the real
  project; no Hyak or local inference ran.

Implemented and verified for Task 009B2X:

- a completed targeted recovery can now be materialized deterministically as
  a diagnostic-only comparison bundle without rerunning MuScriptor or changing
  its immutable source artifacts;
- the saved soft-mask report reconstructs all three exact stages: 864 raw
  generated notes, 234 notes after removing 630 accompaniment shadows, and 161
  notes after rejecting another 73 events with the monophonic-path constraint;
- the app displays the three stages as separate tracks and keeps them mutually
  exclusive during arrangement playback. Each stage also has a separate MIDI
  file for outside inspection;
- the real private project contains
  `gap-recovery-20260728T000154Z-244743c9-stage-comparison`. A configured
  project-loader test opened its raw track and exported valid MIDI; the source
  bundle and current 322-note product melody remain unchanged;
- full `make check` passes 282 Python and 39 Swift tests with three expected
  environment-gated skips. The signed release app was rebuilt and opened on
  the real song, and no Hyak or local inference ran.

Implemented and verified for Task 009B2W:

- immediately before each whole-song or selected-gap `sbatch`, the backend
  discovers the current user's compatible Slurm associations and runs
  no-allocation `sbatch --test-only` probes with the exact resource arguments
  that the real job would use;
- the admitted set is deliberately bounded to the verified 48 GB-or-larger
  L40, L40S, A40, and A100 routes. Earliest estimated start wins; candidates
  within five minutes use the fixed performance tie-break
  `A100 > L40S > L40 > A40`;
- checkpoint A100/A40 choices are visibly marked as preemptible. If discovery
  or every test-only estimate fails, submission continues on the stable L40
  fallback instead of failing the upload;
- the selected GPU, partition, estimated wait, preemption flag, and human
  reason are persisted in local job state and shown in the app. The planner
  adds no personal Hyak username, host login, password, Duo data, or private
  path; candidate accounts come from live Slurm associations;
- a live read-only probe compared all four compatible plans and selected an
  immediately schedulable A100. No test job remained queued, and existing Job
  `37805247` was left running unchanged;
- full `make check` passes 281 Python and 38 Swift tests with three expected
  environment-gated skips. Strict Swift formatting, signed app packaging,
  plist/signature validation, Python compilation, and `git diff --check` pass.

Implemented and verified for Task 009B2V:

- at the scheduling snapshot, pending Job `37804031` was blocked by
  `AssocGrpGRES`. Slurm test-only estimates placed normal L40 at
  `2026-07-28T06:22:38` PDT and L40S at `2026-07-27T20:19:38` PDT, while
  checkpoint A40 and A100 were immediately schedulable;
- the old job had never run and was cancelled. Replacement Job `37805247`
  requests only one A100, has a one-hour time limit, and started on an 80 GB
  A100 within seconds. The local project state follows the replacement ID and
  reports `RUNNING / full_transcription`;
- new whole-song and selected-gap submissions default to one hour. The app's
  `设置` sheet persists a 1–24 hour choice and the backend explicitly supplies
  it to `sbatch`; local GPU and CPU jobs do not receive the Slurm option;
- full `make check` passes 277 Python and 38 Swift tests with three expected
  environment-gated skips. Slurm shell syntax, strict Swift formatting, Python
  compilation, and `git diff --check` also pass.

Implemented and verified for Task 009B2U:

- the completed recovery did run MuScriptor with `--instruments voice`; its
  failure was therefore not a stale frontend or an omitted allowlist. It added
  841 notes to the prior 338-note main-melody track, while the earlier
  owner-accepted recovery added only 16 notes to the 322-note raw voice;
- production recovery no longer performs the unrestricted residual pass that
  was able to admit non-voice material. Directed candidates are still
  preserved and accompaniment-soft-masked, but automatic merge now also
  requires conservative growth admission: at most `max(32, source / 10)`
  candidate notes;
- a rejected recovery remains immutable diagnostic evidence. Its candidate
  files and bundle are not deleted, but it cannot become the default or
  silently replace the safer source melody. Future rejected selected-gap
  candidates also appear as a non-playing diagnostic track, and a user's
  later manual selection of another eligible version survives restart;
- the current private project now opens
  `gap-recovery-20260727T035419Z-c5001346-multitrack` on
  `voice_auto_enhanced` with 338 notes. The rejected 1,179-note bundle remains
  present and is visibly labeled diagnostic;
- accompaniment-track selected-gap recovery and per-track tail cleanup remain
  available. No Hyak or local inference job was submitted for this fix;
- full `make check` passes 276 Python and 38 Swift tests with three expected
  environment-gated skips. The configured real-project integration confirms
  the safe bundle ID, 338-note count, and existing five-group/51-fragment
  guitar-tail diagnostic.

Implemented and verified for Task 009B2T:

- the left music library searches all projects, groups active/completed/
  incomplete entries, and uses current job/result modification times;
- each row has a compact action menu. Completed or inactive projects can be
  moved to macOS Trash after confirmation; active Slurm states, symlinks,
  mismatched manifests, and paths outside the private project root are refused;
- deletion now fails closed for an unreadable or unknown persisted job state,
  preserves monitoring when another project owns the active job, and keeps
  failed reruns in the incomplete/failed group even if older results exist;
- tail repair is always visible for a selected track. It now explains whether
  the track was already cleaned, has no conservative candidate, or offers the
  existing sustain/percussion cleanup action;
- local state shows targeted-gap Job `37754413` as
  `COMPLETED / complete / succeeded`. No reusable SSH master existed, so no
  connection retry or remote action was attempted;
- the newest real bundle opens on `voice_auto_enhanced`; the clean-electric-
  guitar track still reports five groups and 51 fragments. Full `make check`
  passes 274 Python and 37 Swift tests with three expected environment-gated
  skips; the configured real-project integration also passes.
- the single bounded review found two P1 deletion-state issues and one
  user-facing failed-rerun grouping issue; all three are fixed with targeted
  regression coverage.

Implemented and verified for Task 009B2S:

- main-melody gap recovery now preserves the raw directed candidates, removes
  same-pitch/time accompaniment shadows, and keeps a monophonic derived
  candidate path. It does not perform unsafe literal audio or MIDI subtraction;
- if a selected main-melody target still has an empty span of at least three
  seconds, the same MuScriptor model runs exactly one contextual fallback
  without an instrument allowlist. Original predicted instrument labels remain
  in note provenance, percussion is excluded, and the result passes through the
  same accompaniment mask. Retries never recurse;
- generated product bundles now clean each accompaniment track independently.
  Conservative pitched tail fragments become sustains; dense drum-tail repeats
  become one short hit. Changed source events remain under `raw_tracks/`, and
  `reports/trailing_sustain_cleanup.json` records the derivation;
- edit sessions now bind the selected-track hash and migrate across a newer
  bundle only when the base track is compatible. Legacy before-state edits are
  replay-checked. A visible `保存修改` control and saved timestamp remove the
  prior ambiguity;
- read-only validation on the current song reduced 841 raw recovery candidates
  to 160, rejecting 606 accompaniment shadows and 75 polyphonic competitors.
  It then identified the still-empty `0:00–0:15` opening for the one fallback
  pass. This is diagnostic evidence, not an accuracy score;
- the same read-only song check found five guitar sustain groups (51
  fragments), one bass group (10 fragments), and two drum-repeat groups (14
  hits). No existing private result was rewritten and no new inference job was
  submitted;
- the configured real-project test proves the previous clean-guitar correction
  is compatible with the newest bundle. Full `make check` passes 274 Python and
  37 Swift tests with three expected environment-gated skips.

Implemented and visually verified for Task 009B2R:

- the screenshot's `待复核 0/0` panel had no action value because all 338
  selected-track notes lacked source confidence. It is now omitted whenever a
  track has no real confidence data and remains available for models that do;
- pitch, onset, offset, duration, and note deletion remain immediately
  visible. Model ID, run ID, and confidence provenance are preserved under the
  collapsed `来源信息` disclosure;
- the 1,663 cross-track review hints no longer occupy a permanent full panel.
  They are available under one collapsed `高级诊断` row. Current-track tail
  cleanup remains directly visible only when its conservative detector finds a
  candidate;
- the rebuilt signed app was checked on the current project. The owner-started
  constrained Hyak recovery remained `RUNNING` across the app restart;
- full `make check` passes 267 Python and 36 Swift tests with three expected
  environment-gated skips. Strict Swift formatting and `git diff --check`
  pass.

Implemented and code-verified for Task 009B2Q:

- completed Job `37751981` was successful, but its previous unconstrained
  selected-gap route added only 16 `voice` notes: two at
  `129.571–130.271` seconds and fourteen at `209.261–215.261` seconds. Three
  selected spans returned zero candidates;
- owner listening establishes that the missing melody is not present in the
  accompaniment tracks either. Those correctly transcribed accompaniment
  notes must therefore not be copied into the main melody;
- MuScriptor exposes a native `--instruments` allowlist. Both automatic
  voice-gap recovery and user-selected recovery now pass the requested
  instrument during model generation. The selected-track path remains generic
  for guitar, bass, and other canonical instrument labels;
- recovery requests record the allowlist; prior source bundles and result
  versions remain immutable. This is a directed-decoding fix, not a claim that
  every clear melody will now be recovered;
- focused tests pass 15 cases. Full `make check` passes 267 Python and 36 Swift
  tests with three expected environment-gated skips. No replacement Hyak or
  local inference job was submitted.

Implemented and verified for Task 009B2P:

- normal imported projects already carry canonical-audio duration. Product
  notes are now clipped to that boundary everywhere they are consumed:
  current-track and all-track piano rolls, review queues, MIDI preview,
  single-track export, and full multitrack export. Notes starting after the
  audio endpoint are omitted and crossing notes end at the endpoint; raw model
  JSONL is retained unchanged;
- every track is analyzed independently and an orange tail badge appears on
  both the mixer and all-track piano-roll row when a candidate exists. Selecting
  that row opens its own confirmation action in `整曲验收`;
- pitched tracks use the existing conservative contiguous-same-pitch sustain
  merge. Drum tracks use a separate periodic-short-hit detector and
  `折叠重复打击`, which keeps one hit per detected drum pitch instead of
  creating musically invalid long drum notes;
- neither cleanup is automatic because real tremolo, repeated playing, drum
  patterns, or rolls can look similar. Each action affects only the selected
  track, is saved as one undoable edit, and preserves original model output;
- on the current song, the drums track has two in-timeline repeat groups with
  14 hits. Another 28 drum predictions begin after `271.805147` and are
  automatically excluded from the product. Electric bass has one 10-fragment
  sustain candidate. The previously corrected clean-electric-guitar track
  remains corrected;
- focused analyzers, clipping, cleanup/undo, real-project loading, and real
  drum-track MIDI export pass. Full `make check` passes 265 Python and 36 Swift
  tests with three expected environment-gated skips. This implementation
  started no compute; the owner's corrected five-gap submission is now real
  Job `37751981` in `RUNNING` state and was left untouched.

Implemented and verified for Task 009B2O:

- the current song's canonical audio is `271.805147` seconds, while MuScriptor
  emitted accompaniment notes through `274.96`. The App incorrectly used the
  later MIDI offset as the song duration, displayed a false `4:34` endpoint,
  and sent the fifth gap beyond the authoritative audio boundary;
- product timeline, bar/beat position, gap detection, and trailing-sustain
  review now use canonical-audio duration whenever it is available. MIDI note
  spill no longer extends the song;
- the corrected five `voice_auto_enhanced` gaps are `0–60.51`,
  `81.75–120.09`, `123.34–130.72`, `209.26–215.73`, and
  `254.04–271.805147`. A read-only real-project planning check accepts all five
  as one request and writes no request file or Slurm job;
- the backend continues to reject genuinely out-of-range selections. A gap
  ending exactly at the audio boundary is covered by a regression test;
- new trailing-sustain merges clamp to the canonical endpoint. The owner had
  already used the old merge action, producing five app-owned correction notes
  ending at `274.96`; reopening that track in the rebuilt App repairs those
  legacy app-generated notes to `271.805147` as one undoable update. Original
  MuScriptor JSONL remains unchanged;
- focused Python, Swift, and configured real-project checks pass. Full
  `make check` passes 265 Python and 33 Swift tests with three expected
  environment-gated skips. No Hyak or local inference was started.

Implemented and code-verified for Task 009B2N:

- the App correctly launched the installed `amt-private-beta` console entry
  point from the repository, but Python used the executable directory rather
  than the repository as its import root. The gap planner therefore failed on
  `workers` before any Slurm submission. The backend now explicitly installs
  its already-validated repository root before importing repository workers;
- worker-import failure is also converted to bounded JSON, and normal backend
  operation errors no longer appear as an unreadable raw traceback dialog;
- the failed owner attempt left Job `37746586` in its prior terminal
  `succeeded` state and created neither a replacement Job ID nor a recovery
  request;
- the real `clean_electric_guitar` ending contains five synchronized pitch
  chains. They cover 121 contiguous events, and from `270.12` seconds the
  model repeats the same five-note chord every `0.23` seconds. Later Task
  009B2O established that events after `271.805147` are also model spill beyond
  the canonical audio endpoint, not valid extension of the song;
- the current-track review panel now offers a conservative
  `合并为延长音` action only when at least four same-pitch, contiguous notes
  reach the song tail, span at least two seconds, and are predominantly short.
  The owner must confirm it; all groups merge as one saved, undoable edit while
  canonical MuScriptor JSONL remains unchanged;
- the current song is detected as five pitch groups and 121 fragments. A
  real-project integration check passes without changing the project, and
  `make check` passes 264 Python and 31 Swift tests with three expected
  environment-gated skips. No Hyak or local inference job was started.

Implemented and code-verified for Task 009B2M:

- the former read-only voice coverage list is now a current-track gap control:
  every gap has a checkbox plus select-all/clear actions, and the owner can
  submit any subset as one compute job;
- selected spans are split only when needed for bounded inference, include
  four seconds of context, and run sequentially inside one Hyak L40 allocation
  or the explicitly selected local backend. The whole song is not
  retranscribed;
- recovery follows the selected track's MuScriptor instrument label, so the
  same flow supports the main voice candidate and accompaniment tracks such as
  guitar or bass. Silence can be intentional and remains labeled for listening
  review;
- the source bundle is hash-checked and retained unchanged. A successful task
  copies all tracks into a new bundle, augments only the selected track, keeps
  candidate provenance, automatically opens the new version, and allows
  another targeted pass over any remaining gaps;
- the previous job state is archived before a new project task replaces the
  active state. Login-node execution, overlapping/nonempty targets, unsafe
  paths, duplicate active tasks, and more than 16 target windows are rejected;
- the real `ピカソ-ビギン-ザ-ナイト` result was checked read-only. Its
  `voice_auto_enhanced` track contains 322 notes and five ≥3-second gaps:
  `0:00–1:00.51`, `1:21.75–2:00.09`, `2:03.34–2:10.72`,
  `3:29.26–3:35.73`, and `4:14.04–4:31.81`. The former UI displayed only the
  first four; the new list displays all five. Its first automatic gap candidate
  contained zero notes, which is why a manual second-pass entry is useful;
- `make check` passes 263 Python and 29 Swift tests with three expected
  environment-gated skips. Focused real-project loading and read-only planning
  also pass; no GPU job or local model inference was started;
- one Task-only `/review` was invoked. It produced no output for more than
  eight minutes after the network interruption, so the stalled process was
  stopped and not rerun. A bounded manual P0/P1 plus secret/path check found
  no blocking issue.

Implemented and code-verified for Task 009B2L:

- the current-track editor now has an explicit `新增音符` action and
  `Command-Shift-N` shortcut. It inserts a one-beat note at the playback head,
  selects it immediately, saves it as a reversible non-destructive correction,
  and leaves the canonical model output untouched;
- canonical rhythm data now carries actual Beat This beat events in addition
  to tempo and meter maps. The app shows seconds, representative BPM, current
  meter, `第 N 小节 · 第 N 拍`, downbeat labels, and beat-grid lines. Older
  bundles remain readable and are visibly labeled as an unanalyzed MIDI
  default rather than a model estimate;
- future Hyak private-Beta jobs run MuScriptor, then the already pinned Beat
  This worker, then same-model voice-gap recovery and packaging sequentially
  in one L40 allocation. The verified rhythm run is bound to the same
  canonical audio, preserved in worker provenance, used for MIDI tempo/meter,
  and fetched with the result. Rhythm failure falls back to the explicitly
  labeled default MIDI grid instead of discarding a valid multitrack result;
- the inspector now has a song-level acceptance summary across all product
  tracks and can jump between low-confidence or abnormally short notes. These
  are review hints only and are never auto-deleted or described as confirmed
  transcription errors;
- Beat This estimates beat/downbeat structure but its current normalizer uses
  a denominator of four. Common 4/4 and 3/4 estimates are useful; compound
  meters such as 6/8 are not yet a guaranteed distinction and the UI labels
  all rhythm output as an estimate requiring listening;
- read-only Hyak inspection found only Job `37746586` on L40 node `g3116`.
  It completed `0:0` in `00:21:19`, was fetched successfully, and left the
  queue empty. It was not interrupted or duplicated. Because it was submitted
  from the previous code, it does not retroactively gain Beat This;
- `make check` passes 259 Python and 29 Swift tests with three expected
  environment-gated
  skips, strict Swift formatting, Xcode compilation, release packaging,
  signature/plist validation, shell syntax, and `git diff --check` pass. The
  single focused `/review` found no remaining P0/P1 blocker.

Implemented and code-verified for Task 009B2K:

- Hyak remains the default for every new song. The toolbar and sidebar now
  allow an explicit choice of `Hyak GPU`, `本机 GPU`, or `本机 CPU`;
- local GPU uses MuScriptor's Apple Metal/MPS device and local CPU uses a
  reduced-priority background worker with bounded thread environment settings;
- local work uses the same full-song multitrack, deterministic gap planning,
  optional same-model recovery, fallback, and final bundle contract as Hyak;
- local readiness checks model/environment/device availability before launch.
  A detached per-project worker survives the app window, has a fixed local log,
  exposes honest stages, and can be stopped only after PID/project identity
  checks;
- no password, Hyak account identity, private audio, or local result path was
  added to tracked source. Existing Hyak connection/submission behavior is
  unchanged;
- by owner request, no local model inference and no local song transcription
  were run. Verification therefore covers command planning, state validation,
  readiness without device probing, process safety, UI selection persistence,
  compilation, and packaging—not local runtime speed or transcription quality;
- `make check` passes 258 Python and 28 Swift tests with three expected
  environment-gated Swift skips. Strict Swift formatting, release signing,
  plist validation, and `git diff --check` pass;
- the standalone XCUITest could not attach to its temporary fixture because
  the owner's already-running production app has the same bundle identifier.
  The live app was deliberately not terminated during its active Hyak task;
  this is an explicit GUI-session verification gap, not a passing result.

Implemented and verified for Task 009B2J:

- the editor now opens a complete song-level piano-roll overview by default:
  every normal product track occupies one vertically stacked row, with its
  instrument, actual note count, full-song time distribution, and pitch
  contour visible together;
- clicking a row selects that track. `编辑所选音轨` switches to the existing
  detailed piano roll, where note movement, edge resizing, inspector edits,
  undo, and redo remain available; `返回全部音轨` restores the overview;
- the overview follows the transport with a shared playhead and keeps raw and
  gap-only voice diagnostics hidden unless the existing diagnostic switch is
  enabled, so standard playback/export still contains only one melody variant;
- the current default branch was synchronized to the public GitHub repository
  after replacing the remaining tracked personal Hyak path with portable
  placeholders. Credentials, private audio, results, and local Hyak config
  remain ignored;
- `make check` passes 257 Python and 27 Swift tests with three expected
  environment-gated Swift skips. Strict Swift formatting, signed release
  packaging, `git diff --check`, real-project visual QA, and the formal
  XCUITest covering the overview/detail switch all pass.

Implemented and verified for Task 009B2I:

- the default Precision mode now uses a restrained graphite, teal, and lime
  signal-lab treatment; Settings can enable a separate Spectrum mode using
  midnight navy, cyan, and violet;
- both modes share the same project, model state, and controls. Appearance
  persists locally and never reloads a song, submits a Hyak job, or changes
  MIDI output;
- the running-job empty state is replaced by a truthful five-stage view for
  upload/queue, full transcription, gap inspection, automatic recovery, and
  packaging. It shows no fabricated percentage or ETA;
- the toolbar is reduced to seven focused controls. Project operations are
  grouped under `项目`; `导出` names `整个识别版本（完整多轨 MIDI）` first,
  followed by current-track and audible-mix exports;
- the real decoded waveform and piano-roll notes inherit the active theme,
  while the sidebar and library keep the same clear information hierarchy;
- Job `37743206` is locally recorded as `COMPLETED / succeeded`, with
  `pipeline_stage=complete`, `slurm_exit_code=0:0`, a fetched 12-file bundle,
  and successful automatic recovery;
- `make check` passes 257 Python and 26 Swift tests with three expected
  environment-gated Swift skips. Strict Swift formatting, signed release
  packaging, plist/signature validation, `git diff --check`, and dual-mode
  visual QA pass.

Implemented and verified for Task 009B2H:

- the screenshot error was reproduced as an NFC/NFD spelling difference for
  the same Japanese project directory. State validation now accepts only
  canonically equivalent project identifiers while retaining same-file,
  manifest, remote-path, Job ID, and traversal checks;
- the production status command now accepts the exact decomposed path received
  from the Mac app. Job `37743206` remains `RUNNING` in
  `full_transcription`; no duplicate job was submitted;
- `保存修改` is now explicitly separate from `导出整版 MIDI`. The selected
  recognition version has a visible sidebar export action and explanatory
  text; current-track and current-mix exports remain under `其他导出`;
- whole-version export means every accompaniment track in the selected bundle
  plus one preferred melody representation. It ignores mixer mute/solo/volume,
  while current-mix export continues to honor them;
- the real nine-track `STILL LOVE HER` automatic bundle passed application-level
  whole-version MIDI export. The output has a valid standard MIDI header;
- `make check` passes 257 Python and 25 Swift tests with three expected
  environment-gated Swift skips. Strict Swift formatting, signed release
  packaging, plist/signature validation, and `git diff --check` pass.

Implemented and verified for Task 009B2G:

- one private-Beta Slurm job now runs full-song MuScriptor first, plans only
  voice gaps of at least eight seconds, and conditionally runs bounded
  same-model contextual clips without asking the user to upload again;
- the automatic plan is capped at eight targets, splits spans above 80 seconds,
  keeps four seconds of context, and combines nearby targets only when the
  resulting clip stays within 90 seconds. These are fixed engineering bounds,
  not benchmark-tuned accuracy thresholds;
- recovery failure publishes a freshly rebuilt raw multitrack bundle instead
  of failing an otherwise successful full-song result;
- successful automatic output is self-contained and keeps
  `voice_raw`, `voice_gap_candidate`, `voice_auto_enhanced`, and every original
  accompaniment track. Every enhanced event retains its source event and
  origin variant;
- the app reports full transcription, gap planning, automatic recovery, and
  packaging stages. Normal playback and standard multitrack export include
  only one voice variant; raw and gap-only versions are hidden behind a
  diagnostic toggle and remain available for comparison;
- a read-only plan over the existing `STILL LOVE HER` raw result reproduced
  four contextual windows covering the same five previously reviewed gaps;
- reusing the already completed 184 candidates produced a private nine-track
  dry-run bundle with 438 auto-enhanced voice events and all six accompaniment
  tracks. The real Swift loader and selected-track MIDI export pass for
  `voice_auto_enhanced`;
- `make check` passes 256 Python and 25 Swift tests with three expected
  environment-gated skips. Strict Swift formatting, shell syntax, and
  `git diff --check` pass;
- no Hyak job, new model inference, source separation, GAME, training, or
  dataset work ran for this implementation. Automatic recovery remains a Beta
  candidate and makes no accuracy claim.

Implemented and verified for Task 009B2F:

- the owner accepted the same-model gap recovery after listening, estimating
  that it recovered more than 95% of the previously missing notes while a few
  notes remain absent. This is explicitly stored as subjective single-song
  feedback, not formal accuracy;
- `voice_enhanced` deterministically combines 254 immutable raw notes and 184
  separately preserved gap candidates into 438 provenance-bearing events;
- the app prefers the enhanced track when present and makes
  `voice_raw`/`voice_gap_candidate`/`voice_enhanced` mutually exclusive during
  mix playback, so selecting a comparison variant does not create doubled
  notes;
- the new private bundle passes all hash/count checks and real-project Swift
  loading plus selected-track and arrangement MIDI export;
- all 25 Swift tests pass with three expected environment-gated skips. No new
  Hyak job, separator, GAME run, training, or automatic model promotion was
  performed;
- final `make check` passes 254 Python and 25 Swift tests. Strict Swift
  formatting passes, and the focused P0/P1 review has no remaining blocker.

Implemented and measured for Task 009B2E:

- the original 254-note `voice_raw` file is unchanged at SHA-256
  `25725cff2b738bee8d66514dc5fbde51e04cf1a6b5e74c490e52025de4b4d48c`;
- Hyak Job `37740313` ran four contextual clips sequentially on L40 node
  `g3115`. All four MuScriptor child manifests succeeded with the same large
  model, beam size 4, and prelude forcing as the full-song run;
- the probe produced 184 separate `voice_gap_candidate` notes. The two middle
  targets contain 52 notes each and cover 18.70/27.14 and 20.25/26.89 seconds.
  The first tail target contains 80 notes covering 21.28/77.36 seconds. The
  possible-instrumental intro negative control and final 76.653719-second
  target contain zero candidates;
- across the four non-control targets, candidates cover 60.23 of 208.043719
  seconds (28.95%). This is recall-oriented time coverage, not correctness or
  transcription accuracy;
- the Slurm parent exited `1:0` only after all inference completed because the
  old private-Beta rhythm map lacked newer MIDI provenance fields. The
  compatibility fix reused those completed artifacts on the Mac and generated
  `task009b2e-muscriptor-gap-v2-review`; no model inference was repeated;
- the review bundle exposes `voice_raw` and `voice_gap_candidate` as two
  tracks, declares no fusion/automatic merge/accuracy claim, and passes the
  real-project Swift loader with `voice_gap_candidate` selected;
- source separation, GAME, training, retuning, and automatic candidate merging
  remain unstarted. The later owner review accepted the result for a derived
  enhanced track, but exact correct-note and false-positive counts remain
  `null`;
- final `make check` passes 253 Python and 24 Swift tests with three expected
  environment-gated skips. The focused P0/P1 review found no blocker.

Implemented for Task 009B2D responsiveness and melody coverage:

- project loading, bundle/track selection, note materialization, and MIDI
  preview generation no longer perform full-project work on the SwiftUI main
  actor; stale background selections and previews are discarded;
- playback observes only the transport components that need live updates, the
  piano roll uses lazy 10-second segments, and selecting a track no longer
  reloads the same FLAC or rewrites every note into the edit history;
- the start screen and sidebar list six existing private song projects, so
  prior music can be reopened without choosing its folder again;
- external project access is remembered with security-scoped bookmarks.
  `连接 Hyak` opens the login script through LaunchServices instead of
  automating Terminal, and release builds use the installed Apple Development
  identity when available instead of changing ad-hoc identity every build;
- original-audio and MIDI-master volume controls make the transcription
  audible over the song;
- `voice` is now described as a **主唱候选**, not a complete main melody. The
  app detects silent spans of at least three seconds, seeks through them, and
  reports how many other predicted tracks contain notes in each span without
  automatically copying accompaniment into `voice`;
- on the 349.85-second `STILL LOVE HER` result, the 254-note `voice` candidate
  has four such spans: `0.00–33.35`, `63.55–90.69`,
  `104.52–131.41`, and `195.14–349.85`, totaling `242.09` seconds.
  The owner's listening says detected voice notes are usually accurate while
  these long omissions are obvious; this is product feedback, not a formal
  accuracy measurement;
- 24 Swift tests pass with three expected environment-gated skips. Two
  private real-project integration tests also pass; opening the full project
  returns control to the main actor promptly while background preparation
  completes;
- final `make check` passes all 247 Python and 24 Swift tests. A focused
  P0/P1 review found no remaining blocker;
- the release app is signed with the installed Apple Development identity,
  passes strict signature/plist validation, and is running on the real fetched
  project;
- this slice submitted no Hyak/model job, did not alter canonical model
  output, and did not attempt an unsafe automatic melody merge.

Implemented for Task 009B2C usability:

- all fetched MuScriptor tracks are now audible in-app, with explicit
  `当前音轨` and `合奏` modes plus per-track note count, mute, solo, and MIDI
  volume controls;
- the default is the complete audible arrangement, while selecting a track
  still changes only the piano-roll editor; model labels remain visibly
  described as fallible predictions;
- mixer state survives restart, and MIDI export now distinguishes current
  edited track, current audible mix, and untouched complete multitrack;
- the app persists an active Hyak project separately from the recent editor
  project, reports connection state, and prevents duplicate submission while a
  job is active;
- an expired SSH session does not mark the Slurm job failed. `连接 Hyak` opens
  Terminal, waits for the owner-controlled password/Duo flow, then resumes
  polling and result retrieval;
- completed projects restore their local job ID/state without blocking the
  next song;
- real new-song Job `37735878` completed `0:0` in `00:24:50` on L40 node
  `g3096`. It was fetched through the production status interface, and the
  Hyak queue is now empty;
- the new `STILL LOVE HER` bundle contains all 10,989 events across 7 predicted
  instrument tracks; `voice` is the default with 254 events. Its convenience
  MIDI has 8 tracks including conductor, 6 program changes, and 2,115
  percussion note-ons;
- the production Swift loader and selected/full-arrangement real-project test
  pass on the new private result. The formal macOS UI flow also passes open,
  waveform, playback, review, edit, undo/redo, and process-restart restoration;
- the single bounded Task 009B2C review found no P0 and one P1. The direct
  upload path now recognizes expired SSH and enters the explicit relogin/resume
  state; no lower-priority review expansion was performed;
- final `make check` passes all 247 Python tests and 21 Swift tests, with two
  expected environment-gated Swift skips;
- the release app was rebuilt, ad-hoc signed, launched with a real 13-track
  project, and visually confirmed to show the mixer and complete editor.

Implemented for Task 009B2B private Beta:

- the Mac app now exposes `连接 Hyak`, `识别歌曲`, job refresh, current-track
  MIDI export, and complete edited multitrack MIDI export;
- the Mac performs only audio canonicalization, transfer, status polling,
  editing, and export; MuScriptor inference is submitted to an L40 Slurm
  compute node and refuses login-node execution;
- the fast path runs one MuScriptor JSONL decode, then losslessly groups every
  event by its predicted instrument instead of running a second model decode;
- the `voice` track is opened as the default main-melody view when present;
  all other raw predicted tracks remain available and no accuracy claim is
  added;
- original worker output remains immutable. Manual edits stay in
  `annotations/corrections/` and change exports, not the MuScriptor model;
- the Task 002 full-song run was converted locally into 9 instrument tracks
  containing all 7,667 events. The bundle opens through the production Swift
  loader, and both selected-track and complete-arrangement MIDI exports pass
  the private integration test;
- all 34 melodic MuScriptor instrument classes have explicit General MIDI
  programs, and `drums` uses the percussion channel, so edited multitrack
  exports do not collapse to undifferentiated piano tracks;
- real end-to-end job `37734361` completed `0:0` in `00:17:28` on L40 compute
  node `g3098`; the app workflow created, uploaded, submitted, polled, fetched,
  validated, and reopened the private project without login-node inference;
- the fetched run preserved 6,881 valid events across 13 predicted instrument
  tracks, defaulted to the 469-event `voice` track, and produced a 14-track
  MIDI with all 6,881 note-ons, 12 program changes, and 1,545 percussion
  note-ons on channel 10;
- the source/canonical hashes, model revision, weight hash, beam size, and
  prelude setting match Task 002. The earlier A100 result had 7,667 events
  across 9 labels while this L40 result has 6,881 across 13, so cross-hardware
  byte invariance is not claimed; the private Beta pins the L40 route;
- Hyak identity and persistent-root values now come from the ignored local
  `configs/local_hyak.json` (or explicit environment/CLI overrides), while
  `configs/hyak.example.json` contains only placeholders. Password and Duo
  data are never stored;
- each future submission synchronizes a clean `git archive` snapshot and
  records its exact commit in the worker manifest. Persisted job state is
  project/path/identifier bound and rejects symlink or traversal input;
- canonical JSONL preserves every predicted track even if more than one MIDI
  port can represent. Fifteen melodic tracks plus drums fit one file; a larger
  result remains usable as canonical multitrack data and marks only the
  convenience performance MIDI unavailable;
- the single final `/review` found no P0 and five P1 issues. All five P1s were
  fixed: Xcode source membership, state validation, 16+ track preservation,
  synchronized-code revision binding, and removal of committed personal Hyak
  defaults. Three P2 suggestions were deliberately left outside this bounded
  closeout;
- final `make check` passed 247 Python tests and 18 Swift tests, with two
  expected environment-gated Swift integration skips. Seven Python tests in
  that worktree belong to the preserved, paused Task 007D files and are not
  part of the Task 009 commit; all Task 009 tests passed.

Verified for Task 007C:

- Phoenix remains `development_instrumental_melody`; its six 20-second windows
  were selected only from duration, and neither its reference nor its result
  is eligible for a blind-performance claim;
- prepare `37732190`, Basic Pitch `37732191`, and evaluation `37732192` all
  completed `0:0` on Hyak compute nodes;
- the exact canonical mix was bound by SHA-256
  `1f38bc42cd31134e5592ec7bbc0bed1bdb51e90c3101f442535459af1c56a0bc`,
  and 1,701 normalized events retained unknown instrument `other`;
- across 20,676 contour frames, raw pitch accuracy was `0.6932`, overall
  accuracy was `0.3339`, and voicing false alarm was `0.9648`; all three
  frozen automatic conditions failed;
- the automatic decision is
  `reject_direct_mix_instrumental_route_for_v1`; Phoenix retuning, a new
  instrumental blind set for this route, production promotion, Task 009B2B,
  and Task 010 are all unauthorized;
- report SHA-256 is
  `fbe730efde84b8f1cb70c5a81844c1573eca9a8a51cee468d23603525b90a7df`;
  hardened v2 decision SHA-256 is
  `5bb86efc3ee236013b71147d1b54ceea76c3a5e76bd6f1455014dca41805aa13`;
- ignored private evidence and scheduler logs were synchronized and verified.
  `make check` passed 230 Python and 17 Swift tests, with one expected
  private-integration skip;
- the single `/review` found two P1 and two P2 issues. Both P1 issues are fixed:
  development references cannot enter a blind split, and automatic assessment
  now authenticates the frozen seals/artifacts and exact scoring policy. The
  two P2 hardening suggestions were left documented without expanding scope.
  Targeted P1 tests pass, and no model or scoring job was repeated.

Verified for Task 007B:

- five development and six blind Vocadito singers were frozen before inference;
  all eleven were disjoint from Task 006 and Task 007 v1;
- A40 candidate job `37720513`, development calibration `37720514`, final
  fusion seal `37722126`, and evaluation/assessment `37722127` all completed
  `0:0`; no model or evaluation ran on a login node;
- the final blind report verified candidate and fusion seals,
  development-only calibration, no blind retuning, and both frozen worker
  ablations;
- GAME remained strongest at onset+pitch F1 `0.7814` and
  onset+pitch+offset F1 `0.3676`; fusion scored `0.6924` and `0.3276`,
  regressing by `0.0891` and `0.0400`;
- the automatic decision is `reject_v2_without_blind_retuning`; no matched
  human-correction task is justified and Gate 4 remains open;
- final report SHA-256 is
  `ea66e1b20b3739478a56b89a0c5e104af55b959de15007de7f34dbded507a1f7`;
  decision SHA-256 is
  `4338127e5009589e2f336086d62b78a9b99be8630580ed380b671f8b238fd732`.

Verified for Task 009B2A:

- a committed Xcode project builds the production macOS sources and a formal
  UI-test bundle without adding an app-side model runtime;
- the UI fixture is generated at runtime under a non-ASCII path, uses only a
  synthetic three-second WAV, and does not read or replace the user's recent
  project preference;
- the formal UI test opens and auto-selects the unique canonical candidate,
  observes the real waveform, piano roll, and confidence controls, advances
  and pauses playback, navigates the low-confidence queue, edits a note,
  exercises undo/redo, relaunches the process, and confirms history restore;
- `make mac-ui-test` passes one XCUITest with zero failures. Repository-level
  `make check` separately passes 216 Python and 17 Swift tests, with one
  expected private-integration skip;
- the single focused review found no P0/P1; both P2 evidence/reproducibility
  findings were fixed by asserting a loaded non-empty waveform and making the
  documented command independent of the preceding working directory;
- this verification submitted no Slurm job, ran no inference, and did not
  change Gate 4 or the Mac/Hyak compute boundary.

Verified for Task 009B1:

- Hyak remained live on a login node; the queue was empty and no Slurm job,
  inference, or login-node compute ran;
- the note-density placeholder was replaced by a real 2,048-bin peak envelope
  decoded from the existing canonical audio on a cancellable utility task;
- the real 4:25 private-project waveform rendered in the foreground app with
  the synchronized transport cursor;
- the selected-track review queue filters only numeric source confidence,
  sorts the lowest values first, navigates and seeks to notes, and explicitly
  excludes unknown values;
- all four current canonical tracks provide zero confidence values, so GAME
  correctly shows `0 / 0` and reports 391 unknown-confidence events rather
  than inventing a score;
- Swift coverage verifies real PCM peak placement, threshold/order behavior,
  missing-confidence exclusion, non-ASCII paths, and audio/timeline scaling.
  The single focused review found no P0/P1; all four P2 findings were fixed.
  Final `make check` passes 216 Python and 17 Swift tests, with one expected
  private-integration skip. This slice adds no import, worker, inference
  route, model pack, or Hyak dependency.

Verified for Task 009A:

- Hyak was reconnected for a lightweight queue check; no job was running or
  queued and no model task was submitted;
- the ad-hoc-signed `AMT Studio.app` launches as a foreground macOS app with a
  visible SwiftUI window;
- the real private project opens without inference, requires an explicit one
  of three canonical bundles and one of four unranked candidate tracks, and
  validates all referenced hashes, sizes, and project-root-relative paths;
- the selected GAME track contains 391 notes on a 4:25 timeline; original
  audio and MIDI preview playback advanced the observed cursor from 0 to
  6.512789 seconds before pausing;
- note move and left/right resize projection, short-note hit targets,
  undo/redo, atomic restart persistence, symlink-safe output paths, and
  actionable audio/MIDI errors have regression coverage;
- the real selected-track export is standard MIDI format 1 with 960 PPQ, two
  MIDI tracks, 391 note-ons, and SHA-256
  `5c16d7323b55d8d6f59172e5b3eaab30405e6660b633921bcb24f16c296295ce`;
  Mido parsed the full file, GarageBand imported it, and Logic Pro opened it;
- `swift test` passes 16 tests in the normal run with the private integration
  test intentionally skipped; that private test passes when explicit
  project/bundle/track variables are supplied;
- repository-level `make check` passes all 216 Python tests and the Swift
  suite;
- the focused review found no P0; all implementation-safety P1 findings were
  fixed. Swift format lint, app plist/signature checks, and `git diff --check`
  pass. The previously explicit formal-XCUITest gap is now closed by
  Task 009B2A.

Verified on the user's Mac:

- Python 3.12 root environment created with uv;
- dependency-light Python source and tests compile;
- four unit tests pass;
- doctor finds Git, ffmpeg, ffprobe, and uv;
- the private reference MP3 was ingested through a Japanese/spaced path;
- source SHA-256 is
  `3464cdb850fdb1796c2cc48e0580640f04c39062eb236143e1ff0f2bdc0d1dbe`;
- canonical output is deterministic 44.1 kHz stereo FLAC with SHA-256
  `2c4ef424af20dd1eeb4c17b44ecb8da9a5f640ec26449e972ba4b45cb330ecde`;
- non-empty project overwrite is refused;
- private audio and private project artifacts are ignored by Git;
- `make check` passes.

Verified for Task 002:

- Mac is limited to orchestration, validation, and result rendering; all
  MuScriptor large inference ran in Hyak Slurm GPU allocations;
- the isolated worker is locked to MuScriptor `0.2.2`, Torch `2.2.2`, and the
  exact large-model revision and weight/config SHA-256 values;
- two fixed-excerpt A100 runs produced byte-identical native JSONL and MIDI;
- a beam-4 A40 probe completed successfully;
- full-song A100 job `37604080` completed successfully in `00:24:40`;
- full run `muscriptor-large-beam4-hyak-37604080` preserved native JSONL,
  native MIDI, normalized events, logs, commands, environment, timings, code
  hashes, model hashes, and output hashes;
- 7,667 normalized events validate; observed instruments, pitches, and timing
  are documented without an accuracy claim;
- a full stereo auralization was rendered and structurally inspected on the
  Mac without model inference;
- all private inputs, weights, outputs, and renders remain ignored by Git;
- `make check` passes with 9 unit tests.

Verified for Task 003:

- Mac remains limited to orchestration, artifact validation, short-clip
  rendering, and listening; all separator and downstream MuScriptor inference
  ran in Hyak Slurm A40 allocations;
- `audio-separator==0.44.5`, its upstream commit, the two candidate model
  bundles, and the complete model-file set are hash-pinned;
- independent A40 jobs `37610839` and `37610998` produced exact decoded-PCM
  repeatability for both candidates on the fixed 20-second excerpt;
- final full-song separator job `37611557` completed successfully with
  request-bound manifests, zero decoded-frame timeline drift, and no material
  clipping;
- final downstream MuScriptor job `37611749` completed the same beam-4,
  voice-only configuration on the mix and both vocal stems, preserving verified
  lineage and a descriptive comparison report;
- idempotency job `37612144` verified and reused all three final MuScriptor
  runs and the complete comparison report without rerunning inference;
- the final three-passage listening package is bound to the final separator
  manifests; the project owner preferred A on all three passages, described A
  vocals as clear, and reported obvious accompaniment leakage and echo in B;
- `vocal_quality_a` (BS-Roformer) is the selected default;
- `multistem_quality_a` (Demucs) is the fallback and remains available when
  separate drums, bass, and residual stems are required;
- `make check` passes with 45 unit tests.

Verified for Task 004:

- Mac remained limited to orchestration, validation, statistics, and review-pack
  rendering; all GAME and Basic Pitch model inference ran in Hyak Slurm
  allocations;
- isolated lockfiles and exact package, source, model, and license pins were
  recorded for GAME v1.0.3 plus its official medium model and Basic Pitch
  0.4.0 plus its bundled ONNX model;
- GAME setup job `37614010`, GAME A100 baseline job `37614448`, Basic Pitch
  setup job `37613596`, and Basic Pitch CPU baseline job `37614317` completed
  successfully;
- native GAME CSV/TXT/MIDI and Basic Pitch CSV/MIDI/NPZ outputs were preserved;
  both native MIDI note-on counts exactly match their decoded event counts;
- four lineage-verified vocal candidates now share the same project identity
  and canonical mix: GAME on the selected A stem, Basic Pitch on that stem,
  MuScriptor voice on that stem, and MuScriptor voice directly on the mix;
- the comparison covers event count, short-note fragmentation, pitch range,
  phrase gaps, polyphonic active time, and octave behavior without ranking
  candidates or making an accuracy claim;
- three passages selected before melody output inspection (`4–16 s`,
  `132–144 s`, and `180–192 s`) have synchronized mix and four-candidate piano
  renders, with exact 12-second PCM windows and hashed manifests;
- the review pack is explicitly marked `awaiting_human_review`,
  `accuracy_claimed=false`, and `task005_export=false`;
- focused `/review` found no remaining P0–P2 issue;
- `make check` passes with 90 unit tests.

Verified for Task 005:

- Mac remained limited to code, orchestration, validation, statistics, and
  export; Beat This setup and full-song inference ran in Hyak Slurm A40
  allocations;
- Beat This `1.1.0`, its upstream commit and PyPI wheel, the official `final0`
  checkpoint, SoundFile, Torch/Torchaudio, CUDA runtime, decoding settings, and
  all source files are pinned or hashed;
- setup job `37621094` and final full-song job `37621507` completed
  successfully; the initial missing-FLAC-dependency failure remains preserved
  as an immutable failed run;
- final run `beat-this-task005-final0-d332b542-attempt-4` records 567 beats,
  143 downbeats, 13,281 frames of raw 50 Hz beat/downbeat logits, exact input
  lineage, environment diagnostics, commands, timings, and output hashes;
- `amt-worker-request/v1` and `amt-worker-result/v1` now provide a shared
  validation interface for isolated workers, including legacy Task 002–004
  results;
- canonical note, track, tempo, meter, rhythm, and provenance models are
  implemented without rewriting previous raw results;
- the real private canonical bundle retains GAME, Basic Pitch, stem-MuScriptor,
  and direct-MuScriptor as four separate candidate tracks;
- performance MIDI contains 2,223 original-timeline notes and the separate
  score-grid experiment contains 2,223 derived records;
- Mido `1.3.3` independently round-tripped all four MIDI tracks with maximum
  onset/offset error below 0.236 ms;
- tempo/meter inference and missing calibrated per-event confidence are
  explicitly represented as uncertainty, not accuracy;
- focused review found no remaining P0–P2 issue;
- `make check` passes with 110 unit tests.

Not yet verified:

- any note, instrument, melody, or score accuracy against human reference;
- beat/downbeat accuracy against human reference;
- GAME or Basic Pitch repeatability across independent inference runs;
- accepted candidate fusion, formal score quantization/MusicXML, training, or
  Task 009B import/background-job/model-pack integration.

Task 006 implementation now includes a dependency-light reference-note model,
benchmark freeze policy, human-reference seal, note/octave/instrument and
confidence/coverage metrics, timed-event F1, correction-effort logs, seeded
whole-excerpt review, an annotation-only top-line proposal tool, and
tamper-detecting evaluation output. Candidate-corrected seals now bind the
verified worker seed and review artifacts immutably; blind results require an
exact candidate set frozen before output-quality inspection. The first private
song has a six-excerpt development pack, publicly referred to as
`development-song-a`, with benchmark SHA-256
`ec7e6895b36686212da8cbec5e86bee9007f0d733f5b433cdfe56111a02f6838`;
the owner has confirmed that its six stated coverage types are broadly correct.

A previously unused different-artist song is now frozen before model output as
the opaque public alias `blind-song-b`, with benchmark SHA-256
`e235a1faa04990bb53c3d976bfb6bb9241411beae4cc198328eaece747a8e5ee`.
Its separator, Beat This, GAME, Basic Pitch, vocal-stem MuScriptor, and
direct-mix MuScriptor baselines ran on Hyak compute nodes. Direct MuScriptor
produced 8,270 native notes; one exact zero-duration note was explicitly
quarantined and 8,269 valid notes were recovered without rerunning inference.

Owner listening now provides actionable but still subjective error labels:
`blind-01` was described as approximately 90% correct, `blind-02`, `blind-04`,
and `blind-06` retain note identity or segmentation errors, and `blind-05`
remains cluttered. A post-feedback annotation-only Hyak A40 job (`37627351`)
transcribed the multistem `other` track with drums, bass, and vocals excluded.
It completed successfully and produced a cleaner 59-note `blind-05` proposal,
but owner listening rejected it: the configured review SoundFont did not sound
like a recognizable acoustic piano, and the original tune was not
recognizable. This route is closed rather than rerendered with a different
timbre, because the melody itself failed. The derived proposal is excluded
from primary blind metrics. The review renderer now verifies the actual bank 0
program 0 preset and rejects non-acoustic-piano SoundFonts, so the prior
`FM Bells 1` configuration cannot recur; this guard does not rehabilitate the
failed melody. Verification now requires both the approved GeneralUser GS
SHA-256 and the exact bank 0/program 0 name `Grand Piano`; names such as
`FM Piano` and `Rhodes Piano` are rejected.

A final Hyak annotation-aid investigation used the six-stem guitar output. All
three predeclared pYIN variants produced zero accepted notes. MuScriptor found
167 notes in `blind-05`, but 40 of 77 onset groups were polyphonic and up to
five notes occurred together. The stem therefore still contains lead plus
accompaniment rather than a trustworthy single melody. This route was rejected
without producing another owner listening pack. The 90% wording is not a
measured accuracy result.

The focused Task 006 review found five additional benchmark-integrity defects,
all now covered by regression tests: seed-copy detection is scoped to scored
windows and scoring fields; absent confidence emits no numeric threshold
rows; pair-dependent metrics use globally minimum-cost maximum matching;
high-agreement diagnostics mask estimates matched to omitted references; and
offset censoring is accepted only at the frozen context boundary.
The later formal-blind completion path also fixed a sealed-set contradiction:
a candidate-corrected reference may evaluate exactly the preinspection sealed
set minus its uniquely hash-bound annotation seed, and the excluded seed is
recorded in both reports. Final review additionally requires that seed to
exist in the sealed set, revalidates every scored input snapshot immediately
before publication, and publishes into a newly claimed directory without
overwriting a path that appeared during evaluation. `make check` now passes
all 155 unit tests;
script/worker compile checks, JSON-schema parsing,
external-working-directory CLI startup, and `git diff --check` also pass.

The private-song note references remain unsealed, so no formal note metrics are
claimed for those songs. Their current artifacts were already inspected and
cannot be retroactively labeled as formal blind metrics. Task 006 therefore
uses separately frozen external references for its formal baseline while
retaining the private-song feedback only as subjective annotation guidance.

A replacement formal blind project, publicly identified only as
`blind-song-c`, was ingested from a newly supplied different-artist song. Its
six audio-only excerpts were frozen before any model submission with benchmark
SHA-256 `f4e1736c833eb0cc427f17d9bb0f99dae7d5211dfe737bd013f9aa78718539f0`.
The separator route and four main-melody candidate labels were predeclared
while output quality was uninspected. Superseded multi-job submissions were
cancelled before start. Job `37637038` used one checkpoint A40 and completed
the separator, Beat This, GAME, Basic Pitch, and MuScriptor chain in
`00:25:07` with exit code `0:0`. It automatically wrote the preinspection
candidate seal before synchronization; candidate-set SHA-256 is
`02f37949ffe92824cb6b793181f491562c3cd66622f7e2f9d7f727bd53763296`.
All eight worker runs, the comparison report, seal, and Slurm logs were synced
to the Mac and every manifest-recorded output was re-hashed successfully.

Before listening, GAME was frozen as the single candidate-corrected annotation
seed and permanently excluded from primary metrics. A Task 006-specific
renderer now requires the benchmark freeze, seed policy, candidate seal, exact
GAME run and artifact hashes, and the approved `Grand Piano` SoundFont before
creating a package. The six synchronized mix/seed passages are generated and
hash-verified with status `awaiting_human_review`; no other sealed candidate
was exposed as an annotation aid.

The first owner review described `blind-02`, `blind-03`, and `blind-04` as
approximately 95%, 90%, and 80% correct by informal listening, while also
reporting residual wrong, cluttered, or missing notes. Those percentages are
preserved only as subjective impressions and are not measured accuracy or
reference approval. The owner classified `blind-05` and `blind-06` as
accompaniment/interlude rather than the one-track main melody, so the detected
seed notes may be false positives; because the feedback was explicitly offered
as non-expert guidance, the empty-reference interpretation remains provisional.

The raw feedback was recorded privately without modifying the seeded notes.
An independent annotation-only pYIN aid then ran on the lineage-verified vocal
stem in Hyak checkpoint CPU job `37650151`. It completed in
`00:02:54` with exit code `0:0`; all 12 declared outputs were hash-verified
after synchronization. It proposed 22, 22, and 17 notes for `blind-02` through
`blind-04`, and a narrow three-passage review pack was rendered with the
approved `Grand Piano` SoundFont. The aid did not read or expose the three
sealed primary candidates and is ineligible for primary blind metrics. Its
`blind-05` and `blind-06` detections will not override the owner's
accompaniment classification.

Final owner review retained the GAME seed as the more useful annotation aid
and rejected pYIN as discontinuous and unusable. That route is closed rather
than awaiting another listening pass. The provisional private-song references
remain unsealed; formal Task 006 metrics instead use separately frozen,
professionally annotated external benchmarks without converting the owner's
subjective percentages into accuracy claims.

The owner later supplied a privately held piano score for `blind-04` and
clarified that the relevant location is original printed page 3 of 6 (the left
half of combined PDF page 2), system 2 through the opening of system 3. A
score-guided provisional reference now records 22 right-hand top-voice notes
over `180.78–190.00 s`, aligned to the existing Beat This downbeats and shifted
down one octave to the recorded vocal register. It fixes the seed's missing,
over-segmented, low-pitched, and split-note regions while retaining the old
23-note seed unchanged for audit. Private source hashes, the exact
transcription, a cropped score image, MIDI, and three acoustic-piano review
renders are stored under
`projects/private/<blind-song-c-project>/annotations/reference-task006-blind-v1/score-guided/blind-04-v1/`.
This is Codex transcription from an owner-supplied score, not an owner-operated
timed correction session, so it remains unsealed and does not close Gate 2.
The owner's first listening pass estimated this score-guided version at roughly
80% correct and reported obvious wrong notes. That percentage is subjective,
not a metric; the 22-note version is now explicitly `needs_revision` and is not
accepted or sealed as the final reference.
The follow-up staff-position audit found a concrete transcription error rather
than a score-source mismatch: six notes in system 2 measures 3–4 had been read
one diatonic step too high. A non-overwriting `blind-04-v2` now changes
`D-C-C-Bb / Eb-C-Eb-D` to the score's
`D-Bb-Bb-Bb / D-Bb-D-C`. Existing Hyak-generated vocal pYIN frame medians
independently support all eight corrected interval pitches. The v2 MIDI and
three review WAVs pass hash, duration, channel, sample-rate, and 22-note
validation. The owner now estimates v2 at above 95% by informal listening and
accepts it as the current private reference. The estimate is not a measured
accuracy metric; v2 remains formally unsealed and provides no timed human
correction evidence, so Gate 2 is unchanged.
The first attempted timed review was invalidated because the original mix
masked the piano guide. A replacement 12-second review attenuated the original
and placed the piano approximately 12 dB forward; the owner completed one full
playback and accepted v2 in 41 seconds wall-clock time. The complete
feedback-to-v2 assisted workflow took 449 seconds and changed six pitches.
These are valid assisted-correction and final-review measurements, but direct
owner note-edit time was not measured. ADR 0005 now accepts this explicitly
named workflow as sufficient to authorize Task 007 research while preserving
direct owner edit time as unavailable and making no editor-efficiency claim.

The MedleyDB predominant-melody benchmark froze six windows and four candidate
routes before inference. A40 job `37690768` completed and sealed candidate-set
SHA-256
`f34359571dd3396197182c39f4c1c63dac6ae870ddbf49ec79bc6e384e4517c6`.
Final CPU evaluation job `37692231` completed with exit code `0:0`. At the
fixed inclusive 50-cent tolerance, GAME ranked first with overall accuracy
`0.7271`, raw pitch accuracy `0.6822`, voicing recall `0.9278`, and voicing
false alarm `0.2086`; Basic Pitch ranked second with `0.5564`, `0.4368`,
`0.8860`, and `0.2723`. The authoritative report SHA-256 is
`e4407cce7728e0990d0b3070edb43464ba60228296fb80aeb210ef0bc287ea68`.

The Vocadito dual-annotator note benchmark fixed six singers and both
trained-musician note transcriptions before candidate inference. A40 job
`37691274` completed and sealed candidate-set SHA-256
`4de9e1495687a255bf3d8f5244cb31235b781db70d1fc852ffb297fa764a21e7`.
Final CPU evaluation job `37692232` completed with exit code `0:0`. GAME ranked
first with macro per-track Amax onset+pitch F1 `0.7447` and
onset+pitch+offset F1 `0.4758`; its aggregate onset+pitch F1 was `0.5966`
against A1 and `0.7379` against A2. The authoritative report SHA-256 is
`f38c2c0d31086418b40ef10e2a9c437c7c76d2771794176b5e9559e64e7a0d60`.
Amax is retained only as an optimistic summary; A1/A2 results remain visible.

Final `/review` found nine P1/P2 issues. All were fixed with regression tests:
note-level corrected seeds can now be audited and sealed; Hyak candidate paths
relocate by run identity and hashes; contour and note references bind to the
same selected source records; formal contour manifests record command,
configuration, code, host, device, and timestamps; non-finite events are
rejected; and the correction proxy no longer claims to be an edit-action lower
bound. Task 006 acceptance criteria pass. ADR 0005 subsequently authorized
Task 007 from the measured assisted workflow without claiming direct-edit
efficiency.

Task 007 now implements deterministic main-melody clustering, eight explicit
features, development-only source reliability and isotonic confidence,
survivor-aware overlap handling, full candidate/rejection provenance, stable
worker-route binding, and immutable blind fusion evaluation. ADR 0006 records
the architecture and requires the fusion run plus the complete scoring
protocol to be sealed before any blind reference is loaded.

The fixed Task 007 Vocadito split uses six development singers and six new
blind singers, disjoint from each other and from all six Task 006 blind
singers. A40 candidate job `37705578` completed in `00:23:17`; development
calibration job `37705582`, blind fusion/seal job `37706932`, and final
evaluation job `37706934` all completed on Hyak CPU compute nodes with exit
code `0:0`. Candidate-set SHA-256 is
`e2584762d81911d8685b45aecbbdf4949d1f4d9c2824289d9a6d6312ca6bb403`,
and fusion evaluation-seal payload SHA-256 is
`50181e0c74a22396b9d1fe2770c0750351f890dc17a2c6039332794cfa12f520`.

GAME remained the strongest single blind baseline with macro Amax
onset+pitch F1 `0.7797` and onset+pitch+offset F1 `0.4316`. Full fusion scored
`0.7410` and `0.4332`: the `0.0016` offset-aware gain does not compensate for
the `0.0387` onset+pitch regression, so the frozen non-regression rule failed.
At confidence threshold `0.75`, fusion retained `41/293` evaluated-window
notes and reached precision `0.8556` at recall `0.1225`; the full
precision/coverage curve and all 12 ablations remain preserved.

Fusion and GAME have the same automated discrepancy rate, `85.3723` note
objects per minute. No matched human correction-time comparison or sealed
multi-track reference exists. Deterministic fusion v1 is therefore retained as
a reproducible rejected experiment, not promoted over GAME, and Gate 4 does
not pass. The authoritative report SHA-256 is
`8d529a72cdd9119f7eabf97cf64b6c4010c96d668de8a592a2a0cd896d0c5f75`.
All private Task 007 evidence was synchronized to the Mac and re-hashed
successfully. `make check` passes 186 tests; Ruff, Slurm shell syntax, Task 007
JSON, compile, and diff checks also pass. Final focused `/review` has no
remaining P0–P2 finding.

Task 008 now provides a model-agnostic Hyak batch layer with compute-node
frozen manifests, cross-manifest content-addressed
input/configuration/model/code/stage keys, atomic hash-verified stage
completion, persistent per-stage checkpoints, cleanup of unpublished stage
data, Slurm termination forwarding, append-only attempt indexes and logs,
serialized preflighted retention, and persistent raw/derived output archives.
The runtime binding preserves the virtualenv launcher and fingerprints its
resolved interpreter plus installed packages; Python entry points must be
frozen code artifacts. ADR 0007 records these boundaries without adding a
model dependency to the root environment.

Final smoke manifest `task008-smoke-v7` has SHA-256
`44c265b6f402798d4ed277fb2e7f94524747a432f5fac97f87061dc6f42de18d`;
freeze job `37712191` hashed it on compute node `n3467`. GPU scheduler
test-only checks `37712211` and `37712212` accepted STF L40S and checkpoint
A40 profiles without allocating GPUs. CPU array `37712213` deliberately
interrupted one row after completing its prepare stage while the other row
completed. Identical replay array `37712227` reused that prepare stage,
completed only the unfinished infer stage, and served the other row as a full
cache hit. Both finalizers (`37712215`, `37712230`) completed on compute nodes.

The final index reports both rows completed. Across four attempts it records
one deliberate interruption, two executions completed, one cache hit, an
execution failure rate of `1/3`, and a cache-hit rate of `1/4`. The index and
resource/failure summary SHA-256 values are
`766d07fedc4c360412b15cd724e7c0d635ebd519a7e259965703e0cdf37dfdb0`
and
`81e0b02708e69bac727d4ec9c9962f30ba283c900a3236d8419b59f2145da6ca`.
All four append-only attempts, ten attempt logs, selected and prepare outputs,
manifests, indexes, and scheduler logs were synchronized to the ignored local
`hyak-results/` area and re-hashed; interrupted-run `tmp/` is empty and the
synced manifest loads offline. The final resource summary counts `117,938`
bytes across all 14 directories in the shared cache root, not only v7 rows.
This smoke verifies batch mechanics only; it is not a transcription-quality or
GPU-throughput result.

Task 008 acceptance criteria pass. `make check` now passes 216 tests; Ruff
lint, Slurm shell syntax, JSON parsing, compile, and diff checks also pass.
Gate 4 remains
unchanged, so the native app task is still blocked by model/backend quality
rather than batch infrastructure.

The single final Task 008 `/review` reported two P1 findings and one P2. The
two blocking findings are fixed in `amt-batch-execution/v2`: every worker now
runs against cache-local immutable input/configuration/model/code snapshots,
and arbitrary inherited environment variables no longer reach a stage.
Explicit stage environment values remain supported and are part of the cache
key. Targeted regression tests cover both boundaries. Per the requested stop
rule, the P2 edge case for regular files placed directly in the cache root was
not expanded into additional infrastructure work.

Smoke v7 remains the authoritative Hyak scheduler, resume, cache, finalizer,
and retention evidence and predates this final P1 hardening. No additional
Hyak smoke was run. Task 009A and the model-independent waveform/review
surfaces in Task 009B1 are implemented; Task 009B2 inference integration
remains blocked.
