# ADR 0009: Permit model-independent review surfaces before backend promotion

Status: accepted for Task 009B1

Date: 2026-07-25

## Context

Gate 4 remains open and therefore still blocks audio import that immediately
launches inference, production worker selection, model-pack packaging, and
claims that the rejected deterministic fusion route is the product backend.
Task 009A nevertheless established that existing canonical audio and note
events can be opened safely without inference.

Two planned editor surfaces do not require a production backend: a waveform
derived from the already verified canonical audio and a review queue derived
from confidence values already present in the selected candidate track.
Keeping the placeholder note-density graphic would be less accurate than
rendering the real audio samples.

## Decision

Allow a bounded Task 009B1 editor slice while Gate 4 remains open:

- decode the existing canonical audio to a fixed-size peak envelope on a
  cancellable utility task on the Mac;
- display that envelope as the original-audio waveform synchronized with the
  existing transport cursor;
- let the user filter and navigate notes by a threshold within the currently
  selected candidate track;
- exclude missing confidence values instead of treating them as low
  confidence;
- label values as uncalibrated source-model confidence and forbid comparisons
  across candidate models.

This slice does not add audio import, invoke a local or remote worker, contact
Hyak, choose a default inference route, or pass Gate 4.

## Consequences

The existing-project editor gains honest audio context and a usable review
surface without controlling research choices. Current canonical Task 005
tracks do not provide confidence values, so their queue correctly remains
empty and reports the missing count. Backend import, progress/cancellation,
worker discovery, model packs, and production inference remain blocked.
