# Architecture

## Why the system is modular

Full-song transcription combines source separation, instrument detection, note decoding, beat/downbeat tracking, melody selection, timing quantization, notation, confidence estimation, and editing. These subproblems have different best models and incompatible dependency stacks. The architecture therefore treats models as replaceable workers.

## High-level data flow

```text
                         ┌─────────────────────────────┐
Original stereo mix ────►│ project ingest + hashing   │
                         └──────────────┬──────────────┘
                                        │ canonical audio
                 ┌──────────────────────┼──────────────────────┐
                 │                      │                      │
                 ▼                      ▼                      ▼
       direct full-mix AMT       source separation       beat/downbeat
       (MuScriptor, etc.)        candidate ensembles     tracker
                 │               │   │   │   │                │
                 │               │   │   │   │                │
                 │               ▼   ▼   ▼   ▼                │
                 │             vocals drums bass other        │
                 │               │     │    │    │             │
                 │               ▼     ▼    ▼    ▼             │
                 │             GAME / specialized /            │
                 │             Basic Pitch / conditioned AMT   │
                 └──────────────────────┬───────────────────────┘
                                        ▼
                             canonical candidate events
                                        ▼
                        alignment, deduplication, provenance
                                        ▼
                     confidence calibration + fusion/reranking
                                        ▼
                       performance tracks + main melody choice
                                        ▼
                      tempo/meter-aware notation quantization
                                        ▼
                    MIDI / MusicXML / audio render / Mac editor
```

## Execution layers

### Layer A: `amt_core`

A lightweight Python package that is safe to install on the Mac and Hyak. It owns project structure, schemas, manifests, worker invocation, validation, hashing, caching, evaluation orchestration, and exports.

### Layer B: isolated workers

Each worker has its own Python version and environment. A worker accepts an input request JSON and writes:

- a result manifest;
- raw native model output;
- normalized candidate `events.jsonl`;
- optional MIDI or audio previews;
- logs and diagnostics.

A failed worker cannot corrupt another worker's environment.

### Layer C: research pipeline

Runs workers, compares configurations, evaluates against references, and builds fused tracks. It can execute locally or through Slurm.

Hyak batch experiments use frozen manifest rows and content-addressed stage
caches. A cache hit is valid only after output re-verification. Every declared
raw and derived output, its selected-output markers, append-only attempt
provenance, and experiment indexes live in persistent storage before cache
retention. The cache key also binds the virtualenv launcher, resolved Python
runtime, installed-package fingerprint, and frozen code used by expanded
repository commands. Python entry points must be frozen artifacts. Retention
measures the complete shared cache root, serializes deletion against active
rows, and removes terminal incomplete caches only after attempt records and
logs are persistent; unpublished intermediates and resumable stage checkpoints
may live in scrubbed storage.

### Layer D: macOS application

SwiftUI/AVFoundation front end. During research it invokes the Python backend as a local subprocess or service. Once the algorithms stabilize, selected workers can be converted to CoreML/ONNX or bundled separately. Do not force early model conversion at the expense of accuracy.

The gated Task 009A shell is narrower: it opens, validates, plays, edits, and
exports already existing canonical projects with no subprocess or network
dependency. `AMTStudioCore` owns the model-free contracts; SwiftUI and
AVFoundation are adapters. Task 009B may add the versioned job API only after
the backend gate passes.

## Project directory contract

```text
projects/private/<project-id>/
├── manifest.json
├── audio/
│   ├── original/          immutable imported file or reference link
│   ├── canonical/         normalized lossless mix
│   └── stems/             worker-specific stem sets
├── annotations/
│   ├── references/        human-confirmed notes
│   └── corrections/       editor changes and atomic audit history
├── app/
│   └── workspace.json     selected bundle/track and restart state
├── runs/
│   └── <run-id>/
│       ├── request.json
│       ├── run_manifest.json
│       ├── raw/
│       ├── normalized/events.jsonl
│       ├── previews/
│       └── logs/
├── fusion/
│   └── <fusion-run-id>/
├── exports/
└── reports/
```

## Canonical note event

Each JSONL record represents a note candidate or a final note. Required concepts:

- stable event ID;
- source run and source model;
- track/instrument hypothesis;
- onset and offset in original timeline seconds;
- floating MIDI pitch and optional quantized MIDI pitch;
- velocity when available;
- confidence and calibration version;
- performance/score status;
- provenance IDs to all contributing candidates;
- tags for pitch bend, slur, uncertainty, and edits.

## Direct mix and separated-stem paths

Both paths are retained because separation can remove weak notes or create artifacts. Direct full-mix models can preserve context but confuse instruments. Stem-specialized models can be more precise while inheriting separation errors. Fusion is justified only after blind evaluation shows complementary error patterns.

## Main-melody subsystem

The main melody is selected from:

1. lead-vocal worker candidates;
2. direct multi-instrument model candidates tagged as vocals or lead instruments;
3. instrumental salience candidates;
4. user-selected instrument constraints.

The selector should use note continuity, register, phrase structure, source agreement, stem salience, and user input. It must preserve alternatives around handoffs and ambiguous passages.

## Fusion strategy progression

1. deterministic candidate clustering and rules;
2. calibrated per-worker reliability by instrument and repertoire;
3. learned note-level reranker/refiner;
4. sequence-level track consistency model;
5. only then consider joint end-to-end fine-tuning.

This progression extracts value from strong pretrained models and creates labeled error data before expensive training.
