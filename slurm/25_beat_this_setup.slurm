#!/bin/bash
#SBATCH --job-name=amt-beat-setup
#SBATCH --account=stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt-gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gpus=a40:1
#SBATCH --time=02:00:00
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
exec "$AMT_REPO_ROOT/scripts/hyak/setup_beat_this.sh"
