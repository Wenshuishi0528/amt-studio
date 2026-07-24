# Project status

Current gate: Gate 1 passed under the user-directed Hyak compute boundary
Current task: `tasks/002_MUSCRIPTOR_BASELINE.md` complete
Next task: `tasks/003_SOURCE_SEPARATION.md`
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

Not yet verified:

- any note, instrument, melody, or score accuracy against human reference;
- source-separation, GAME, Basic Pitch, Beat This, fusion, training, or SwiftUI.

Task 003 may begin after review of the Task 002 commit.
