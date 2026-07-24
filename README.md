# AMT Studio

A quality-first, local-first research and product framework for automatic music transcription.

## Goal

Input a stereo song and produce:

- a dependable main-melody transcription;
- candidate instrument tracks such as vocals, drums, bass, keys, guitar, strings/synth, and other;
- performance MIDI that preserves expressive timing;
- score-oriented MIDI/MusicXML with tempo and notation quantization;
- confidence and provenance for every note so errors can be reviewed efficiently.

The repository is intentionally not a monolithic “one model does everything” application. It is a reproducible ensemble system with isolated model workers and a canonical event format.

## Root package

The dependency-light `amt_core` package handles:

- environment diagnostics;
- audio metadata and canonicalization;
- project/run manifests;
- note-event validation;
- worker command generation;
- artifact hashing and provenance.

Third-party models live in separate `workers/` environments.

## Quick start

```bash
./scripts/bootstrap_mac.sh
make check

mkdir -p data/private/inbox
cp "/path/to/song.mp3" data/private/inbox/

uv run amt init-project \
  "data/private/inbox/song.mp3" \
  --output "projects/private/song"

uv run amt show "projects/private/song"
```

Then follow `tasks/002_MUSCRIPTOR_BASELINE.md`.

## Repository map

```text
amt-studio/
├── src/amt_core/          lightweight orchestration and schemas
├── workers/               isolated third-party model environments
├── configs/               pipeline, model registry, taxonomy
├── schema/                interoperable JSON schemas
├── scripts/               Mac and Hyak operations
├── slurm/                 reproducible Hyak jobs
├── tasks/                 ordered Codex tasks with acceptance tests
├── docs/                  product, architecture, evaluation and runbooks
├── data/private/          local private input, never committed
├── projects/private/      local project artifacts, never committed
└── weights/               external model weights, never committed
```

## Current status

Tasks 001–005 are complete and Task 006 is ready to begin. See `STATUS.md` for
verified evidence, `HANDOFF.md` for the current Mac/Hyak operating state and
next-task entry point, and `CHANGELOG.md` for task-level history. No
transcription-accuracy claim is made before human reference annotations exist.
