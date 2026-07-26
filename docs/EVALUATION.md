# Evaluation protocol

Task 006 freezes references and metric definitions before fusion or learned
refinement. A report is valid only when it identifies both a benchmark freeze
and a human reference seal by SHA-256.

## Split policy

The split unit is artist first and song second:

- every excerpt from one song stays in one split;
- an artist must not appear in more than one of train, development, or
  blind-test for a reported quality claim;
- `train` may contain owner-opted-in corrections after they are sealed;
- `development` may be inspected repeatedly and is the only split allowed for
  fusion rules, thresholds, or model selection;
- `blind_test` must have no prior output inspection or system-selection use,
  is evaluated only after choices are frozen, and is never used to tune them.

The initial private song was already used for Task 003/004 listening and route
selection and is therefore development material. The Task 006 blind split uses
a previously unused song by a different artist; its audio-only excerpts and
split identity were frozen before any model job for that song was submitted.

## External predominant-melody contour

A professionally annotated external F0 contour may replace manual note
annotation for a melody-only research benchmark when all of the following are
true:

- the reference source, download, artifact hash, license, and redistribution
  limits are recorded before scoring;
- audio and annotations remain private when their terms prohibit bundling or
  redistribution;
- the benchmark windows and exact candidate routes are frozen before candidate
  output inspection;
- the external reference is not an arrangement, community MIDI, or
  model-generated annotation;
- results are described as frame-level predominant-melody metrics, not
  note-level transcription or full-score accuracy.

Task 006 uses MedleyDB `Melody 1`, whose documented target is the predominant
melodic line from a single source. The sample audio and annotation are retained
only for private, non-commercial research evaluation under the stricter terms
stated by the official MedleyDB download page. They are never committed,
redistributed, or included in a release.

For note-event candidates, evaluation first applies a fixed,
reference-independent projection. Only events whose normalized instrument is
exactly `voice` are eligible. At each reference timestamp, overlapping events
are reduced by highest pitch, then latest onset, then lexical event ID. Reports
include the overlap-frame fraction so polyphonic clutter remains visible.
This projection is frozen before candidate inference and is not adjusted after
seeing scores.

The dependency-light implementation follows the standard melody quantities
documented by
[`mir_eval.melody`](https://mir-eval.readthedocs.io/stable/api/melody.html):

- voicing recall is the fraction of reference-voiced frames estimated voiced;
- voicing false alarm is the fraction of reference-unvoiced frames estimated
  voiced;
- raw pitch accuracy is the fraction of reference-voiced frames whose estimate
  is voiced and within 50 cents, inclusive;
- raw chroma accuracy uses the same denominator and tolerance after octave
  folding;
- overall accuracy is the fraction of all frames that are either correctly
  unvoiced or reference-voiced with correct pitch.

Undefined denominators are reported as `null`, not zero. The aggregate is
computed by concatenating only frames inside the six frozen, non-overlapping
evaluation windows; per-window results are also preserved. Blind scores may
report the fixed candidates but cannot be used to revise their routes,
projection rule, thresholds, or benchmark windows.

## External dual-annotator note reference

Continuous F0 cannot be converted into a trustworthy note-event reference by
simple semitone quantization. Task 006 therefore supplements the mixed-audio
contour benchmark with
[`vocadito v3`](https://zenodo.org/records/5578807), whose solo-vocal excerpts
have two independent note transcriptions made by trained musicians. The
dataset's [technical report](https://arxiv.org/abs/2110.05580) documents both
the annotation method and the substantial subjectivity of vocal onset, offset,
pitch center, and ornament segmentation.

The blind subset is frozen by singer, track, language, source-audio hash, and
both annotation hashes before candidate inference. Candidate routes and
note-event projection are fixed at the same time. Evaluation then:

- reports onset-only, onset+pitch, onset+pitch+offset, onset+chroma, octave, and
  instrument metrics separately against annotators A1 and A2;
- follows the dataset authors' predeclared `Amax` convention by choosing, for
  each track and candidate, the annotator with the greater
  onset+pitch+offset F1, then macro-averaging the selected track results;
- retains both annotator-specific results so `Amax` cannot hide disagreement;
- reports an automated note-object discrepancy count per minute as a rough
  correction-burden proxy, while explicitly keeping both edit-action counts
  and human correction time unavailable until a timed editing session is
  actually performed.

The automated correction proxy is
`max(reference_note_count, estimate_note_count) - exact_note_matches`.
It describes note-object discrepancy, but it is not a lower bound on editor
actions because one split or merge can change multiple objects. It does not
estimate seconds of human work and cannot be presented as measured manual
correction time.

## Task 007 deterministic-fusion evaluation

Task 007 fixes a new six-singer Vocadito development split and a separate
six-singer blind-test split. Both are disjoint from each other and from the
six Task 006 Vocadito blind singers. Only the development split may determine
worker reliability, the raw-score threshold, or isotonic confidence
calibration.

The four declared routes are GAME and Basic Pitch on the selected vocal stem,
MuScriptor on that vocal stem, and MuScriptor directly on the canonical mix.
Their stable worker/model/input/decoding identities are frozen during
development calibration and must match independently verified blind worker
artifacts. A label cannot be substituted for another route.

Blind evaluation has two distinct seals:

1. `candidate_set_seal.json` binds all four blind worker outputs before their
   quality is inspected.
2. The fusion evaluation seal binds the candidate seal, full fusion outputs,
   rejected/provenance artifacts, development calibration, metric
   configuration, ranking and acceptance rules, and evaluator source hashes
   before any blind reference is loaded or scored.

Main-melody note metrics use the same dual-annotator Amax policy as Task 006.
The strongest single baseline is the maximum baseline for each primary metric;
fusion must be non-regressing against both maxima and strictly improve at least
one to count as a metric improvement. This still does not pass the
correction-time criterion: matched human correction time must be measured
under the same named workflow, otherwise the overall trade-off is reported as
inconclusive or rejected.

Precision-versus-coverage uses only events whose onsets fall inside the frozen
evaluation windows. Full-fusion confidence is calibrated; worker and feature
ablations retain the development-selected raw-score threshold but report no
calibrated confidence because each ablation changes the feature-model
identity. A missing beat map remains an explicit unavailable feature.

The completed v1 blind evaluation rejected the trade-off. GAME scored macro
Amax onset+pitch/onset+pitch+offset F1 `0.7797`/`0.4316`; fusion scored
`0.7410`/`0.4332`. The small offset-aware gain did not satisfy the frozen
non-regression rule, automated discrepancy did not improve, and matched human
correction time remained unavailable. These blind results are evaluation-only
and must not be used to retune v1.

## Freeze and annotation protocol

1. Write an `amt-benchmark-spec/v1` file whose non-overlapping excerpts
   collectively target lead vocal, chorus/harmony, instrumental passage, dense
   accompaniment, vibrato/glissando, and weak notes.
2. Run `scripts/create_reference_pack.py`. It verifies the project and canonical
   audio hash, renders only audio plus context, hashes every excerpt, writes a
   canonical freeze payload, and refuses to overwrite an existing directory.
3. Create the first note reference from `mix.wav`, without candidate piano
   renders. Reference times use canonical-mix seconds. Include notes whose
   onset satisfies
   `evaluation_start_sec <= onset < evaluation_end_sec`; surrounding audio is
   context only. If a note continues beyond the rendered context, clip its
   stored offset exactly at the context boundary, set `offset_censored=true`,
   and add `phrase_boundary`; onset and pitch remain scored but offset is not.
   Sealing rejects censoring away from that boundary.
4. Give every note an annotator confidence in `[0, 1]`. Apply all relevant
   ambiguity tags instead of hiding hard notes. An excluded note requires a
   written reason and remains in the file.
5. A human confirms both the notes and the named coverage categories. Only
   then run `scripts/seal_reference_pack.py --confirm-human-reviewed
   --confirm-coverage`. The seal hashes references and annotation plans.
6. `scripts/evaluate_benchmark.py` rejects missing, mismatched, changed, or
   unsealed references. Its report keeps `measured_results` separate from
   `listening_impressions`.

For a blind split, run `scripts/freeze_evaluation_candidates.py` after worker
artifacts exist but before anyone inspects their output quality. The resulting
`candidate_set_seal.json` binds every candidate label, run ID, worker,
normalized-events hash, and run-manifest hash. Evaluation refuses a blind
result unless the evaluated set matches this seal exactly. A candidate set
cannot be frozen retroactively after listening, tuning, or candidate selection.

For a candidate-corrected blind reference, the annotation seed must itself be
one of the sealed candidates, and primary evaluation uses exactly the sealed
set minus that seed. The subtraction is allowed only when the reference seal's
run ID, worker, normalized-events SHA-256, and run-manifest SHA-256 uniquely
match one sealed record. The report and evaluation run manifest record the
excluded sealed seed. Every other missing, added, substituted, or modified
candidate remains an error.

Both sealing and evaluation re-hash every frozen `mix.wav`; a reference cannot
be sealed or scored if the audio heard during annotation changed after the
freeze.

When a candidate is used as the editing seed, the method is
`candidate_corrected`. Each excerpt then requires a correction session with
the candidate hash, benchmark freeze hash, elapsed review/edit time, and every
add/delete/pitch/onset/offset/split/merge/instrument operation. A from-scratch
reference does not claim candidate correction time.

The seed itself must be a succeeded, hash-verified worker
`normalized/events.jsonl` output with matching project, canonical-mix, run, and
event lineage. Its manifest and the applied human-review manifest are bound
into the immutable reference seal. The seed artifact hash and a run-ID-free
semantic note fingerprint are both excluded from primary scoring. The
fingerprint covers only events inside the frozen evaluation windows and only
the onset, offset, pitch, and instrument fields used for scoring, so changing
serialization, quantized pitch, run IDs, or events outside the scored windows
cannot disguise a self-scoring copy. A note-level correction session requires
at least one logged edit and positive review time;
a no-edit acceptance must use whole-excerpt review with playback count,
additional review time, and an explicit acceptance decision. Logged audio
duration must equal the frozen evaluation duration.

When the owner selects `needs_note_correction`, the review record supplies a
separate corrected-reference JSONL and an `amt-correction-session/v1` file.
The application step first verifies that the untouched provisional seed still
matches its recorded hash, then validates the corrected notes against the
frozen window and context boundary, verifies note-level operations against the
seed and result note IDs, and copies both artifacts into the pack. The review
manifest hashes the external sources and persisted results, so later changes
prevent sealing. Directly editing the provisional file is rejected because it
would erase the before/after audit trail.

An exact zero-duration native model event is not a valid note and is never
silently stretched. The MuScriptor adapter can quarantine only exact
zero-duration pairs into a hashed rejection report; negative-duration events
still fail normalization. A recovery run must hash-verify and preserve the
completed native inference and link the failed source manifest. Recovery
supports both the canonical mix and a lineage-verified separator stem; it
preserves the original input kind instead of substituting the mix.

## Annotation aids after the freeze

A derived candidate created after blind output inspection may be used only to
reduce manual annotation effort. It must be labeled `annotation-only`, retain
the hashes and event IDs of its source run, and remain ineligible for primary
blind metrics. The same restriction applies to community MIDI or sheet-music
arrangements: preserve their source, artifact hash, structure mismatch, and
license or access limitations instead of treating them as truth.

The deterministic top-line helper selects the highest pitch in each
simultaneous onset group, merges only adjacent equal pitches, and clips an
overlap at the next onset. It is a proposal, not a melody detector. Owner
listening comments remain subjective evidence until the notes are corrected
and sealed; wording such as “approximately 90 percent correct” must not be
reported as measured accuracy.

Listening review audio is also evidence-bearing. The renderer hashes the
SoundFont and probes its bank 0 program 0 preset before rendering. It refuses
to create a review package unless the file matches the explicitly approved
GeneralUser GS SHA-256 and program 0 is exactly `Grand Piano`. A piano-like
substring is insufficient: `FM Piano`, `Rhodes Piano`, electric-piano, bell,
and synth presets are not accepted. Changing a failed melody candidate's
timbre does not make the candidate valid. The selected SoundFont's source and
license must remain recorded beside the private review assets.

For the formal blind candidate-corrected path, use
`scripts/create_task006_seed_review.py` rather than the Task 004 multi-candidate
audition command. It requires `benchmark_manifest.json`,
`reference_seed_policy.json`, and the preinspection
`candidate_set_seal.json`; derives all six evaluation windows from the frozen
benchmark; verifies the exact sealed GAME seed and its parent lineage; and
renders only `mix.wav` plus `seed-piano.wav`. This prevents the remaining
primary-metric candidates from becoming undeclared annotation aids.

Primary evaluation accepts only a succeeded worker run's recorded
`normalized/events.jsonl`, with matching project, canonical-mix lineage, run
ID, and artifact hash. The annotation seed and events tagged
`annotation-only` or `not-evaluation-candidate` are rejected. Main-melody
scoring uses exactly one explicitly flagged melody track, with a one-track
voice-only fallback for legacy vocal workers; unrelated drum, bass, and
harmonic events are not pooled into melody metrics.

The evaluator snapshots every benchmark, seal, reference, correction, worker
manifest, and candidate event file used for scoring and revalidates them
immediately before publication. It atomically claims a previously absent
output directory and uses exclusive file creation, so a path created by
another process during evaluation is preserved rather than overwritten.

## Note metrics

The defaults mirror the transparent transcription definitions documented by
[`mir_eval.transcription`](https://mir-eval.readthedocs.io/stable/api/transcription.html):

- onset tolerance: 50 ms, inclusive;
- pitch tolerance: 50 cents, inclusive;
- offset tolerance:
  `max(50 ms, 20% * reference note duration)`, inclusive;
- matching: maximum-cardinality, one reference note to at most one estimate,
  followed by global minimum lexicographic onset/pitch/offset cost for
  pair-dependent octave and instrument diagnostics.

Every candidate reports:

- onset-only precision, recall, and F1;
- onset+pitch precision, recall, and F1;
- onset+pitch+offset precision, recall, and F1;
- onset+chroma precision, recall, and F1;
- octave-error count and rate, whose denominator is onset+chroma matched pairs;
- instrument-assignment accuracy among onset+pitch matches where both
  instrument labels exist.

The primary result includes every human-confirmed note with
`evaluation_status=include`. A secondary diagnostic uses only unambiguous
notes with annotator confidence at least 0.8. Estimates correctly matched to
omitted included references are masked instead of becoming false positives in
that diagnostic. It must not replace the primary result.

## Confidence and coverage

At confidence thresholds 0.25, 0.50, 0.75, and 0.90, the report includes:

- precision, recall, and F1 for retained estimates;
- estimate retention: retained estimates divided by all estimates;
- reference coverage: recall;
- number of estimates missing confidence.

If a worker does not expose calibrated per-event confidence, the report says
`unavailable_no_candidate_confidence`. Missing confidence is never converted
to zero and never presented as calibrated coverage; when every estimate lacks
confidence, no numeric threshold rows are emitted.

## Beat/downbeat events

Plain beat or downbeat event F1 uses a one-to-one 70 ms inclusive window, in
line with the default window documented by
[`mir_eval.beat`](https://mir-eval.readthedocs.io/latest/api/beat.html).
Beat and downbeat are reported separately. Beat count or downbeat count alone
is not an accuracy result.

## Correction effort

Correction reports contain:

- operation count and counts by action;
- corrections per minute of evaluated audio;
- total edit seconds per minute of audio;
- operation-attributed time and unattributed listening/review time.

The timer starts when comparison/review starts and stops only when the
annotator considers the excerpt satisfactory. Replaying audio counts as review
time. Setup time, model inference, and file transfer do not count.

## Required outputs

Every sealed evaluation produces:

```text
evaluation_report.json
metrics_by_track.csv
precision_coverage.csv
error_taxonomy.csv
correction_time.csv
run_manifest.json
```

The JSON report records metric tolerances, candidate and reference hashes,
split identity, and whether the result consumed a blind test. These files are
measured evidence; free-form listening impressions remain a separate field.
The run manifest hashes the report and CSV outputs and records the verified
candidate runs, code state, host, command, and benchmark seals. Supplemental
correction logs must match the benchmark, a frozen excerpt, and an evaluated
candidate; their duration must match that frozen excerpt. Whole-excerpt review
time must account for every declared playback plus additional review time and
must state whether the seed or an empty excerpt was accepted.

## Batch execution telemetry

Task008 batch telemetry measures infrastructure, not transcription accuracy.
The execution failure rate is:

```text
(failed attempts + interrupted attempts)
--------------------------------------------------
(completed + failed + interrupted executed attempts)
```

A cache hit performs no experiment stage and is excluded from that
denominator. Cache-hit rate is reported separately across all attempts. The
resource summary also records aggregate stage wall time, peak child-process
RSS, Slurm allocation fields, host/device evidence, cache bytes, and the
declared retention budget.

Because content caches can be reused across batches, telemetry includes only
attempts whose batch ID, manifest SHA-256, row ID, and cache key match the
current manifest. Attempt JSON and stdout/stderr logs are copied to the
persistent index before an incomplete terminal cache becomes retention-safe.

An intentionally injected interruption remains a failed execution attempt even
when a later retry succeeds. Final row status and attempt failure rate are
therefore separate fields. Neither value is a model-quality result.
