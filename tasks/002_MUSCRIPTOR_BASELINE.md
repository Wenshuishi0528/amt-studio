# Task 002: Direct full-mix MuScriptor baseline

Status: blocked by Task 001

## Objective

Run a pinned MuScriptor large baseline on the full canonical mix on Mac M4 and Hyak L40. Preserve native JSONL, MIDI, logs, environment, weight hashes, runtime, and normalized events.

## Required comparisons

- Mac M4/MPS, large, default decoding.
- Mac M4/MPS, large, beam size 4.
- Hyak L40, large, beam size 4 with prelude forcing.
- Optional instrument-constrained decodes only after the unconstrained result is saved.

## Implementation requirements

- Create isolated worker environments on Mac and Hyak.
- Pin package version or Git commit.
- Locate and hash downloaded model weights.
- Capture `muscriptor --help`, `list-instruments`, and device diagnostics.
- Generate native JSONL and MIDI in separate immutable run directories.
- Write a native-to-canonical adapter with fixture tests.
- Preserve model instrument names before product taxonomy mapping.
- Record wall time and peak memory if available.

## Acceptance criteria

- At least one successful Mac run and one successful Hyak run.
- Both have complete run manifests and output hashes.
- Canonical events validate with `amt validate-events`.
- Event counts, instrument counts, pitch ranges, and durations are summarized.
- Auralized or external MIDI playback is inspected and notes are recorded without claiming ground-truth accuracy.
- Repeatability or nondeterminism is measured on one short excerpt.

## Evidence

Codex: append evidence here.
