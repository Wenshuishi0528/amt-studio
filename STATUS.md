# Project status

Current gate: Gate 1 passed under the user-directed Hyak compute boundary
Current task: `tasks/003_SOURCE_SEPARATION.md` complete
Next task: `tasks/004_VOCAL_MELODY_BASELINE.md`
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

Not yet verified:

- any note, instrument, melody, or score accuracy against human reference;
- GAME, Basic Pitch, Beat This, fusion, training, or SwiftUI.

Task 003 is complete. Task 004 may use the selected BS-Roformer vocal stem
while retaining Demucs as the multistem fallback. No transcription-accuracy
claim is made before human reference annotations exist.
