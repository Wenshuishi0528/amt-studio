#!/bin/bash
#SBATCH --job-name=amt-separator-setup
#SBATCH --account=stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt-gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gpus=a40:1
#SBATCH --time=02:00:00
#SBATCH --requeue
#SBATCH --signal=B:TERM@120
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Submit this script with sbatch; do not run it on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${SEPARATOR_MODEL_DIR:?Export SEPARATOR_MODEL_DIR in persistent storage}"
: "${SEPARATOR_MODEL_PROVENANCE:?Export SEPARATOR_MODEL_PROVENANCE as an output JSON path}"

cd "$AMT_REPO_ROOT"
srun bash "$AMT_REPO_ROOT/scripts/hyak/setup_separator.sh"
