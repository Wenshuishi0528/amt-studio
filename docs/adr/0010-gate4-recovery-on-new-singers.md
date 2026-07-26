# ADR 0010: Recover Gate 4 only on previously unexposed singers

## Status

Accepted

## Context

Deterministic fusion v1 was rejected because it regressed blind onset+pitch F1
and did not establish matched correction-effort improvement. Its revealed
Vocadito blind results are now diagnostic-only. Task 009B2B cannot select a
production inference route while Gate 4 remains open, and Task 010 lacks a
valid reason to train before another bounded deterministic test.

Vocadito v3 still contains eleven singers that were not used by Task 006 or
Task 007 v1. Each has at least one dual-annotator note reference. This permits a
new singer-disjoint experiment without new data access or a changed annotation
protocol.

## Decision

Pause Task 009B2B and run Task 007B:

- choose one track per previously unexposed singer using metadata only;
- freeze five development singers and six blind singers before inference;
- keep only GAME and Basic Pitch in deterministic fusion v2;
- use revealed v1 results only to motivate route removal;
- fit reliability, threshold, and confidence on the new development split;
- seal the new blind candidate set and fusion before reading blind references;
- require a `0.01` absolute onset+pitch F1 improvement and at most `0.01`
  onset+pitch+offset F1 regression before asking for human correction work;
- reject without blind retuning if the automatic precondition fails.

Task 009B2B and Task 010 remain blocked until this experiment is resolved.

## Consequences

The new result has a narrow scope: short, solo-vocal Vocadito excerpts. Passing
does not prove full-song, accompanied, instrumental, or multi-track accuracy.
Gate 4 still requires a matched human-correction comparison after the automatic
precondition passes.

The experiment avoids restricted downloads and keeps heavy inference on Hyak
compute nodes. The Mac remains responsible for orchestration, validation,
documentation, and result synchronization.
