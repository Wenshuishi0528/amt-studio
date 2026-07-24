# Quality gates

Progress is controlled by evidence, not dates.

## Gate 0: Reproducible ingest

Pass when:

- a song with spaces and non-ASCII characters is ingested;
- original hash and audio metadata are recorded;
- canonical audio is deterministic;
- a fresh checkout can recreate the project structure;
- no private audio is tracked by Git.

## Gate 1: Reproducible single-model baseline

Pass when:

- MuScriptor or another direct full-mix model runs on Mac and Hyak;
- raw output, normalized events, MIDI, logs, model version, weights hash, command, device, runtime, and code commit are captured;
- repeated runs with deterministic settings are compared;
- errors are visible rather than hidden by postprocessing.

## Gate 2: Main-melody baseline set

Pass when:

- at least three independent candidate paths are available where feasible;
- a fixed human-confirmed reference set exists;
- note metrics and correction effort are measured;
- failure cases are categorized by separation, pitch, onset, offset, octave, harmony leakage, or melody selection.

## Gate 3: Multi-track baseline

Pass when:

- a stable instrument taxonomy is used;
- at least vocals/melody, drums, bass, and harmonic-other are evaluated separately;
- raw direct-mix and stem-conditioned results are retained;
- per-track precision, recall, F1, and coverage are reported;
- no aggregate score conceals weak tracks.

## Gate 4: Fusion proves value

Pass when:

- fusion is tuned without using the blind test split;
- it improves at least one primary metric without unacceptable regression in another;
- high-confidence precision is reported with coverage;
- the contribution of each path is measured by ablation;
- manual correction time improves on blind examples.

## Gate 5: Learned refiner proves value

Pass when:

- training/validation/test separation is auditable;
- the model beats deterministic fusion on blind references;
- calibration is measured;
- regressions by singer, genre, instrument, and recording type are reported;
- the checkpoint and training run are reproducible.

## Gate 6: Mac editor integration

Pass when:

- projects reopen without rerunning inference;
- playback and note cursor remain synchronized;
- editing operations are lossless and undoable;
- low-confidence review reduces correction time;
- exports round-trip through at least one external MIDI/notation application;
- a missing worker produces a clear message rather than corrupting the project.

## Primary evaluation outputs

For every benchmark snapshot produce:

- `metrics_by_track.csv`;
- `precision_coverage.csv`;
- `error_taxonomy.csv`;
- `correction_time.csv`;
- `run_manifest.json`;
- selected audio/MIDI comparison renders;
- a short interpretation that distinguishes measured facts from hypotheses.
