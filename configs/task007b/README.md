# Task 007B Gate 4 recovery freeze

This directory freezes a new experiment before candidate inference.

- Development: tracks `12, 20, 23, 29, 33`.
- Blind test: tracks `19, 21, 22, 26, 30, 32`.
- Every selected track has a unique singer.
- All eleven singers are disjoint from Task 006 and Task 007 v1.
- Tracks `28`, `31`, and `40` are withheld because their singers already have
  one selected track.
- Selection used only the committed Vocadito metadata. Audio, annotations, and
  candidate output quality were not inspected.

The v2 hypothesis keeps only GAME and Basic Pitch. Task 007 v1 blind
diagnostics may motivate that hypothesis, but no v1 blind score may tune the
new source reliability, threshold, calibration, or pass rule.

Automatic Gate 4 precondition:

- improve blind macro Amax onset+pitch F1 by at least `0.01` absolute over the
  strongest single-worker baseline;
- do not regress blind macro Amax onset+pitch+offset F1 by more than `0.01`;
- preserve the full precision/coverage curve and both worker ablations.

If the automatic precondition fails, reject v2 without blind retuning. If it
passes, collect a matched, blinded human-correction comparison before declaring
Gate 4 passed.
