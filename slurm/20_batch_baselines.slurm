#!/bin/bash
#SBATCH --job-name=amt-batch-baseline
#SBATCH --account=stf
#SBATCH --partition=ckpt-g2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gpus=l40:1
#SBATCH --time=1-00:00:00
#SBATCH --requeue
#SBATCH --signal=B:TERM@120
#SBATCH --output=/gscratch/stf/%u/amt-studio/logs/%x-%A_%a.out
#SBATCH --error=/gscratch/stf/%u/amt-studio/logs/%x-%A_%a.err
#SBATCH --export=ALL

set -euo pipefail

: "${MANIFEST:?Set MANIFEST to a newline-delimited list of project directories}"
index="${SLURM_ARRAY_TASK_ID:-0}"
PROJECT_DIR="$(sed -n "$((index + 1))p" "$MANIFEST")"
if [[ -z "$PROJECT_DIR" ]]; then
  echo "No project at array index $index" >&2
  exit 2
fi

# This is deliberately a placeholder until Task 008 implements content-addressed
# run caching and interruption-safe orchestration.
echo "Selected project: $PROJECT_DIR"
echo "Implement only after single-project baselines are reproducible."
exit 3
