# ADR 0013: Automate same-model voice-gap recovery without replacing raw output

Status: accepted for Task 009B2G

Date: 2026-07-26

## Context

The private Beta currently submits one full-song MuScriptor job and returns an
editable multitrack bundle. On the owner's `STILL LOVE HER` project, the
full-song `voice` track contained long empty spans while its detected phrases
were usually useful. A second MuScriptor pass over shorter contextual clips
recovered 184 separate candidate notes, and the owner judged that recovery
useful on that song.

That one-song listening result does not prove that every empty `voice` span is
missing singing. Instrumental sections are valid empty spans, and a same-model
rerun can still produce false positives. Requiring a new user to find gaps,
re-upload the song, or submit another Hyak job would nevertheless expose an
internal diagnostic workflow as the product workflow.

## Decision

Task 009B2G makes gap recovery a conditional continuation of the original
private-Beta Slurm job:

- run the pinned full-song MuScriptor route first and preserve its immutable
  run plus a raw multitrack bundle;
- derive a deterministic gap plan only when a non-empty `voice` track contains
  sufficiently long silent spans;
- rerun the same pinned MuScriptor model on bounded clips with surrounding
  context inside the same compute allocation;
- keep recovered notes as `voice_gap_candidate`, never overwrite
  `voice_raw`, and retain note-level provenance;
- build `voice_auto_enhanced` as a deterministic union of the raw and recovered
  candidates without claiming that the candidates are correct;
- package every original accompaniment track together with the three voice
  representations in one self-contained canonical bundle;
- make normal playback and export include at most one voice representation,
  while keeping raw and gap-only variants available as advanced diagnostics;
- if planning or recovery fails, publish the original raw multitrack bundle
  and complete the user's job instead of discarding a successful full-song
  transcription.

The automatic plan uses conservative fixed bounds for this product slice. They
are engineering controls, not learned or benchmark-optimized thresholds.
Source separation, GAME, training, and cross-track accompaniment copying into
the melody remain outside this task.

## Consequences

A new user uploads once and receives one result without understanding Slurm or
the gap-probe workflow. Songs with eligible gaps take longer because they run
additional same-model inference. The default enhanced voice remains an
experimental candidate, and the application must not describe it as verified
or accurate.

The raw full-song result remains sufficient for recovery and comparison. An
expired local SSH session does not stop the remote job; reconnecting only
restores status polling and result retrieval. Broader automatic-vocal-presence
classification is deferred until unseen-song evidence shows that instrumental
false positives require another model.
