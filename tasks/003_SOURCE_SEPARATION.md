# Task 003: Source-separation candidate benchmark

Status: complete

## Objective

Produce authorized vocal, drum, bass, and residual stem candidates while measuring their effect on downstream transcription.

## Requirements

- Isolate the separator environment.
- List available models and select at least two justified candidates: a vocal-quality model and a multi-stem model.
- Pin package/model versions and hashes.
- Preserve each stem set separately. Never overwrite one model with another.
- Create objective checks: sum/reconstruction error where applicable, clipping, duration drift, loudness, and silence.
- Create subjective listening notes on representative passages.
- Run at least one downstream AMT worker on the vocal stems to test whether separation helps or hurts.

## Acceptance criteria

- Two reproducible stem sets with manifests.
- No timeline drift relative to canonical audio beyond documented tolerance.
- Downstream candidate note statistics are compared.
- Separation deletion/leakage examples are time-stamped.
- A default and fallback separator preset are selected based on evidence.

## Evidence

### Execution boundary and private storage

The user directed that the Mac remain the front end and lightweight result
processor. Separator environment installation, model download, source
separation, objective full-song analysis, and downstream MuScriptor inference
ran only inside Hyak Slurm GPU allocations. The Mac submitted and monitored
jobs, verified and synced manifests, decoded existing result files for
repeatability checks, and rendered short listening clips. No model inference
ran on the Mac or a Hyak login node.

Private audio, weights, run directories, reports, and listening clips remain
under ignored project/weight paths. They are evidence inputs and outputs, not
Git artifacts.

### Pinned worker, models, and rights boundary

The isolated Linux worker is locked to:

- `audio-separator==0.44.5`;
- upstream commit
  `4fe3540c249ff130bd5395c0e9377b3d16970c1a`;
- package wheel SHA-256
  `9db7d8ded987a74aec9d96be949b49c9068def69823abb59cabb6e6f88679ae7`;
- package sdist SHA-256
  `58866bc61d0c692fff8a52cda67c284f7847a844048987135677a007bf0ae794`;
- separator pins SHA-256
  `d332b5425af0c7c1599d368fb5bfb4677e91409c85ab002dfcfdd9c02b4cd389`;
- Python `3.12.13`, Torch `2.7.1+cu126`, CUDA `12.6`, NumPy `2.2.6`,
  Numba `0.61.2`, ONNX Runtime `1.27.0`, and FFmpeg `8.1`.

The selected candidates are:

- `vocal_quality_a`: BS-Roformer
  `model_bs_roformer_ep_317_sdr_12.9755.ckpt`, checkpoint SHA-256
  `5b84f37e8d444c8cb30c79d77f613a41c05868ff9c9ac6c7049c00aefae115aa`,
  model bundle SHA-256
  `dea73ef247f5054d218d685ca9a6bb6300988a90a3618c4def79e052ee860471`;
- `multistem_quality_a`: `htdemucs_ft.yaml`, with four pinned `.th` files,
  model bundle SHA-256
  `11d5a120ab49a6425cd577af549068009a1aca80a538b00b2150f19fb84b918e`.

Every expected model/config file has a recorded size and SHA-256 in
`workers/separator/pins.json` and the ignored installation provenance. The
wrapper code is MIT-licensed at the pinned revision. That does not establish
the training-data or commercial-distribution rights of every downloaded
weight, so the weights and generated stems remain private research artifacts
pending an independent rights review.

### Environment setup and retained failures

The setup history is retained rather than rewritten as a first-try success:

- jobs `37609903` and `37609958` exposed incompatible native dependency and
  Python-header resolution;
- job `37610002` rejected a GPU ONNX Runtime configuration whose provider ABI
  did not match the node runtime;
- job `37610355` completed the final isolated setup on an A40 in `00:03:03`;
- jobs `37610583`, `37610584`, and `37610585` preserved failures caused by
  FFmpeg not being available in the compute-node path;
- job `37610720` exposed an Lmod initialization issue under `set -u`;
- queued jobs `37610751`, `37610794`, and `37610827` were cancelled before
  allocation while checking scheduling alternatives; they performed no model
  compute and produced no run artifact.

The final jobs load the pinned `weirdlab/ffmpeg/8.1` module. The evaluated
BS-Roformer and Demucs models run through PyTorch CUDA; CPU ONNX Runtime only
satisfies the wrapper's unconditional import and is not the inference engine
for these two candidates.

### Fixed-excerpt repeatability

The fixed 20-second input SHA-256 is
`465ef3766468e95724d8eb9aa37df7d61b9fa81542f6c20ef14bb7b7d55dc76a`.
Jobs `37610839` (`g3052`) and `37610998` (`g3057`) ran the same two
configurations on separate A40 allocations.

For BS-Roformer, both instrumental and vocal FLAC container bytes, decoded PCM,
and key metadata were identical between repeat A and repeat B. For Demucs, the
bass, drums, other, and vocal artifacts were identical under the same three
comparisons. The result is exact repeatability for this fixed input,
configuration, runtime family, and observed A40 allocations; it is not a
general determinism or accuracy guarantee for every input or accelerator.

### Request-bound final full-song runs

An initial full-song job `37610997` succeeded on `g3047`. A targeted review
then found that checkpoint reuse verified output hashes but did not bind reuse
to the current input, pins, weight provenance, decoding settings, and source
files. The verifier and Slurm jobs were hardened. The old immutable runs were
preserved, and final job `37611557` correctly rejected them as stale before
allocating `-attempt-1` run IDs.

Final job `37611557` completed on A40 node `g3045`, exit `0:0`, elapsed
`00:08:11`:

```text
separator-task003-full-d332b542-vocal-quality-a-attempt-1
separator-task003-full-d332b542-multistem-quality-a-attempt-1
```

Both manifests passed output size/hash checks and the current-request binding
for the canonical input, pins, model provenance, configuration, and all seven
recorded execution sources.

Observed objective diagnostics:

- BS-Roformer separation wall time `134.930148` seconds, reconstruction
  relative L2 `0.0206440918`, reconstruction SNR `33.7040844 dB`, global
  reconstruction correlation `0.9999963`;
- Demucs separation wall time `62.417695` seconds, reconstruction relative L2
  `0.0938805331`, reconstruction SNR `20.5484891 dB`, global reconstruction
  correlation `0.9982676`;
- every stem has `11,713,583` decoded frames at 44.1 kHz and duration
  `265.614126984127` seconds;
- every stem has zero decoded-frame endpoint drift, and both summed-stem
  alignment diagnostics report `0.0` second lag;
- vocals, bass, and other have threshold clipping fraction `0`; the
  BS-Roformer instrumental and Demucs drums each contain one threshold-crossing
  scalar sample (`4.268548743795984e-8`), so no material clipping was observed.

Selected final stem SHA-256 values:

- BS-Roformer vocals
  `e8500bdf08f761a117d167f1cd3852309440661b93ebadde8064f3f90189538a`;
- BS-Roformer instrumental
  `da94012fddb6412fd830f3c9556f043ea73577d66ed48469f5426422cb0962a0`;
- Demucs vocals
  `614b2d1c53ce7f70b1af0393b19c7f43a2b688bceb3db3cbcbe2a139e72a692b`;
- Demucs drums
  `ec835ec87b8d5c7f0933cef2cae91199f3c5717e02fa11e6dd80032b712aca2d`;
- Demucs bass
  `a2c2122fafff81fa7ce9cef5d619459dae6f5a66e7d8c99b8049b68dd17241c9`;
- Demucs other
  `4327401b5e902e808d3f55d8ee744765d2a344a0df2737bfb813715b729aca50`.

All six final stem files are byte-identical to the corresponding initial
full-song artifacts. This demonstrates that the validation-only hardening did
not change the observed model outputs. Reconstruction and correlation values
remain diagnostics without isolated ground-truth stems; they are not
separation-quality or transcription-accuracy rankings.

### Request-bound downstream MuScriptor comparison

The first completed downstream comparison was retained, then regenerated after
the same request-binding review described above. Final job `37611749` completed
on A40 node `g3062`, exit `0:0`, elapsed `00:10:13`. It used the pinned
MuScriptor large worker with beam size `4`, the `voice` instrument constraint,
prelude forcing enabled, deterministic decoding, CUDA, and JSONL-only output
for all three paths:

```text
muscriptor-task003-voice-compare-d332b542-direct-attempt-1
muscriptor-task003-voice-compare-d332b542-vocal-a-attempt-1
muscriptor-task003-voice-compare-d332b542-vocal-b-attempt-1
```

The request-bound verifier checks each current audio path and SHA-256, current
MuScriptor pins and weight provenance, decoding fields, source hashes, required
outputs, and all output sizes and hashes before a run may be reused. The
comparison report independently reconstructs its complete contents from the
three current manifests and normalized event files before it may be reused.

Observed descriptive event summaries were:

- direct canonical mix: `756` voice events, MIDI pitches `44` through `81`,
  timeline `1.16` through `261.85` seconds, inference wall time
  `212.071299` seconds;
- BS-Roformer vocal path: `590` voice events, MIDI pitches `50` through `74`,
  timeline `14.11` through `252.33` seconds, inference wall time
  `121.185595` seconds;
- Demucs vocal path: `560` voice events, MIDI pitches `55` through `75`,
  timeline `14.10` through `253.37` seconds, inference wall time
  `126.787377` seconds.

Using deterministic one-to-one same-pitch and same-instrument pairing with a
`0.05`-second onset tolerance:

- direct versus BS-Roformer had `188` onset partners (`24.8677%` of direct
  events and `31.8644%` of BS-Roformer events), of which `124` also matched
  within the `0.1`-second offset tolerance;
- direct versus Demucs had `222` onset partners (`29.3651%` of direct events
  and `39.6429%` of Demucs events), of which `159` also matched the offset
  tolerance;
- BS-Roformer versus Demucs had `274` onset partners (`46.4407%` and
  `48.9286%`, respectively), of which `216` also matched the offset tolerance.

All three paths share the verified canonical-mix lineage, and both stem parent
hashes and zero-drift timeline records were verified. The report explicitly
claims neither accuracy nor a separator ranking: agreement can represent
shared errors, and disagreement does not identify which path is correct.
Precision, recall, F1, and a defensible "helps or hurts" conclusion require the
Task 006 human reference.

The ignored report is:

```text
projects/private/glass-kiss/reports/
  muscriptor-task003-voice-compare-d332b542-attempt-1.json
```

Its final run-manifest SHA-256 values are:

- direct:
  `066ade02464ef28a9472d3787eb587f573ca30b2f9a5e54aced2b53bd2198e9f`;
- BS-Roformer vocal:
  `27e32e66337697016c0ba48858cb4b3c4fd6991e8900b1d9fd7469a5361f5ead`;
- Demucs vocal:
  `ad7125b19321c3d881e5a2ea1d306d8949e84245b4c724f6a776ccd1b25b7dfa`.

Job `37612144` then completed on A40 node `g3054`, exit `0:0`, elapsed
`00:00:08`. It rejected each stale base run and stale base report for a
specific request mismatch, verified and reused all three `-attempt-1` runs and
the complete `-attempt-1` report, and exited without model inference. This is
the final checkpoint/idempotency proof.

### Review hardening

The targeted code review found and the implementation now covers:

- run reuse bound to current inputs, pins, model provenance, configuration, and
  execution-source hashes rather than only output hashes and run IDs;
- comparison-report reuse bound to a freshly reconstructed complete report,
  with only the generated timestamp value intentionally ignored;
- listening candidate labels restricted to safe, unique filename components,
  including Unicode-normalized collision detection and a reserved `mix` name;
- separator setup paths canonicalized and constrained to approved repository
  locations before any environment clear or installation.

Regression tests exercise stale inputs and sources, tampered report sections,
unsafe and colliding labels, and aliased or out-of-bound environment paths.

### Final human listening gate

The Mac rendered only short clips from existing artifacts; it did not perform
model inference. The final listening manifest SHA-256 is
`84d50590fa592d7c75c5b62d0d1c67c85d273cc3f10e07e9e21559f78122e81a`
and is bound to the two final `-attempt-1` separator manifests:

```text
projects/private/glass-kiss/reviews/
  separator-task003-d332b542-final/review_manifest.json
```

It contains three 12-second, 44.1 kHz stereo passages:

- `4` to `16` seconds: intro and vocal-entry boundary;
- `132` to `144` seconds: lower-vocal/transition candidate;
- `180` to `192` seconds: vocal-dominant candidate.

Each passage includes the original mix, candidate A (`vocal_quality_a`,
BS-Roformer), and candidate B (`multistem_quality_a`, Demucs). All nine clips
were decoded and structurally verified.

The project owner reviewed all three passages and selected A each time:

- `4` to `16` seconds: A preferred; A's vocals were described as clear, while
  B had obvious accompaniment leakage and audible echo;
- `132` to `144` seconds: A preferred with the same clear-vocal versus
  leakage/echo finding;
- `180` to `192` seconds: A preferred with the same clear-vocal versus
  leakage/echo finding.

No obvious vocal deletion was reported for A in these passages. This is a
bounded listening observation, not proof that no deletion exists elsewhere in
the song and not a transcription-accuracy result.

### Final operational selection

The selected presets are:

- default: `vocal_quality_a` (BS-Roformer);
- fallback: `multistem_quality_a` (Demucs).

The human preference overrides the earlier objective-only proposal: A was
preferred on every reviewed passage, its vocals were reported as clear, and B
had audible accompaniment leakage and echo. BS-Roformer also had the stronger
reconstruction diagnostics on this song.

Demucs remains the fallback because it provides the separate drums, bass, and
residual stems required by later multistem work. Its lower observed runtime
and descriptive downstream agreement are retained as diagnostics, not as
reasons to override the listening result. Task 003 therefore satisfies its
listening, downstream-comparison, timestamped-example, and default/fallback
acceptance gates without making an unsupported accuracy claim.
