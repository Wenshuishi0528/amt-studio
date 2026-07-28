# ADR 0013: Product GAME large and live whole-track fragment scan

Status: accepted

Date: 2026-07-27

## Context

The optional GAME product action failed before submission because discovery
searched only legacy cache directories while the verified assets lived under
the private product model directory. It also hard-coded the historical
Task 004 medium checkpoint. Separately, the track list could show a current
fragment count while the SwiftUI `Menu` retained an older disabled state.

## Decision

- Keep the Task 004 `GAME-1.0-medium` pins and results unchanged as historical
  research evidence.
- Use a separately hash-pinned official `GAME-1.0-large` checkpoint for new
  product-triggered GAME runs. Large means the highest-capacity official
  PyTorch release variant; it is not an accuracy claim.
- Discover only a uniquely matching large provenance from known private model
  roots. Never silently fall back to medium.
- Keep the fragment-repair action available on every track and refresh its
  diagnostics when invoked. Pitched tracks scan the complete song timeline.
  Drums retain their separate conservative tail-repeat treatment because
  repeated drum hits are not sustained notes.

## Consequences

Historical medium benchmarks remain reproducible. New GAME jobs require a
verified large provenance and fail with a specific installation message when
it is absent. Fragment repair remains explicit, saved, undoable, and
non-destructive to the immutable source bundle.
