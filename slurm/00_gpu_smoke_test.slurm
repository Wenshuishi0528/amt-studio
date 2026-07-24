#!/bin/bash
#SBATCH --job-name=amt-gpu-smoke
#SBATCH --account=stf
#SBATCH --partition=gpu-l40
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --gpus=l40:1
#SBATCH --time=00:10:00
#SBATCH --output=/gscratch/stf/%u/amt-studio/logs/%x-%j.out
#SBATCH --error=/gscratch/stf/%u/amt-studio/logs/%x-%j.err
#SBATCH --export=ALL

set -euo pipefail

PERSIST_ROOT="${HYAK_PERSIST_ROOT:-/gscratch/stf/$USER/amt-studio}"
mkdir -p "$PERSIST_ROOT/logs" "$PERSIST_ROOT/manifests"
chmod 700 "$PERSIST_ROOT/logs" "$PERSIST_ROOT/manifests"

RUN_DIR="$PERSIST_ROOT/manifests/${SLURM_JOB_NAME}-${SLURM_JOB_ID}"
mkdir -p "$RUN_DIR"

{
  echo "timestamp=$(date --iso-8601=seconds)"
  echo "hostname=$(hostname)"
  echo "job_id=$SLURM_JOB_ID"
  echo "account=$SLURM_JOB_ACCOUNT"
  echo "partition=$SLURM_JOB_PARTITION"
  echo "cpus=$SLURM_CPUS_PER_TASK"
  echo "cuda_visible_devices=${CUDA_VISIBLE_DEVICES:-}"
  uname -a
  nvidia-smi
} | tee "$RUN_DIR/diagnostics.txt"

python3 - <<'PY' | tee "$RUN_DIR/python.txt"
import platform
import sys
print(sys.version)
print(platform.platform())
try:
    import torch
    print("torch", torch.__version__)
    print("cuda_available", torch.cuda.is_available())
    if torch.cuda.is_available():
        print("device", torch.cuda.get_device_name(0))
except Exception as exc:
    print("torch_check", repr(exc))
PY

echo "Smoke test complete"
