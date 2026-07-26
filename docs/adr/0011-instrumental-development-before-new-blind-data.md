# ADR 0011: Require an instrumental development probe before new blind data

## Status

Accepted

## Context

Task 007 and Task 007B rejected two deterministic vocal-fusion routes. GAME
remains the strongest vocal baseline, but the owner also observed that
instrumental introductions and interludes can be missed or inconsistently
transcribed. The completed Vocadito splits contain solo voice only and cannot
answer whether the product's automatic main-melody path works without vocals.

The existing MedleyDB Sample includes `Phoenix_ScotchMorris`, an instrumental
track from an artist not used by the existing vocal benchmarks. Its provenance
already labels it as development data, so it cannot supply a new blind claim.
It can still cheaply falsify a proposed instrumental route before requesting
or downloading another restricted dataset.

## Decision

Run Task 007C as one fixed development probe:

- Basic Pitch operates directly on the canonical instrumental mix using its
  pinned defaults;
- direct-mix output is explicitly labeled as unknown instrument (`other`),
  not voice;
- six time-distributed windows and the Melody 1 projection are fixed before
  inference;
- the candidate is sealed before reference scoring;
- only a result meeting all predeclared pitch, overall-accuracy, and voicing
  thresholds may advance to a new artist-disjoint blind benchmark;
- a failure scopes v1 to lead-vocal melody and is not retuned on Phoenix.

The revealed Task 007/007B blind outputs remain diagnostic-only. Task 007C does
not combine them with Phoenix, alter fusion, or train a model.

## Consequences

Passing Task 007C is only permission to acquire and freeze new blind data. It
is not Gate 4, a production route, or an accompanied-pop accuracy claim.
Failing avoids unnecessary data acquisition and Hyak work, while making the
v1 product limitation explicit.

All audio, annotations, outputs, and dataset provenance remain private.
Canonicalization and inference run in Slurm compute allocations; the Mac
continues to handle source changes, orchestration, lightweight validation, and
evidence synchronization.

## Outcome

Task 007C failed all three predeclared development conditions. Raw pitch
accuracy was `0.6932`, overall accuracy was `0.3339`, and voicing false alarm
was `0.9648`. The direct-mix instrumental route is rejected for v1, Phoenix
retuning is prohibited, and no new instrumental blind set is acquired for this
route. The next research slice is lead-vocal-only.
