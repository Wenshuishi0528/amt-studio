# Task 010: Learned note reranker/refiner

Status: blocked by fixed references and correction data

## Objective

Train the first project-owned learned component to improve candidate selection and correction. Do not train a large end-to-end AMT model by default.

## Initial task formulation

Input: candidate note clusters plus audio/stem/context features.

Outputs:

- keep/delete probability;
- melody probability;
- corrected octave/pitch class;
- onset/offset adjustment;
- instrument reassignment;
- calibrated confidence.

## Requirements

- Song/artist-disjoint splits.
- Baseline logistic/gradient-boosted model before a sequence neural model.
- Feature ablations and calibration.
- Reproducible Hyak training with resumable checkpoints.
- Evaluate blind metrics and correction effort.
- Preserve raw candidate features and label provenance.

## Acceptance criteria

- Beats deterministic fusion on a predeclared primary metric without unacceptable coverage or track regressions.
- Calibration improves or is explicitly handled post hoc.
- Checkpoint, data manifest, environment, and code are fully reproducible.
- Failure slices are reported.
- The model can be disabled without making projects unreadable.

## Evidence

Codex: append evidence here.
