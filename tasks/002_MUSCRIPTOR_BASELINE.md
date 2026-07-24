# Task 002: Direct full-mix MuScriptor baseline

Status: complete (Hyak verification 2026-07-23)

## User-directed execution scope

On 2026-07-23 the user designated the Mac as the front end and lightweight
processing machine. All MuScriptor large inference, including short
repeatability probes, must run through Slurm on a Hyak CUDA GPU. Record the
GPU model actually allocated instead of assuming a specific accelerator. The
earlier Mac/MPS comparison requirement is superseded; observed Mac
compatibility failures are reported as failures, not converted into successful
baselines.

## Objective

Run a pinned MuScriptor large baseline on the full canonical mix on Hyak.
Preserve native JSONL, MIDI, logs, environment, weight hashes, runtime, and
normalized events. Keep the Mac on lightweight orchestration and validation.

## Required comparisons

- Hyak CUDA GPU, large, beam size 4 with prelude forcing.
- Hyak CUDA GPU, fixed excerpt, repeated twice with identical decoding.
- Optional instrument-constrained decodes only after the unconstrained result is saved.

## Implementation requirements

- Create the isolated inference worker environment on Hyak.
- Keep Mac work to orchestration, validation, and non-model result rendering.
- Pin package version or Git commit.
- Locate and hash downloaded model weights.
- Capture `muscriptor --help`, `list-instruments`, and device diagnostics.
- Generate native JSONL and MIDI in separate immutable run directories.
- Write a native-to-canonical adapter with fixture tests.
- Preserve model instrument names before product taxonomy mapping.
- Record wall time and peak memory if available.

## Acceptance criteria

- At least one successful Hyak full-song run.
- The full-song and repeatability runs have complete manifests and output hashes.
- Canonical events validate with `amt validate-events`.
- Event counts, instrument counts, pitch ranges, and durations are summarized.
- Auralized or external MIDI playback is inspected and notes are recorded without claiming ground-truth accuracy.
- Repeatability or nondeterminism is measured on one short excerpt.

## Evidence

### Execution boundary and pinned artifacts

From the point when the user set the execution boundary, MuScriptor large
inference ran only inside Slurm GPU allocations on Hyak. The Mac performed
SSH/Slurm orchestration, file transfer, event validation, hashing, and
FluidSynth result rendering. Earlier unsuccessful Mac/MPS compatibility probes
were not accepted as baselines, and no model inference ran on a Hyak login
node.

Pinned worker and model:

- `muscriptor==0.2.2`;
- `torch==2.2.2` (`2.2.2+cu121` in the Hyak worker);
- upstream Git commit
  `3feb2497bcd5316f9a9934b93d9f5dd3ff15e85a`;
- model revision
  `MuScriptor/muscriptor-large@8809fdfbed2affa7ade94a7059e746e3880720e7`;
- model SHA-256
  `ac4eb6ea87dfc26b6ca6b954c6b967ab87ad4c7d08e078b25214f13ed051f397`;
- config SHA-256
  `16bedd02b18770e43740419b0d5777f231047e96e8987f498e8a1123c39c9852`;
- model size: 5,465,642,136 bytes.

The gated model terms were accepted by the user in their browser. No Hugging
Face token was copied to Hyak, written to the repository, or placed in a job
log. The already authorized pinned files were transferred and registered with
an ignored provenance file.

### Hyak environment and Slurm jobs

Persistent project root:

```text
/mmfs1/gscratch/stf/liuhaobo/amt-studio
```

The locked root environment uses Python `3.12.13`. The isolated worker recorded
Linux x86_64, MuScriptor `0.2.2`, Torch `2.2.2+cu121`, CUDA `12.1`, and one
available CUDA device. Slurm startup logs captured `hostname`, `nvidia-smi`,
Python/Torch/CUDA versions, Git state, and the exact worker source hashes.

Observed jobs:

- `37603992`: A100 repeatability job, `COMPLETED`, exit `0:0`, elapsed
  `00:05:04`;
- `37604140`: A40 beam-4 probe, `COMPLETED`, exit `0:0`, elapsed `00:04:12`;
- `37604080`: A100 80 GB full-song job on `g3087`, `COMPLETED`, exit `0:0`,
  elapsed `00:24:40`.

The full job used two CPUs, 64 GB host memory, and one A100. Its two
subprocesses reported:

- JSONL wall time `725.631078` seconds;
- MIDI wall time `674.678523` seconds;
- peak child RSS `6,057,996,288` bytes;
- beam size 4, prelude forcing enabled, sampling disabled.

The manifest records base commit
`570c29f58f327c8f63795a1b3cbfd73b40f343a0` plus `dirty=true`, because Task
002 is committed only after its evidence is complete. Each of the five
execution-source SHA-256 values in the manifest was independently compared
with the final local source and matched exactly.

### Repeatability and beam-4 probe

The fixed 20-second FLAC excerpt SHA-256 was
`465ef3766468e95724d8eb9aa37df7d61b9fa81542f6c20ef14bb7b7d55dc76a`.
Two beam-1 runs executed sequentially in job `37603992`:

```text
muscriptor-large-repeat-a-hyak-20260724T032734Z
muscriptor-large-repeat-b-hyak-20260724T032734Z
```

Both produced 312 normalized events with the same counts
(`acoustic_piano=45`, `clean_electric_guitar=33`, `drums=99`,
`electric_bass=135`), pitch range 29–72, and timeline 0.45–19.92 seconds.
Their native outputs were byte-identical:

- JSONL SHA-256
  `2021154263cac250674afdee98274223b78d850563db4fa49f10f20dcdb3636d`;
- MIDI SHA-256
  `e5d9141e24e350767a5ea287e4ce0a9a4cf652e9af8d3187b93636ffef25e39f`.

The normalized files include their immutable run IDs and therefore have
different artifact hashes. After removing only `event_id` and
`source_run_id`, both canonical streams had the same compact-JSON SHA-256:
`cd6ea722b2c8a5e176b66fd04f627c846280505c847e8153b4a10d2fcae029a8`.
This is exact repeatability for this excerpt and configuration, not a general
accuracy claim. Run A included CUDA/model warm-up (JSONL `94.409660` seconds,
MIDI `29.330476` seconds); run B took `26.127138` and `24.501559` seconds.

The A40 beam-4 probe
`muscriptor-large-beam4-probe-hyak-20260724T034000Z` also succeeded. It
produced 206 valid events, with JSONL/MIDI wall times `94.142779` and
`42.731894` seconds. Its different event distribution from beam 1 is recorded
as an observed decoding difference, not judged as better without a reference.

### Full-song result

Run ID:

```text
muscriptor-large-beam4-hyak-37604080
```

Input was the deterministic 44.1 kHz canonical FLAC from Task 001, duration
`265.614127` seconds. The final manifest status is `succeeded`; its error field
is null. `uv run amt validate-events` returned:

```json
{"valid": true, "event_count": 7667}
```

Descriptive output only:

- timeline: `1.20`–`262.33` seconds;
- pitch range: MIDI `28`–`89`;
- `acoustic_guitar`: 1,423;
- `acoustic_piano`: 1,154;
- `clean_electric_guitar`: 2,175;
- `drums`: 1,554;
- `electric_bass`: 808;
- `electric_piano`: 44;
- `flutes`: 14;
- `soprano_and_alto_sax`: 2;
- `voice`: 493.

Native instrument names remain unmapped. MuScriptor 0.2.2 exposes neither
event confidence nor preserved velocity, so those fields remain explicitly
unavailable.

Selected artifact hashes:

- native JSONL:
  `16393f820fbc4f4b39bdca123aaed545ad8929465cf26d6c64af21833e3f1b2b`;
- native MIDI:
  `d8f1d4c0c1c83f27feb6b01f5a632bf5d3a647ab9971e26e13acc48cb627e04c`;
- normalized events:
  `057ed404e0427365b00334a0ca26dcc319cc297ea6de30fb7e9f0e3db4f44135`;
- normalized summary:
  `61c51451f1c6bf0259d06c16456a253b669b1cc124842397b62717266cfbc00e`;
- Slurm stdout:
  `fd7b9b8e90018905f9ec4abac737da5d68fc75c426462d8c344a70f4c44c0543`;
- Slurm stderr was empty, SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

All run directories, model files, private audio, MIDI, JSONL, and renders
remain under ignored private/weight paths and are not Git artifacts.

### Auralization inspection

On the Mac, without loading the model, MuScriptor's result-only auralizer used
FluidSynth `2.5.6` and MuseScore General SoundFont SHA-256
`ee51d2c4b1525e70f19a45909c4fd7a2e26d91d115fa89dbf5a6bc413d8b9bf3`.
It produced a stereo PCM WAV with original audio on the left and MIDI
synthesis on the right:

- duration `265.614127` seconds at 44.1 kHz;
- SHA-256
  `2843d8fdb1172c3635f5955896741330abf9a3cdd88937fc6cc6ea4ffb1a8210`;
- left/right RMS `0.1014611` / `0.1014608`;
- right channel non-silent fraction `98.20%`;
- right-channel activity `1.202`–`262.741` seconds, structurally consistent
  with the event timeline.

The render is playable and the synthesis channel is non-empty and
time-aligned at the structural level. This inspection does not establish note,
instrument, or melody accuracy; Task 006 human reference annotation is still
required for those claims.

### Final checks and review

Commands:

```bash
make check
uvx ruff check workers/muscriptor/*.py tests/test_muscriptor_*.py
uv lock --check
uv lock --check --project workers/muscriptor
bash -n scripts/hyak/setup_muscriptor.sh slurm/10_muscriptor_baseline.slurm
git diff --check
```

Observed before the final commit:

- doctor passed all required tools and FluidSynth `2.5.6`;
- all 9 unit tests passed;
- source and tests compiled;
- Ruff checks passed on the Task 002 Python files;
- both lock files were current;
- both shell scripts parsed successfully;
- diff whitespace checks passed.

The lightweight review found no blocking issues: private audio/weights/results
remain ignored, no token or password is present in tracked files, model compute
is not performed on the Mac or login node, raw native output is preserved,
versions and hashes are pinned, failures remain explicit, and no later task
was silently implemented.
