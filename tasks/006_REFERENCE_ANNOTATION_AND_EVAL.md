# Task 006: Human reference set and evaluation harness

Status: blocked by Task 005

## Objective

Create a fixed, auditable benchmark before tuning fusion or training.

## Requirements

- Choose excerpts that cover lead vocal, chorus/harmony, instrumental intro/interlude, dense accompaniment, vibrato/glissando, and weak notes.
- Define train/dev/blind-test policy even if training has not started.
- Create human-confirmed main-melody references first.
- Add selected drum, bass, and harmonic-track references gradually.
- Store ambiguity and annotator confidence.
- Implement note metrics, octave errors, instrument assignment, confidence/coverage, and correction effort logging.

## Acceptance criteria

- Blind excerpts are frozen and cryptographically identified.
- Baseline metrics are computed without tuning on blind data.
- Every metric states tolerance and definition.
- A report separates measured results from listening impressions.
- Manual correction protocol is reproducible.

## Evidence

Codex: append evidence here.
