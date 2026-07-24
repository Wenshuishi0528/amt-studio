# MuScriptor worker

Initial direct full-mix multi-instrument baseline. This worker is isolated from
the root `amt_core` environment.

## Verified pins

- PyPI package: `muscriptor==0.2.2`
- upstream tag commit: `3feb2497bcd5316f9a9934b93d9f5dd3ff15e85a`
- large model repository: `MuScriptor/muscriptor-large`
- large model revision: `8809fdfbed2affa7ade94a7059e746e3880720e7`
- code license: MIT
- released weights: CC BY-NC 4.0 plus the conditions shown on the gated model page

Machine-readable values are in `pins.json`; the full dependency graph and
artifact hashes are locked in `uv.lock`.

## Install the isolated environment

From the repository root:

```bash
uv sync --project workers/muscriptor --locked
```

This creates `workers/muscriptor/.venv`. Do not install MuScriptor into the root
environment.

## Authenticate and fetch the pinned model

The model owner requires the user to accept the gated model terms and
authenticate with Hugging Face. Keep the token outside Git:

```bash
uvx hf auth login
workers/muscriptor/.venv/bin/python \
  workers/muscriptor/fetch_weights.py \
  --output weights/muscriptor/large-provenance.json
```

The ignored provenance JSON records the exact resolved weight/config paths,
sizes, and hashes. The runner re-hashes the weight before every immutable run.

To register already transferred files on Hyak without copying a token:

```bash
workers/muscriptor/.venv/bin/python \
  workers/muscriptor/fetch_weights.py \
  --local-weight /persistent/path/model.safetensors \
  --local-config /persistent/path/config.json \
  --output /persistent/path/large-provenance.json
```

## Run one immutable baseline

The project execution boundary keeps MuScriptor large inference off the Mac.
Submit `slurm/10_muscriptor_baseline.slurm` on Hyak; it invokes
`run_baseline.py` with CUDA inside the allocated GPU job. The runner refuses
an existing run directory. Each successful run preserves:

- `raw/events.native.jsonl`
- `raw/full.native.mid`
- `normalized/events.jsonl`
- `normalized/summary.json`
- CLI help, instrument names, device diagnostics, stdout/stderr
- `request.json` and a complete `run_manifest.json` with hashes

The adapter keeps upstream instrument names unchanged in both `instrument` and
`extra.native_instrument`; product taxonomy mapping remains a later measured
step. MuScriptor 0.2.2 does not expose confidence and does not preserve
velocity, so both remain explicitly unavailable.

For a fixed repeatability excerpt, export `MUSCRIPTOR_AUDIO` when submitting
the Slurm script. The input hash and exact path are captured in the request and
run manifest.

## Hyak

Set up the locked root and worker environments without running inference:

```bash
bash scripts/hyak/setup_muscriptor.sh
```

Submit `slurm/10_muscriptor_baseline.slurm` with `PROJECT_DIR`,
`AMT_REPO_ROOT`, and `MUSCRIPTOR_WEIGHT_PROVENANCE` exported. Optional
`MUSCRIPTOR_AUDIO`, `MUSCRIPTOR_BEAM_SIZE`, and `MUSCRIPTOR_RUN_ID` values
configure excerpt runs. All model inference must run inside Slurm, never on a
Mac or `klone-login` node.
