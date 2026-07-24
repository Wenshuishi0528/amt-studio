# Task 009: Native macOS application shell

Status: blocked by stable backend gates

## Objective

Build a native SwiftUI application around the stable project format and backend API without embedding model-specific assumptions.

## Requirements

- Project import/open/save.
- Background job progress, cancellation, and error reporting.
- Waveform, piano roll, transport, track mixer, and synchronized audio/MIDI preview.
- Confidence review queue.
- Non-destructive note editing with undo/redo.
- Performance MIDI export first; MusicXML after notation tests.
- Missing worker/model packs produce actionable messages.

## Acceptance criteria

- Existing projects open without inference.
- Editing and playback remain synchronized.
- Projects survive app restart.
- Exported MIDI opens in at least two external applications.
- UI tests cover import, job failure, edit, undo, and export.

## Evidence

Codex: append evidence here.
