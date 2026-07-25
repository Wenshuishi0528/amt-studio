# ADR 0006: Deterministic fusion and pre-scoring blind seal

Status: accepted

Date: 2026-07-25

## Context

The four Task 004 melody routes make different onset, pitch, duration, and
melody-selection errors. Selecting one route discards complementary evidence,
while an unconstrained learned refiner would exceed the available sealed
training evidence and make blind-data leakage harder to audit.

Task 007 therefore needs a fusion path whose inputs, rules, calibration data,
rejected alternatives, and blind evaluation order are reproducible.

## Decision

Task 007 uses deterministic main-melody fusion:

- candidates are clustered by frozen onset, pitch, and duration tolerances,
  with at most one event from each source contributing to a cluster;
- scoring uses source agreement, development-only worker reliability, declared
  stem quality, optional beat phase, duration plausibility, local continuity,
  register, and declared instrument presence;
- source profiles, the raw-score threshold, and isotonic confidence calibration
  are fit on the singer-disjoint development split only;
- every eligible input candidate remains represented in cluster provenance or
  a rejection record, and pre-filtered events retain their IDs and reasons;
- main melody is evaluated separately from multi-track transcription;
- blind candidate sets are sealed before output inspection;
- the blind fusion run and its evaluation seal are created in one Slurm job,
  before reference notes are loaded or quality metrics are calculated;
- the scoring protocol, required artifacts, source routes, and evaluator code
  are hash-bound by that seal before the separate evaluation job starts.

Worker and feature ablations keep the development-selected raw-score threshold
fixed and do not reuse the full model's isotonic calibrator, because removing
a worker or feature changes the feature-model identity. Missing beat evidence
is recorded as unavailable rather than synthesized.

## Consequences

- A blind result can be replayed from the exact four worker outputs and frozen
  development artifacts without hidden manual edits.
- Calibrated confidence is reported only for the unchanged full fusion model;
  ablation confidence remains unavailable.
- Precision-versus-coverage claims use only events inside the frozen evaluation
  windows.
- A metric improvement does not establish correction-efficiency improvement.
  If matched human correction time is unavailable, Gate 4 remains open and the
  deployment trade-off is rejected or reported inconclusive.
- This decision does not authorize learned refinement, training on private
  corrections, or a multi-track accuracy claim.
