# Experiment protocol

## Unit of evaluation

A song-level project may contain fixed excerpts. Splits are made at song or artist level. Never tune on the blind test excerpts.

## Required run identity

A run ID should include timestamp and a short configuration hash. Every run manifest records:

- parent project ID;
- input audio SHA-256;
- Git commit and dirty status;
- worker name and version;
- model identifier and weight SHA-256;
- exact argv;
- configuration file hash;
- hostname, operating system, Python, device, CUDA/MPS details;
- start/end time and wall time;
- random seeds and deterministic flags;
- exit code;
- output artifact hashes.

## Baseline matrix

At minimum compare:

- direct full-mix model, default decoding;
- direct full-mix model, accuracy-oriented decoding;
- vocal separation model A + GAME;
- vocal separation model A + Basic Pitch;
- vocal separation model A + MuScriptor vocal-constrained decoding;
- separation model B or ensemble + the same vocal workers;
- optional direct instrument-conditioned decodes.

Do not assume the most expensive configuration is best. Measure.

## Reference creation

For each reference note store:

- onset and offset in seconds;
- MIDI pitch;
- instrument/track;
- melody flag;
- annotator confidence;
- ambiguity note;
- source audio hash and excerpt boundaries.

Review difficult passages with slowed playback, isolated stems where appropriate, spectrogram/pitch aids, and external notation/DAW tools. Tools may assist; the final reference is human-confirmed.

## Metrics

### Note transcription

- onset-only precision/recall/F1 at explicit time tolerance;
- onset+offset precision/recall/F1 with explicit offset tolerance;
- pitch-class and absolute-pitch metrics;
- octave error rate;
- frame-level multi-pitch metrics where useful.

### Multi-track assignment

- instrument-aware note F1;
- confusion matrix by taxonomy level;
- macro average across tracks and micro average across notes;
- missing-track and spurious-track rates.

### Main melody

- melody note F1;
- voiced/unvoiced accuracy;
- melody source selection accuracy;
- interruption/handoff errors;
- correction actions and correction time.

### Confidence

- precision at multiple coverage levels;
- reliability diagram / expected calibration error;
- error-detection AUROC or average precision;
- fraction of real errors surfaced in the review queue.

### Product effort

- time to first usable MIDI;
- human correction minutes per minute of audio;
- count of move/resize/split/merge/delete/reassign operations;
- user-rated acceptability with a defined rubric.

## Error taxonomy

Every reviewed error should map to one or more causes:

- source separation deletion;
- source separation leakage/artifact;
- wrong melody source;
- pitch semitone error;
- octave error;
- missing onset;
- duplicate/fragmented onset;
- offset too early/late;
- vibrato/glissando fragmentation;
- wrong instrument;
- beat/downbeat error;
- quantization/notation error;
- structurally ambiguous passage;
- reference uncertainty.

## Fair model comparison

- Use the same canonical input timeline.
- Keep worker-native preprocessing documented.
- Do not tune each system on the blind set.
- Report failures and excluded files.
- Separate decoding/postprocessing gains from model gains.
- Keep raw model output for audit.
