# Task 005: Beat/downbeat map and canonical project model

Status: blocked by Task 004

## Objective

Finalize the worker request/result contract, canonical events, tempo/meter maps, and exporters without changing the raw baseline results.

## Requirements

- Integrate Beat This as an isolated worker.
- Store raw beat/downbeat timestamps.
- Implement versioned worker request and result manifests.
- Implement canonical note, tempo, meter, track, and provenance models.
- Add performance MIDI export.
- Add a first score-grid experiment, but keep score timing separate.
- Round-trip tests through at least one independent MIDI parser.

## Acceptance criteria

- All baseline workers normalize through one interface.
- Canonical events validate and retain source provenance.
- Performance MIDI exports without time drift.
- Raw versus quantized outputs are distinguishable.
- Tempo/downbeat uncertainty is recorded.

## Evidence

Codex: append evidence here.
