# ADR 0008: Gate the native editor from research inference

Status: accepted for Task 009 shell work

Date: 2026-07-25

## Context

Gate 4 remains open because deterministic fusion v1 did not improve the
primary blind metrics without an unacceptable regression. That prevents
shipping the current research pipeline as a stable product backend. It does
not invalidate the already versioned canonical project and note-event
contracts, nor does it prevent measuring whether a native editor can reopen,
play, edit, and export those artifacts without inference.

The application must remain useful when a model pack is absent, and Hyak must
not become a product dependency.

## Decision

Start Task 009 with a gated native shell:

- `apps/AMTStudioMac` is an independent Swift Package. `AMTStudioCore` owns
  project loading, note validation, non-destructive edit history, and
  performance-MIDI export without importing SwiftUI or model libraries.
- The app opens existing `manifest.json` plus
  `exports/*/canonical_project.json` projects without launching a subprocess.
- Base JSONL events are immutable. Immutable operation records, the current
  materialization, and the undo cursor are rewritten atomically under
  `annotations/corrections/`; abandoned undo branches remain in the audit
  log.
- SwiftUI and AVFoundation are adapters over that core. A generic local
  process controller may call the lightweight `amt` CLI for ingest or backend
  checks, but UI state never parses model-specific stdout.
- Missing CLI/model packs are explicit unavailable states. No inference
  button may imply that the rejected fusion path is a production default.
- Hyak remains an optional research executor and is never contacted while
  opening, editing, playing, or exporting a local project.
- Existing write directories and files are rejected when they are symbolic
  links, so a project cannot redirect editor output outside its root.

## Consequences

The editor shell can be built and tested while Gate 4 remains open. Completing
the shell does not pass Gate 4, select a production model, or authorize model
packaging. True end-to-end inference integration and any accuracy promise
remain blocked until the backend gates pass.
