# Task 004: Lead-vocal/main-melody baseline

Status: blocked by Task 003

## Objective

Build independent lead-vocal note candidates so main melody does not depend on one full-mix model.

## Candidate paths

- selected vocal stem + GAME;
- selected vocal stem + Basic Pitch;
- selected vocal stem + MuScriptor constrained to voice;
- direct full-mix vocal candidates from Task 002.

## Requirements

- Each worker has a pinned isolated environment.
- Native outputs and confidence/logits are preserved where available.
- Adapters emit canonical events on the original song timeline.
- No fusion or aggressive cleanup before baseline statistics.
- Produce synchronized piano renders for human inspection.

## Acceptance criteria

- At least three independent candidate event sets when technically possible.
- Event counts, fragmentation, pitch range, phrase gaps, and octave behavior are compared.
- At least three representative excerpts are selected for later reference annotation without tuning to them yet.
- A failure taxonomy draft identifies which paths appear complementary.

## Evidence

Codex: append evidence here.
