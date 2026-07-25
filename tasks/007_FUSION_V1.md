# Task 007: Deterministic fusion and confidence v1

Status: complete — v1 trade-off rejected

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

### Authorization and fixed inputs

- ADR 0005 records the accepted named Gate 2 workflow: 449 seconds of
  assistant-mediated correction, 41 seconds for one owner final-review
  playback, and direct owner note-edit time explicitly unavailable. This
  authorizes deterministic-fusion research without claiming editor
  efficiency.
- ADR 0006 freezes the deterministic main-melody architecture and requires a
  pre-scoring blind fusion seal.
- `configs/task007/vocadito_v3_split.json` fixes six development singers and
  six blind-test singers, disjoint from each other and from all six Task 006
  Vocadito blind singers. Its SHA-256 is
  `5361efa948f7e0e71e3486dbe0fe38d5204180000631d1fb6994cd09ce1aa88b`.
- Stem quality, instrument presence, clustering tolerances, feature weights,
  and the initial threshold were hash-frozen and synchronized before
  development scoring.

### Implementation

- `src/amt_core/fusion.py` implements deterministic clustering, one-event-per-
  source agreement, profile-weighted representatives, eight explicit
  features, main-melody competition, survivor-aware overlap clipping,
  candidate/rejection provenance, and development-only isotonic confidence.
- `scripts/calibrate_fusion.py` learns source reliability, confidence, and a
  frozen raw-score threshold from development references only.
- `scripts/run_fusion.py` verifies standard worker results, project/canonical
  lineage, stable worker/model/input/decoding route bindings, and exact input
  accounting before publishing an immutable fusion run.
- `scripts/evaluate_fusion.py` requires a blind fusion seal that binds the
  candidate seal, all fusion/provenance/rejection artifacts, development
  calibration, scoring protocol, and direct scoring-source hashes before any
  blind reference is loaded. Worker and feature ablations do not reuse the
  full model's calibrator.
- Slurm entrypoints 25–29 keep preparation, A40 candidate inference,
  development calibration, blind fusion/sealing, and blind evaluation on Hyak
  compute nodes.

### Verification

- Candidate and scoring routes are hash-bound and deterministically replayed;
  label substitution, incomplete outputs, changed clusters, changed scoring
  config, and output overwrites have regression coverage.
- Precision-versus-coverage uses only events inside frozen evaluation windows.
- Main-melody metrics and the unavailable multi-track reference are reported
  separately; automated discrepancy is not described as human edit time.
- Focused `/review` closed four P1 and two P2 findings. Final review found no
  remaining P0–P2 issue.

### Hyak execution and blind result

- Data preparation jobs `37705519` and idempotent replay `37705562` completed
  with exit code `0:0`. Candidate job `37705578` ran both fixed splits on one
  A40 and completed in `00:23:17`, then wrote the four-route blind candidate
  seal before quality inspection.
- Development calibration job `37705582` completed in `00:01:02` and selected
  raw-score threshold `0.625`. Its manifest records
  `blind_data_used_for_tuning=false`.
- Blind fusion/seal job `37706932` completed in `00:00:14`; only after its
  evaluation seal existed did evaluation job `37706934` run and complete in
  `00:00:34`. All four final jobs exited `0:0` on Hyak compute nodes.
- Blind benchmark freeze SHA-256 is
  `a400577437d062251e038295aa3913b98b74a435a6e401696145cb61cead3f0e`;
  candidate-set SHA-256 is
  `e2584762d81911d8685b45aecbbdf4949d1f4d9c2824289d9a6d6312ca6bb403`;
  fusion evaluation-seal payload SHA-256 is
  `50181e0c74a22396b9d1fe2770c0750351f890dc17a2c6039332794cfa12f520`.
- On six blind singers, GAME remained the strongest single baseline:
  macro Amax onset+pitch F1 `0.7797` and onset+pitch+offset F1 `0.4316`.
  Full fusion scored `0.7410` and `0.4332`, respectively. Offset-aware F1
  improved only `0.0016`, while onset+pitch F1 regressed `0.0387`; the frozen
  two-primary-metric rule therefore failed.
- At calibrated confidence threshold `0.75`, fusion retained 41 of 293
  evaluated-window notes (`0.1399` retention) with onset+pitch precision
  `0.8556` and recall `0.1225`. The full curve remains in
  `precision_coverage.csv`.
- Removing beat phase changed nothing because no beat evidence was supplied.
  Removing either MuScriptor route improved full-fusion pitch F1, while
  removing GAME caused the largest worker ablation loss. These are blind
  diagnostics only and were not used for retuning.
- Fusion and GAME had the same automated note-object discrepancy rate,
  `85.3723` per minute. Matched human correction time was not measured and
  multi-track reference metrics were unavailable; neither value was inferred.
- Decision: do not promote deterministic fusion v1. Keep GAME as the
  main-melody baseline and explicitly reject the fusion trade-off because a
  primary metric regressed and correction-efficiency improvement is
  unavailable. Gate 4 does not pass.
- The authoritative evaluation report SHA-256 is
  `8d529a72cdd9119f7eabf97cf64b6c4010c96d668de8a592a2a0cd896d0c5f75`.
  Calibration, fusion, seals, and evaluation outputs were synchronized to the
  ignored local private-project area; every manifest-recorded output and all
  11 sealed scoring-source hashes were reverified.
- `make check` passes all 186 tests. Ruff, Task 007 JSON parsing, Slurm
  `bash -n`, compile checks, and `git diff --check` also pass.
