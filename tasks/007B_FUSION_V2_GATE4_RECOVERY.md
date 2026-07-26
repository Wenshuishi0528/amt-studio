# Task 007B: Gate 4 recovery with a new blind split

Status: complete — automatic precondition failed; v2 rejected without blind retuning

## Objective

Test one constrained deterministic-fusion v2 hypothesis without reusing the
revealed Task 007 blind split for tuning.

Task 009B2B remains paused. Task 010 does not start.

## Frozen hypothesis

Keep GAME as the anchor route and Basic Pitch as the only complementary route.
Do not include either MuScriptor route. This choice is motivated by Task 007 v1
diagnostics, where GAME was the strongest baseline and removing either
MuScriptor route improved pitch F1. Those revealed results define no Task 007B
weight, reliability, threshold, calibration value, or acceptance threshold.

## Frozen data

Use one track per previously unexposed Vocadito singer:

- development: `12/S9`, `20/S15`, `23/S18`, `29/S23`, `33/S26`;
- blind: `19/S14`, `21/S16`, `22/S17`, `26/S21`, `30/S24`, `32/S25`.

All eleven singers are disjoint from Task 006 and Task 007 v1. Tracks `28`,
`31`, and `40` are withheld because the selected sets already contain another
track from the same singer.

## Evaluation order

1. Freeze both benchmark packs and their dual-annotator references.
2. Generate and seal GAME and Basic Pitch candidates for both splits.
3. Calibrate source reliability, confidence, and the raw-score threshold using
   development only.
4. Generate blind fusion and its evaluation seal in one Slurm job before
   loading blind references.
5. Evaluate the sealed blind output once.
6. If the automatic precondition passes, prepare a matched blinded human
   correction comparison. Otherwise reject v2 without retuning.

## Automatic acceptance precondition

- Blind macro Amax onset+pitch F1 improves by at least `0.01` absolute over the
  strongest single-worker baseline.
- Blind macro Amax onset+pitch+offset F1 regresses by no more than `0.01`.
- Precision versus coverage and GAME/Basic Pitch ablations are retained.
- No v1 blind result, v2 blind reference, or user listening feedback is used
  for v2 calibration.

This automatic precondition is necessary but not sufficient for Gate 4.
Matched correction effort under one named workflow remains required.

## Stop rule

Do not retune on Task 007B blind output. If the automatic precondition fails,
record the rejection and return to product/data strategy. Do not proceed to
Task 009B2B or Task 010.

## Evidence

### Frozen inputs

- Development selection manifest SHA-256:
  `1305f59355b83f477e590ee1d2dada84ef75f0c940768f32e2198a8b688623a5`.
- Blind selection manifest SHA-256:
  `1521d89ec9e0d4f5f697bcc9d912aacb41eca10d9d43d30b9093b31c7c61b373`.
- Development/blind benchmark-manifest SHA-256:
  `0deb80bcffdf40dac10cd5a6d27c9de522d0059a2a059cb4819344f72dafc39c`
  and
  `20dc2e9013d06fa7226d4fc1f74c4d324948d5f2a1474bf31d450290db0dee1d`.
- The official track 30 A1 annotation ends `2.77 ms` after the PCM frame
  boundary. The source CSV was not edited. Preparation and scoring instead
  preserve it under one explicit `5 ms` end-boundary quantization tolerance;
  `6 ms` remains rejected.

### Hyak execution

- Initial preparation job `37720460` exposed the official annotation boundary
  mismatch and failed before candidate inference. Its dependent jobs were
  canceled. Retry `37720512` completed on `n3115` in `00:00:51`.
- A40 job `37720513` completed on `g3046` in `00:11:37`, using an NVIDIA A40
  and source snapshot `8fa89852352f02089986389b6ba5c5abd5c03967`.
- Development calibration `37720514` completed on `n3319` in `00:01:18`.
  Calibration run-manifest SHA-256:
  `ed789ed6fc0594500fb478f65fcd29efa449abc604f26d5540ebe32e2ba05c4f`.
- Blind candidate-set seal SHA-256:
  `3022a656447cab707a643fd7dfe496cf27e1fcce2d8d2715eeb16c7d868e0ab1`;
  its frozen candidate-set payload hash is
  `65aaa0f660732115f73e0ee8ffe74fbca38bcbc0e399837da02fe35ac22f03fa`.
  It contains exactly GAME and Basic Pitch.
- The first seal attempt exposed an inherited three-candidate minimum. The
  verifier now defaults to three for Task 007 v1 and requires an explicit
  `--minimum-candidates 2` for Task 007B. No fusion output or score was changed.
- Fusion run-manifest SHA-256:
  `9a9d78950ed99c80c904d5dac307702d1f7ec59c95193a9e126c089ae618e5a6`.
  Final attempt-2 evaluation-seal SHA-256:
  `351a176eebe7a07df71075a8ed26ac22e454d662c8111905d534cf86051d0ffe`.
- Final seal job `37722126` and evaluation/assessment job `37722127` completed
  on `n3099` in `00:00:33` and `00:00:52`, both exit `0:0`, using scoring
  snapshot `6bc9da3c37fa2426c9b8dffbd5858e638d93b0c7`. The later task-commit amend
  changes documentation only, not frozen scoring-source hashes.

### Blind result and decision

- GAME: 355 events; macro Amax onset+pitch F1 `0.7814082068`;
  onset+pitch+offset F1 `0.3676085616`; automated discrepancy
  `113.3599438062/min`.
- Basic Pitch: 280 events; onset+pitch F1 `0.5274010553`;
  onset+pitch+offset F1 `0.3518540812`; discrepancy
  `117.7957676943/min`.
- Fusion: 279 events; onset+pitch F1 `0.6923501742`;
  onset+pitch+offset F1 `0.3276084961`; discrepancy
  `116.3171597316/min`.
- Relative to the strongest single worker, fusion regressed onset+pitch F1 by
  `0.0890580326` and onset+pitch+offset F1 by `0.0400000655`. Both frozen
  automatic checks failed.
- Evaluation report SHA-256:
  `ea66e1b20b3739478a56b89a0c5e104af55b959de15007de7f34dbded507a1f7`.
- Gate decision SHA-256:
  `4338127e5009589e2f336086d62b78a9b99be8630580ed380b671f8b238fd732`;
  decision `reject_v2_without_blind_retuning`; `gate4_passed=false`.
- No matched human correction was requested because the necessary automatic
  precondition failed. Task 007B blind output must not be reused for tuning.

### Verification and local evidence

- One repository `make check` passed before submission: 224 Python tests and
  17 Swift tests passed, with one expected private-integration skip.
- The single `/review` was run once. It produced no completed P0/P1 report
  before being stopped for expanding into unrelated old code. Actual blocking
  issues were found by the formal Hyak chain and fixed with affected-suite
  regression tests; final focused runs passed 19 tests and Slurm `bash -n`,
  compile, boundary-consistency, and `git diff --check`.
- Synced ignored evidence is under
  `projects/private/vocadito-task007b-{development,blind}-v2/`,
  `projects/private/task007b-logs/`, and
  `projects/private/task007b-data-logs/`. Local hashes match Hyak.

### Limitations

- The result applies only to the fixed, short, solo-vocal Vocadito excerpts.
  It is not a full-song, accompanied, instrumental, or multi-track claim.
- Amax is an optimistic per-excerpt annotator policy; both annotator results
  remain in the report.
- Automated note discrepancy is not human edit time. Human correction was
  deliberately not measured after the automatic rejection.
