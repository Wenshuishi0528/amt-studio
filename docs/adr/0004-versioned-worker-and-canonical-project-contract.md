# ADR 0004: Version worker results and separate canonical performance from score-grid data

Status: accepted for Task 005

## Context

Tasks 002–004 produced reproducible worker runs, but each worker currently owns
its adapter and manifest details. Task 005 must consume those immutable results,
add beat/downbeat timing, and export MIDI without rewriting native model output
or silently turning an experimental quantization into the canonical
performance representation.

## Decision

Use `amt-worker-request/v1` and `amt-worker-result/v1` as the common file
contract. Existing schema-version-1 run manifests remain valid immutable
results and are loaded through the same result adapter; new workers record the
explicit contract identifier.

The canonical project bundle references verified worker manifests and
normalized artifacts by SHA-256. It keeps each baseline melody path as a
separate candidate track until Task 007 fusion.

Canonical timing has two separate forms:

- performance notes retain onset and offset in original-mix seconds;
- score-grid notes are derived records containing beat-grid coordinates and
  provenance back to performance notes.

Beat This supplies raw beat/downbeat times and framewise logits. Tempo and
meter maps are derived artifacts with explicit method and uncertainty fields;
they never overwrite the raw rhythm output.

Performance MIDI is an export from canonical performance notes. JSON/JSONL
remains the source of truth for floating pitch, provenance, confidence, and
candidate identity.

## Consequences

- Task 002–004 raw artifacts and manifests are not modified.
- All baseline results can be verified and opened through one model-agnostic
  interface.
- Candidate tracks remain comparable and reversible instead of being fused by
  accident.
- Performance and score timing cannot be confused by sharing the same event
  type or output file.
- MIDI timing must be round-trip tested through an independent parser.
- The first score-grid experiment is not a notation-quality or accuracy claim.
