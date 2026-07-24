# Task 007: Deterministic fusion and confidence v1

Status: blocked by Task 006

## Objective

Fuse complementary candidate paths while preserving alternatives and provenance.

## Requirements

- Cluster candidates by onset, pitch, and duration tolerances.
- Build features for source agreement, worker reliability, stem quality, beat phase, duration, local continuity, register, and instrument presence.
- Implement separate main-melody selection.
- Calibrate confidence on development data only.
- Add ablations for each worker and rule.
- Preserve rejected candidates and reasons.

## Acceptance criteria

- Blind metrics and correction time improve over the strongest single baseline or the trade-off is explicitly rejected.
- Precision is shown against coverage.
- Main melody and multi-track metrics are separate.
- No hidden manual edits are included in automated results.
- Every final note points back to contributing candidates.

## Evidence

Codex: append evidence here.
