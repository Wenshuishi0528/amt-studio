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
