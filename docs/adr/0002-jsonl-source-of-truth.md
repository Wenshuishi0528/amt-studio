# ADR 0002: JSONL note events are canonical

Status: accepted

## Context

MIDI cannot reliably preserve model provenance, calibrated confidence, multiple candidates, arbitrary metadata, continuous pitch summaries, and edit history.

## Decision

Use versioned JSONL note events as the canonical interchange. Export MIDI and MusicXML from canonical events.

## Consequences

- no information is lost when combining models;
- debugging and evaluation remain transparent;
- the Mac editor can expose uncertainty;
- exporters must be maintained and tested.
