# Project status

Current gate: Gate 2 awaits a timed human-correction session
Current task: `tasks/006_REFERENCE_ANNOTATION_AND_EVAL.md` complete
Next task: measure human correction time before authorizing Task 007
Current branch: `main`

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
- candidate fusion, formal score quantization/MusicXML, training, or SwiftUI.

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
validation, but remain `awaiting_owner_review` and unsealed.

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
bound. Task 006 acceptance criteria pass, but Gate 2 remains pending because
no timed human correction session has been measured.
