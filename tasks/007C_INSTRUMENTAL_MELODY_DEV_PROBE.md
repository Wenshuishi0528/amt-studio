# Task 007C: Instrumental main-melody development probe

Status: complete — direct-mix instrumental route rejected for v1

## Objective

Test whether the existing Basic Pitch worker, with its published default
decoding and no song-specific cleanup, is viable enough on a full instrumental
mix to justify acquiring a new artist-disjoint blind benchmark.

This is a product/data-strategy experiment after Task 007B. It does not reopen
fusion v2, pass Gate 4, start Task 009B2B, or authorize Task 010.

## Frozen development input

- Dataset: MedleyDB Sample, private non-commercial research evaluation only.
- Track: `Phoenix_ScotchMorris`.
- Artist group: `phoenix`.
- Content: instrumental World/Folk mix with flute and violin melody sources.
- Existing provenance role: `development_instrumental_melody`.
- Mix SHA-256:
  `0abff2045127295b46849d7cb14614ec5d6cc2e7737c47bfd59577c103b3f41c`.
- Melody 1 SHA-256:
  `c1cb36655177b353e81d11778b755d92263e4f6b53070659c4d1e3dd8b34f508`.

Phoenix is development data. Its output and reference may be used to decide
whether a later route is worth testing, but its metrics must never be relabeled
as blind performance.

## Frozen candidate and projection

- One candidate only: Basic Pitch `0.4.0` ONNX on the canonical full mix.
- Use the already pinned package, model hash, CPU provider, and Task 004
  default decoding without threshold tuning.
- Normalize direct-mix notes as instrument `other`; do not pretend Basic Pitch
  assigned an instrument.
- At each MedleyDB contour timestamp, project the highest active `other` note,
  then break ties by latest onset and lexical event ID.
- Score Melody 1 at 50-cent inclusive tolerance.
- Evaluate six non-overlapping 20-second windows selected only from track
  duration: starts at `0`, `30`, `60`, `90`, `120`, and `150` seconds.

The candidate identity is sealed before the Melody 1 file is loaded for
scoring. This extra seal is for reproducibility; it does not turn development
data into blind data.

## Automatic decision

Advance to a new, different-artist instrumental blind benchmark only if all
three development conditions pass:

- raw pitch accuracy is at least `0.70`;
- overall accuracy is at least `0.70`;
- voicing false alarm is at most `0.25`.

Otherwise reject Basic Pitch direct full mix as the v1 automatic instrumental
main-melody route and scope v1 to lead-vocal melody. A failed development probe
must not be rescued by tuning on Phoenix.

## Acceptance criteria

- Basic Pitch accepts the canonical mix only through an explicit
  `direct_canonical_mix` lineage and keeps the existing separator-vocal
  contract unchanged.
- Direct-mix notes retain unknown instrument semantics rather than being
  mislabeled as voice.
- The evaluator supports the declared development provenance role without
  weakening blind-test confirmation rules.
- Canonicalization, model inference, candidate freezing, and scoring run only
  in Slurm compute jobs.
- The report and automatic decision preserve hashes, metrics, thresholds,
  split identity, and the no-retuning stop rule.
- One `make check`, one focused `/review`, documentation/evidence updates, and
  one Git commit complete the task.

## Evidence

- Frozen config:
  `configs/task007c/phoenix_instrumental_development.json`, canonical JSON
  SHA-256
  `7c37d516ade785119522141b32aef759202a80d2cf5484b8b7fecf3e01b5b1a4`.
- Benchmark freeze SHA-256:
  `e64a30cd6acdfe8064bace7a2872fe36e22056e45939ff07722a39db4ceda5b8`.
- Candidate-set payload SHA-256:
  `cc5b7df33ba9bdc36b020b2461a68b1cdb98827527ff8f855c1f0b880ee168a9`.
  The seal records `split=development`, one Basic Pitch candidate, and no
  blind-result eligibility.
- Slurm prepare job `37732190`, Basic Pitch job `37732191`, and evaluation job
  `37732192` all completed `0:0` on compute nodes. The candidate job emitted
  1,701 normalized `other` events from the exact canonical mix with SHA-256
  `1f38bc42cd31134e5592ec7bbc0bed1bdb51e90c3101f442535459af1c56a0bc`.
- Across 20,676 frozen contour frames, raw pitch accuracy was
  `0.693233883857219`, overall accuracy was `0.333865351131747`, and voicing
  false alarm was `0.9648392525019928`. All three automatic conditions failed.
  Polyphonic overlap occupied `0.8533081834010446` of scored frames, with up
  to seven simultaneous active events.
- The automatic decision is
  `reject_direct_mix_instrumental_route_for_v1`. Phoenix remains development
  data, retuning on Phoenix is prohibited, no instrumental blind acquisition
  is justified by this route, and Gate 4 remains false.
- Authoritative report SHA-256:
  `fbe730efde84b8f1cb70c5a81844c1573eca9a8a51cee468d23603525b90a7df`.
  Hardened v2 decision SHA-256:
  `5bb86efc3ee236013b71147d1b54ceea76c3a5e76bd6f1455014dca41805aa13`.
  The v2 assessment re-verifies the benchmark seal, candidate seal, candidate
  events and run manifest, evaluation run manifest, reference hash, 50-cent
  tolerance, and fixed projection before consuming metrics.
- Ignored private evidence, scheduler logs, the canonical mix, seals, events,
  report, and decision are synchronized under
  `projects/private/medleydb-phoenix-scotch-morris/`. Local canonical-event
  validation reports 1,701 valid events.
- The required `make check` passed 230 Python tests and 17 Swift tests, with one
  expected private-integration skip. The single `/review` also invoked the same
  repository check and it passed. Targeted P1 regression coverage, Slurm shell
  syntax, JSON parsing, compilation, and `git diff --check` passed.
- The single `/review` reported two P1 and two P2 findings. Both P1 findings
  were fixed: reference roles are now split-bound, and automatic assessment
  authenticates the frozen evidence and exact scoring policy. Per the bounded
  review instruction, the two P2 hardening suggestions for prepare-pack reuse
  and generic direct-mix/project-manifest binding were documented but not
  expanded into more Task 007C work. No additional model, scoring, or smoke job
  was run.
