# ADR 0014: Make edits durable and product postprocessing non-destructive

Status: accepted for Task 009B2S

Date: 2026-07-26

## Context

The owner found three related product failures on a real song:

- a directed `voice` recovery returned many notes that duplicated already
  correct accompaniment;
- a clearly audible opening melody remained empty after the directed pass,
  which would otherwise require another manual submission;
- tail-fragment corrections were stored under one canonical bundle and appeared
  lost after a newer recovery bundle became current.

The raw MuScriptor output remains valuable evidence. Literal MIDI or audio
subtraction is not safe because an accompaniment can double a real melody, and
because independently decoded notes do not form sample-aligned signals.

## Decision

The product uses three bounded, traceable derivations:

1. A main-melody recovery keeps its directed raw candidates, removes candidates
   that strongly duplicate preserved accompaniment at the same pitch and time,
   and selects a monophonic non-overlapping path. The result remains a Beta
   candidate and makes no accuracy claim.
2. If a selected target still contains an empty span of at least three seconds,
   the same MuScriptor model gets one additional contextual decode without an
   instrument allowlist. Non-percussion predictions retain their original
   predicted instrument in provenance, are relabeled only as candidates, and
   pass through the same accompaniment mask. There is no recursive retry.
3. Product bundle generation applies conservative, per-track tail cleanup.
   Pitched accompaniment fragments become a derived sustain; dense drum-tail
   repeats become one short hit rather than a long drum note. Changed raw events
   are copied under `raw_tracks/`, and a cleanup report records every decision.

Application edit sessions additionally store the selected track artifact hash.
When a newer canonical bundle retains that exact track, its latest edit session
is migrated and saved under the new bundle. Legacy sessions without the hash
may migrate only when they contain a before-state and replay cleanly against
the new base notes. An explicit Save control and visible saved time expose the
state to the user.

## Consequences

The normal workflow no longer asks a user to perform a third recovery merely
because the directed pass left an obvious residual gap. Raw directed and
fallback candidates, source tracks, and prior bundles remain available for
diagnosis.

The soft mask can reject a true melody that is deliberately doubled in unison,
and tail patterns can be musically intentional. These rules therefore remain
conservative Beta product derivations with provenance and no formal accuracy
claim. A future benchmark may change thresholds, but it must not rewrite the
preserved raw artifacts.
