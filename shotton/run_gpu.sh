#!/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=pypsa_country
#SBATCH --partition=orchid
#SBATCH --account=orchid
#SBATCH --qos=orchid
#SBATCH --gres=gpu:1
#SBATCH --time=24:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err

set -euo pipefail

# Initialise conda for non-interactive shells and activate environment
if [ -f "$HOME/miniforge3/bin/conda" ]; then
  eval "$("$HOME"/miniforge3/bin/conda shell.bash hook)" || true
fi
conda activate pypsa 2>/dev/null || conda activate pypsa-earth 2>/dev/null || {
  echo "Failed to activate conda env 'pypsa' or 'pypsa-earth'" >&2
  exit 1
}

# Ensure snakemake is available
which snakemake >/dev/null 2>&1 || { echo "snakemake not found in PATH; ensure it's installed in the conda env" >&2; exit 1; }

cd "$SLURM_SUBMIT_DIR"
mkdir -p logs

# Handle stale Snakemake lock carefully.
has_lock=0
if [ -f ".snakemake/lock" ]; then
  has_lock=1
elif [ -d ".snakemake/locks" ] && [ -n "$(ls -A .snakemake/locks 2>/dev/null)" ]; then
  has_lock=1
fi

if [ "$has_lock" -eq 1 ]; then
  active_count=0
  if command -v squeue >/dev/null 2>&1; then
    active_count="$(squeue -u "$USER" -h -o "%i|%T|%Z" 2>/dev/null | awk -F'|' -v wd="$SLURM_SUBMIT_DIR" -v self="${SLURM_JOB_ID:-}" '
      $2 ~ /RUNNING|PENDING|COMPLETING|CONFIGURING|SUSPENDED/ && $3 == wd && $1 != self {c++}
      END {print c+0}
    ')"
  fi

  if [ "$active_count" -gt 0 ]; then
    echo "Snakemake lock detected and $active_count other active job(s) share this workdir." >&2
    echo "Refusing to unlock automatically to avoid interfering with running jobs." >&2
    exit 3
  fi

  echo "Stale Snakemake lock detected with no other active jobs in this workdir; unlocking."
  snakemake -s Snakefile --unlock || true
fi

echo "Running snakemake with default config"
snakemake -j 1 solve_all_networks \
  --rerun-incomplete \
  --latency-wait 60 \
  --printshellcmds
