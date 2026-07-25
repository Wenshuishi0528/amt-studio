# Task 006: Human reference set and evaluation harness

Status: complete (formal baseline evaluation 2026-07-25)

## Objective

Create a fixed, auditable benchmark before tuning fusion or training.

## Requirements

- Choose excerpts that cover lead vocal, chorus/harmony, instrumental intro/interlude, dense accompaniment, vibrato/glissando, and weak notes.
- Define train/dev/blind-test policy even if training has not started.
- Create human-confirmed main-melody references first.
- Add selected drum, bass, and harmonic-track references gradually.
- Store ambiguity and annotator confidence.
- Implement note metrics, octave errors, instrument assignment, confidence/coverage, and correction effort logging.

## Acceptance criteria

- Blind excerpts are frozen and cryptographically identified.
- Baseline metrics are computed without tuning on blind data.
- Every metric states tolerance and definition.
- A report separates measured results from listening impressions.
- Manual correction protocol is reproducible.

## Evidence

- Completed implementation:
  - added `amt-benchmark-spec/v1`, `amt-reference-note/v1`, and
    `amt-correction-session/v1` schemas and dependency-light validators;
  - benchmark creation verifies the canonical audio lineage, renders
    synchronized audio-only excerpts, hashes the complete freeze payload, and
    refuses overwrite;
  - reference sealing requires explicit human note and coverage confirmation,
    verifies every note lies within its frozen evaluation window, and records
    all reference hashes;
  - evaluation refuses unsealed or modified references and writes
    `evaluation_report.json`, `metrics_by_track.csv`,
    `precision_coverage.csv`, `error_taxonomy.csv`, and
    `correction_time.csv`;
  - note metrics use inclusive 50 ms onset, 50 cent pitch, and
    `max(50 ms, 20% reference duration)` offset tolerances with one-to-one
    maximum-cardinality matching;
  - beat/downbeat-style timed events use a separately stated inclusive 70 ms
    tolerance;
  - confidence-threshold results always include estimate retention, reference
    coverage, and missing-confidence count;
  - candidate-corrected references require per-excerpt correction sessions;
  - correction sessions require either logged note-level edits or declared
    whole-excerpt playback evidence; an empty zero-time session is invalid;
  - annotation seeds must be verified worker outputs with matching project,
    canonical-mix lineage, run ID, artifact hash, and source-event lineage;
  - candidate-corrected seals immutably bind the seed and human-review
    manifests and their per-excerpt hashes, so deleting or changing a reviewed
    artifact cannot enable self-scoring or mislabel edited notes;
  - a semantic note fingerprint excludes renamed or re-normalized copies of
    the annotation seed by hashing only scored windows and onset/offset/pitch/
    instrument semantics; changing quantized pitch or window-external events
    cannot bypass it, and seeded packs cannot be sealed as `from_scratch`;
  - blind evaluation requires an exact candidate set sealed before any output
    quality inspection, and refuses missing, added, substituted, or changed
    candidates;
  - added an annotation-only top-line reducer that retains source lineage,
    refuses overwrite, writes a complete derivation run manifest, and
    explicitly excludes its output from primary metrics.
  - correction duration must match the frozen excerpt and whole-excerpt review
    requires an explicit decision;
  - context-clipped boundary notes are marked `offset_censored`, retaining
    onset/pitch scoring without a false offset penalty; sealing rejects this
    flag unless the stored offset is at the frozen context boundary;
  - maximum-cardinality matches use a global minimum-cost assignment for
    pair-dependent octave and instrument metrics;
  - high-agreement secondary diagnostics mask estimates correctly matched to
    omitted included references, and workers with no event confidence emit no
    numeric confidence-threshold rows;
  - normalization recovery now preserves and verifies separator-stem input
    lineage as well as direct canonical-mix lineage.
- Private development freeze:
  - public alias: `development-song-a`;
  - split: `development`, with `prior_system_exposure=true`;
  - six 12-second evaluation excerpts plus one second of audio context;
  - benchmark freeze SHA-256:
    `ec7e6895b36686212da8cbec5e86bee9007f0d733f5b433cdfe56111a02f6838`;
  - path is private and ignored by Git;
  - owner confirmed the six broad coverage categories;
  - status: candidate-seeded and awaiting note-level listening confirmation;
    no reference or accuracy claim.
- Private blind freeze:
  - public alias: `blind-song-b`;
  - split: `blind_test`, with `prior_system_exposure=false`;
  - six 12-second evaluation excerpts plus one second of audio context;
  - benchmark freeze SHA-256:
    `e235a1faa04990bb53c3d976bfb6bb9241411beae4cc198328eaece747a8e5ee`;
  - freeze preceded every model job for the new song;
  - separator, Beat This, GAME, Basic Pitch, vocal-stem MuScriptor, and
    direct-mix MuScriptor baselines completed on Hyak compute nodes;
  - direct MuScriptor inference produced 8,270 native notes; a recovery run
    hash-verified both raw outputs, explicitly quarantined one exact
    zero-duration note, and preserved 8,269 valid notes without inference
    rerun;
  - the owner broadly confirmed the six coverage categories;
  - listening review found the cleaned `blind-01` proposal approximately 90%
    correct by subjective impression, while `blind-02`, `blind-04`, and
    `blind-06` still contain missing, wrong, over-short, or merged notes and
    `blind-05` remains cluttered;
  - post-feedback annotation-aid job `37627351` ran MuScriptor beam 4 on the
    no-drums/no-bass/no-vocals `other` stem on a Hyak A40 allocation; it
    completed in `00:12:51`, produced 5,476 valid guitar events, and
    quarantined two exact zero-duration events;
  - the derived 59-note `blind-05` top-line proposal removes all drum/bass
    inputs and the rejected proposal's eight pitch jumps larger than one
    octave, but owner review rejected it because the rendered instrument was
    not a recognizable acoustic piano and the original tune was not
    recognizable; the candidate remains excluded from primary blind metrics
    and will not be reused;
  - the listening renderer now probes the actual SoundFont bank 0 program 0
    preset and requires both the approved GeneralUser GS SHA-256 and exact
    `Grand Piano` name; the rejected `FM Bells 1` configuration and names such
    as `FM Piano` or `Rhodes Piano` cannot be presented as verified acoustic
    piano; this fixes the review instrument, not the rejected melody;
  - a six-stem Demucs annotation aid then isolated the guitar-family stem on a
    Hyak A40 allocation; all three predeclared pYIN variants returned zero
    accepted notes;
  - MuScriptor on the same guitar stem completed on Hyak and produced 167
    `blind-05` notes in 77 onset groups; 40 groups were polyphonic and the
    maximum simultaneous count was five, so this still represents lead plus
    accompaniment rather than a credible monophonic target;
  - the six-stem route was rejected without lowering pYIN thresholds, applying
    another highest-note reduction, or creating another owner listening pack;
  - the 90% wording is not a computed metric, no excerpt is an exact reference,
    and the reference pack remains unsealed;
  - because current blind outputs were already inspected before
    `candidate_set_seal.json` existed, they cannot be retroactively reported
    as formal blind metrics.
- Replacement formal blind freeze:
  - public alias: `blind-song-c`;
  - different song and artist from both earlier private projects;
  - six non-silent 12-second evaluation excerpts plus one second of context
    were frozen before any model submission;
  - benchmark freeze SHA-256:
    `f4e1736c833eb0cc427f17d9bb0f99dae7d5211dfe737bd013f9aa78718539f0`;
  - separator route and four fixed main-melody candidates were predeclared
    before inference and without output-quality inspection;
  - Hyak job `37637038` used one checkpoint A40 and completed the full fixed
    worker chain sequentially in `00:25:07` with exit code `0:0`;
  - the same hash-recorded pipeline automatically seals the exact four
    declared candidates after every worker succeeds and before any manual
    synchronization or quality inspection;
  - candidate-set SHA-256:
    `02f37949ffe92824cb6b793181f491562c3cd66622f7e2f9d7f727bd53763296`;
  - all eight runs, the comparison report, seal, and Slurm logs were synced to
    the Mac; every manifest-recorded output and all four sealed event/manifest
    hashes were revalidated;
  - before listening, GAME was fixed as the sole candidate-corrected seed and
    permanently excluded from primary metrics;
  - `scripts/create_task006_seed_review.py` verifies the benchmark freeze,
    seed policy, candidate seal, GAME run and artifact hashes, six frozen
    windows, and exact approved `Grand Piano` SoundFont before atomically
    rendering only `mix.wav` plus `seed-piano.wav`;
  - the six-passage review package is hash-verified and
    `awaiting_human_review`; the three primary-metric candidates have not been
    exposed as annotation aids;
  - owner listening described `blind-02`, `blind-03`, and `blind-04` as
    approximately 95%, 90%, and 80% correct respectively, while explicitly
    identifying residual wrong, cluttered, or missing notes; these percentages
    are subjective impressions, not measured metrics or reference approval;
  - the owner classified `blind-05` and `blind-06` as accompaniment/interlude
    rather than the one-track main melody, making the seed notes possible false
    positives; this target-role interpretation remains provisional because the
    owner explicitly described the feedback as non-expert guidance;
  - the raw owner wording and its conservative error taxonomy are preserved in
    a private, ignored feedback record without changing the provisional
    reference notes;
  - source-independent correction aid job `37650151` ran a fixed pYIN
    configuration on the lineage-verified vocal stem on a Hyak checkpoint CPU
    node; it completed in `00:02:54` with exit code `0:0`, and all 12 declared
    outputs were hash-verified after synchronization;
  - pYIN returned 22, 22, and 17 proposal notes for `blind-02` through
    `blind-04`; a narrow three-passage `Grand Piano` review pack was generated,
    while pYIN detections for `blind-05` and `blind-06` were deliberately not
    used to override the owner's accompaniment classification;
  - final owner review preferred the frozen GAME seed on every reviewed
    passage and rejected pYIN as discontinuous and unusable; the reported
    `85%`, `0%`, and similar values remain subjective listening estimates,
    never measured accuracy;
  - the pYIN route is annotation-only, cannot be scored or selected as a blind
    candidate, did not read or expose the three primary-metric candidates, and
    is now closed rather than tuned or rerun.
- Professionally annotated formal benchmark:
  - the MedleyDB sample was downloaded directly from its official Zenodo
    record on Hyak, its published archive MD5 was verified, and archive members
    were safety-checked before private extraction;
  - official-site terms are treated as the controlling, stricter license
    boundary: private non-commercial research evaluation only, with no Git
    commit, redistribution, release bundle, or commercial training use;
  - public alias `medleydb-sample-vocal-a` provides a professionally checked
    `Melody 1` predominant-melody F0 contour with 49,080 frames; the exact
    track identity, mix, and contour are bound by SHA-256 in private
    provenance;
  - six time-distributed 12-second windows were frozen before candidate
    inference, with reference-voiced densities ranging from approximately 34%
    to 77% so false alarms and melody misses are both represented;
  - GAME on the selected vocal stem, Basic Pitch on the same stem, MuScriptor
    on that stem, and direct-mix MuScriptor were declared before inference;
    pYIN is excluded by the already-recorded owner decision;
  - standard voicing recall, voicing false alarm, raw pitch accuracy, raw
    chroma accuracy, and overall accuracy are implemented at an inclusive
    50-cent tolerance, with per-excerpt and aggregate evidence;
  - A40 candidate job `37690768` completed with exit code `0:0` in
    `00:18:32` and sealed the four-candidate set before scoring;
  - benchmark freeze SHA-256:
    `854e3ac3cdf9a0a70867d9e51780e38635d50a07de8acf781a6132e546fb2a16`;
  - candidate-set SHA-256:
    `f34359571dd3396197182c39f4c1c63dac6ae870ddbf49ec79bc6e384e4517c6`;
  - after review hardening, final CPU evaluation job `37692231` completed
    with exit code `0:0` in `00:00:02`;
  - the authoritative `v3` report SHA-256 is
    `e4407cce7728e0990d0b3070edb43464ba60228296fb80aeb210ef0bc287ea68`;
  - at the fixed inclusive 50-cent tolerance, GAME ranked first with
    overall accuracy `0.7271`, raw pitch accuracy `0.6822`, voicing recall
    `0.9278`, and voicing false alarm `0.2086`; Basic Pitch ranked second
    with `0.5564`, `0.4368`, `0.8860`, and `0.2723` respectively;
  - MuScriptor's higher voicing recall came with substantially greater false
    alarm and polyphonic-overlap evidence, so no single undefined “accuracy”
    replaces the separate metrics.
- Dual-annotator external note benchmark:
  - Vocadito v3 was downloaded from its official Zenodo record under CC BY
    4.0; the published MD5 and a locally recorded SHA-256 were verified;
  - all 414 ZIP members were checked before CPU-node extraction, with no
    absolute path, traversal component, or symbolic-link member;
  - six excerpts from six distinct singers were fixed before inference,
    spanning Tagalog, English, French, Mandarin, and Hawaiian+English plus
    average MIDI pitch from 47 to 62;
  - every source audio file and both trained-musician note annotations are
    hash- and count-bound in the private freeze;
  - annotators A1 and A2 are reported separately; the predeclared
    per-track `Amax` summary follows the dataset authors' convention and may
    not replace the annotator-specific evidence;
  - the same four candidate routes were frozen without output inspection;
    Hyak A40 job `37691274` completed with exit code `0:0` in `00:11:00`;
  - benchmark freeze SHA-256:
    `1a50acb82e59c5a60a8904a86db1c0de3f84121aa871a6a4b5775ac1c246145c`;
  - candidate-set SHA-256:
    `4de9e1495687a255bf3d8f5244cb31235b781db70d1fc852ffb297fa764a21e7`;
  - final CPU evaluation job `37692232` completed with exit code `0:0` in
    `00:00:14`; every manifest-recorded report output and final source file was
    re-hashed after synchronization;
  - the authoritative `v3` report SHA-256 is
    `f38c2c0d31086418b40ef10e2a9c437c7c76d2771794176b5e9559e64e7a0d60`;
  - GAME ranked first with macro per-track Amax onset+pitch F1 `0.7447` and
    onset+pitch+offset F1 `0.4758`; its aggregate onset+pitch F1 was `0.5966`
    against A1 and `0.7379` against A2, making annotator disagreement explicit;
  - Basic Pitch's corresponding macro Amax F1 values were `0.5233` and
    `0.2984`; the two MuScriptor routes were lower on both note metrics;
  - the evaluation reports an automated note-object discrepancy proxy per
    minute, but explicitly does not claim an edit-action lower bound or
    measured human correction time.
- Known limitations:
  - MedleyDB measures predominant-melody F0 on mixed audio, while Vocadito
    measures note events on isolated solo vocals; neither is a full-arrangement
    score benchmark or a formal metric for the owner's private songs;
  - per-track Amax is deliberately optimistic and is never substituted for the
    separate A1/A2 results;
  - candidate confidence is unavailable for these fixed outputs, so calibrated
    precision/coverage curves remain unavailable;
  - the note-object discrepancy rate is an automated burden proxy, not a timed
    human edit count; Gate 2's human correction-time evidence remains open
    even though the Task 006 benchmark/evaluator acceptance criteria pass;
  - failed jobs `37691794`, `37691795`, `37692005`, and `37692007` exposed a
    missing remote evaluator dependency before output creation; `37692033`
    exposed a 63-character provenance typo. The dependency and provenance
    record were corrected, hashes reverified, and only the successful `v2`
    reports above are authoritative.
- Validation:
  - focused `/review` was run; its final nine P1/P2 findings were fixed with
    regression coverage, including note-level seed correction, portable
    Hyak/Mac candidate resolution, same-track external-reference binding,
    complete contour run provenance, finite event validation, and honest
    correction-proxy wording;
  - candidate-corrected blind evaluation now permits exactly the sealed set
    minus a uniquely run/worker/events/manifest-hash-bound seed and records the
    exclusion in both evaluation evidence files;
  - final review requires that seed to match exactly one sealed record,
    revalidates every scored input snapshot immediately before publication,
    and refuses output paths that appear during evaluation without overwriting
    them;
  - the standard melody implementation was cross-checked against
    `mir_eval==0.8.2` on 100 randomized cases with agreement within `1e-12`;
  - final `make check` passes 155 tests;
  - `uv run python -m compileall -q scripts workers`, `jq empty
    schema/*.json`, repository/external-cwd candidate-freeze CLI startup, and
    `git diff --check` pass.
