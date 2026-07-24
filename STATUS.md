# Project status

Current gate: Gate 1 passed under the user-directed Hyak compute boundary
Current task: `tasks/005_BEAT_AND_CANONICAL_EVENTS.md` complete
Next task: `tasks/006_REFERENCE_ANNOTATION_AND_EVAL.md`
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

Task 005 is complete. Its performance MIDI retains four unranked candidate
tracks; its score-grid JSONL is explicitly experimental and is not a formal
score. Gate 2 remains unpassed until Task 006 freezes human references and
computes held-out metrics.
