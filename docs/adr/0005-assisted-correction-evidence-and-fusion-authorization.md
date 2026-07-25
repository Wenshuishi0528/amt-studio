# ADR 0005: Assisted correction evidence and fusion authorization

Status: accepted

Date: 2026-07-25

## Context

Gate 2 originally required measured correction effort before Task 007. The
first browser editor did not provide a trustworthy owner-operated editing
session, so its attempted timer cannot be used as direct manipulation
evidence.

The replacement workflow produced auditable but different evidence:

- Codex corrected six score-reading pitch errors from the owner's problem
  report to the accepted V2 artifact in 449 seconds wall-clock time;
- the owner completed one full playback of the piano-forward 12-second review
  and accepted it in 41 seconds wall-clock time;
- the owner did not directly drag, resize, or save the notes, so direct
  owner-operated note-edit time remains unmeasured;
- the owner's estimate above 95 percent is a subjective listening judgment,
  not a formal accuracy metric.

Blocking deterministic fusion until a particular editor interaction is usable
would mix product-UI validation with research-pipeline validation. Ignoring the
missing direct-edit measurement would overstate the evidence.

## Decision

Gate 2 accepts a named correction workflow when its correction and final-review
timers are measured separately and its unmeasured components are explicit.
For the current private `blind-04` evidence:

- `assisted_correction_wall_clock_sec = 449`;
- `owner_final_review_wall_clock_sec = 41`;
- `owner_final_review_playback_count = 1`;
- `owner_direct_note_edit_sec = unavailable_not_measured`.

This satisfies Gate 2's requirement that correction effort be measured and
authorizes Task 007 deterministic-fusion research. It does not demonstrate
that the current editor is efficient or that owner-operated correction time
improved.

Task 007 calibration and selection thresholds may use development data only.
Already revealed blind results remain evaluation-only. Gate 4 requires a
matched baseline-versus-fusion comparison using the same correction workflow.
Until direct owner editing is measured, reports must show assisted correction
time and owner final-review time as separate fields and keep direct edit time
unavailable.

## Consequences

- Task 007 can proceed without treating the browser editor as validated.
- Correction-time comparisons remain honest and reproducible across candidate
  versions.
- The project cannot claim direct editing-speed improvement from the current
  evidence.
- Gate 4 may explicitly reject a fusion trade-off, but it passes only after
  blind metrics, ablations, precision versus coverage, and matched
  correction-effort evidence are recorded.
