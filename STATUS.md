# Project status

Current gate: Gate 0 passed on the user's Apple Silicon Mac
Current task: `tasks/001_BOOTSTRAP_AND_INGEST.md` complete
Next task: `tasks/002_MUSCRIPTOR_BASELINE.md` (not started)
Current branch recommendation: `main`; create the initial commit after user review

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

Not yet verified:

- MuScriptor installation or inference;
- Hyak sync or Slurm jobs;
- any transcription accuracy;
- source-separation, GAME, Basic Pitch, Beat This, fusion, training, or SwiftUI.

Codex should update this file only after the active task's acceptance criteria are met.
