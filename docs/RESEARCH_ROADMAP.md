# Research roadmap

This roadmap is ordered by information value and final product quality.

## Phase A: Baseline laboratory

1. Establish canonical project/run formats.
2. Run MuScriptor large on full mix with several decoding configurations.
3. Run at least two source-separation models or an ensemble.
4. Run GAME, Basic Pitch, and direct MuScriptor on vocal stems.
5. Run Beat This for beats/downbeats.
6. Add drum and bass candidates after the main-melody path is stable.
7. Normalize every output without changing raw results.

Deliverable: reproducible candidate events from independent paths.

## Phase B: Reference and error system

1. Define representative excerpts by musical difficulty, not convenience.
2. Create human-confirmed main melody references.
3. Add drum, bass, and harmonic-track references gradually.
4. Record ambiguity rather than forcing a single answer where the recording does not support it.
5. Build an error taxonomy and correction-time protocol.

Deliverable: a fixed blind benchmark and an annotation audit trail.

## Phase C: Deterministic fusion

1. Align notes by time and pitch tolerance.
2. Cluster duplicates across models.
3. Estimate worker reliability by instrument and input condition.
4. Add beat alignment, range, duration, continuity, and stem-quality features.
5. Preserve competing candidates and calculate confidence.
6. Separate main-melody selection from track transcription.

Deliverable: fusion v1 with ablations and confidence/coverage curves.

Task 007 completed this deliverable, but the sealed blind result rejected v1
as a default route: onset+pitch regressed despite a negligible offset-aware
gain. GAME remains the baseline and Gate 4 is still open.

Task 008 completed the research execution layer around these experiments:
frozen manifest rows, content-addressed stage caching, interruption-safe
replay, explicit priority/checkpoint profiles, persistent raw/derived output
archives, append-only attempts and logs, virtualenv/interpreter/package and
code-entry binding, compute-node manifest hashing, concurrency-safe
shared-root retention, and centralized resource/failure indexes. This removes
batch orchestration as a blocker but does not change the rejected fusion
result.

## Phase D: Learned correction

Start with a note-level or sequence-level reranker/refiner. Candidate features can include:

- model logits/confidence;
- agreement count;
- direct-mix versus stem origin;
- separation leakage features;
- pitch salience and harmonic support;
- beat phase and duration plausibility;
- local melodic interval and register;
- instrument-presence probability;
- repeated-section agreement;
- edit history from human corrections.

Possible outputs:

- keep/delete probability;
- corrected pitch or octave;
- corrected onset/offset;
- instrument reassignment;
- melody probability;
- calibrated uncertainty.

Deliverable: a small model that measurably improves blind quality and correction effort.

## Phase E: Specialized fine-tuning

Fine-tune only where errors remain systematic and data supports the task. Examples:

- lead-vocal note boundary model;
- Japanese/Chinese singing adaptation;
- bass transcription;
- drum class detection;
- instrument-conditioned full-mix decoding;
- source separation for the target repertoire.

Deliverable: targeted checkpoints with per-domain gains and regression tests.

## Phase F: Productization

1. Stabilize the Python backend API.
2. Build SwiftUI project browser, import, job progress, waveform, piano roll, track mixer, and inspector.
3. Add synchronized original/stem/synthesis playback.
4. Implement non-destructive editing and undo history.
5. Export performance and score representations.
6. Convert or bundle selected workers only after accuracy is fixed.
7. Add optional local model packs and hardware-aware selection.

Deliverable: a local Mac application whose editor remains useful even when a transcription needs correction.

## Phase G: Advanced quality paths

- repeated-section consensus;
- score-informed decoding and structural segmentation;
- multiple candidate takes with consensus;
- audio-to-score alignment after user corrections;
- active learning from uncertainty;
- personalized adaptation to genres or instruments;
- model distillation for M4 deployment;
- ensemble separation and oracle stem selection;
- hierarchical instrument taxonomy and program assignment;
- polyphonic voice separation for notation.
