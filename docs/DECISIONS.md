# Current decisions

These decisions are defaults, not immutable beliefs. Change them only with measured evidence and an ADR.

## D-001: Quality-first ensemble instead of one universal model

Use a direct full-mix model plus stem-conditioned specialized models. A universal model remains a candidate, not the entire architecture.

## D-002: Main melody is independently protected

Full multi-track output can be incomplete while main melody still succeeds. Main melody receives its own baselines, evaluation set, fusion logic, export, and user controls.

## D-003: JSONL events are the source of truth

MIDI is lossy for provenance, uncertainty, candidate alternatives, expressive pitch, and edit history. MIDI and MusicXML are generated artifacts.

## D-004: Separate performance and score outputs

A faithful expressive transcription and a readable score have different timing objectives. Keep both.

## D-005: Isolated model workers

MuScriptor, GAME, Basic Pitch, separator, Beat This, and future models run in separate environments. Their interface is files and subprocess exit status.

## D-006: No large from-scratch model first

First build baselines and a fixed reference set. The first learned component should usually be a confidence/reranking/refinement model because it can learn from disagreements and corrections with less data.

## D-007: Hyak is a research executor, not a product dependency

Hyak handles large models, batches, sweeps, fine-tuning, and reproducibility. The final Mac product must remain usable without a live Hyak connection. Remote Hyak execution can remain an optional research mode.

## D-008: Native Mac editor later, Python research backend now

SwiftUI is the final interface. During model discovery, a stable Python CLI/service prevents UI work from controlling research choices. Conversion to CoreML/ONNX happens after quality is proven.

## D-009: Manual corrections are first-class data

Corrections are stored as auditable operations and can form an opt-in training/evaluation corpus. The original model output is never overwritten.

## D-010: “90%” requires metric and coverage

Any 90% claim must name target repertoire, instrument, tolerance, precision/recall definition, and coverage. High precision obtained by omitting most notes is not success.

## D-011: Current research model compute runs on Hyak

For the current research phase, the Mac is the front end and lightweight
project machine; model inference, separation, sweeps, and training run through
Slurm on Hyak. This temporary boundary is detailed in
`docs/adr/0003-hyak-research-compute-boundary.md` and does not change D-007's
long-term product goal.

## D-012: Keep assisted correction and direct editing evidence separate

Gate 2 may use an auditable assistant-mediated correction workflow to
authorize fusion research, but its total correction time, owner final-review
time, and direct owner-operated edit time are separate measurements. Missing
direct-edit time remains unavailable and cannot support an editor-efficiency
claim. See
`docs/adr/0005-assisted-correction-evidence-and-fusion-authorization.md`.

## D-013: Seal deterministic fusion before blind scoring

Task 007 uses development-only deterministic main-melody fusion. The blind
fusion output and complete scoring protocol are sealed before reference notes
are loaded or metrics are calculated; ablations do not reuse the full model's
calibrator. See
`docs/adr/0006-deterministic-fusion-and-blind-evaluation.md`.
