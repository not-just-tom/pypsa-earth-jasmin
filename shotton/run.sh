#!/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=multi-country
#SBATCH --partition=standard
#SBATCH --qos=standard
#SBATCH --nodes=1
#SBATCH --time=24:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err


set -euo pipefail

echo "[LOUD DIAG] --- job starting ---"
echo "[LOUD DIAG] date: $(date)"
echo "[LOUD DIAG] hostname: $(hostname)"
echo "[LOUD DIAG] whoami: $(whoami)"
echo "[LOUD DIAG] pwd: $(pwd)"
echo "[LOUD DIAG] SLURM_JOB_ID: ${SLURM_JOB_ID:-}"
echo "[LOUD DIAG] SLURM_SUBMIT_DIR: ${SLURM_SUBMIT_DIR:-}"
echo "[LOUD DIAG] CONFIG_FILE: ${CONFIG_FILE:-}"
echo "[LOUD DIAG] OBS_URL_CONV: ${OBS_URL_CONV:-}"
echo "[LOUD DIAG] OBS_URL_SOLAR: ${OBS_URL_SOLAR:-}"
echo "[LOUD DIAG] CONDA_DEFAULT_ENV: ${CONDA_DEFAULT_ENV:-}"
echo "[LOUD DIAG] CONDA_PREFIX: ${CONDA_PREFIX:-}"
echo "[LOUD DIAG] python: $(which python3) $(python3 --version 2>&1 | head -n1)"
echo "[LOUD DIAG] snakemake: $(which snakemake) $(snakemake --version 2>&1 | head -n1)"
echo "[LOUD DIAG] git: $(which git) $(git --version 2>&1 | head -n1)"
echo "[LOUD DIAG] git root: $(git rev-parse --show-toplevel 2>/dev/null || echo N/A)"
echo "[LOUD DIAG] git commit: $(git rev-parse HEAD 2>/dev/null || echo N/A)"
echo "[LOUD DIAG] git branch: $(git branch --show-current 2>/dev/null || echo N/A)"
echo "[LOUD DIAG] git status: $(git status --short 2>/dev/null | head -n 10)"
echo "[LOUD DIAG] env snapshot (selected):"
env | grep -E '^(USER|HOME|SHELL|HOSTNAME|CONDA|PYTHONPATH|CONFIG_FILE|OBS_URL|HTTP|HTTPS|NO_PROXY|SLURM)' | sort

echo "[LOUD DIAG] Directory tree (top 100 entries):"
find . -maxdepth 3 -print | head -n 100

for d in data logs .snakemake; do
  if [ -d "$d" ]; then
    echo "[LOUD DIAG] Contents of $d (up to 100 entries):"
    find "$d" | head -n 100
  else
    echo "[LOUD DIAG] $d missing"
  fi
done

echo "[LOUD DIAG] --- end diagnostics ---"

# Load modules / initialise conda for non-interactive shells
if [ -f "$HOME/miniforge3/bin/conda" ]; then
  eval "$("$HOME"/miniforge3/bin/conda shell.bash hook)" || true
fi
# Try to activate the expected environment names
conda activate pypsa 2>/dev/null || conda activate pypsa-earth 2>/dev/null || true

# Change to repository root
cd $SLURM_SUBMIT_DIR

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

# If CONFIG_FILE env var is set, use it
if [ -n "${CONFIG_FILE-}" ]; then
  CONFIG_ARG=(--configfile "$CONFIG_FILE")
else
  CONFIG_ARG=()
fi

# Run
snakemake -s Snakefile -j 1 solve_all_networks "${CONFIG_ARG[@]}" \
  --rerun-incomplete \
  --latency-wait 60 \
  --printshellcmds

# ------------------------------------------------------------------
# Post-run: fetch observed data (if URLs provided) and scale generation
# Set OBS_URL_SOLAR and OBS_URL_CONV environment variables before submitting
# Example: sbatch --export=OBS_URL_SOLAR=https://.../obs_solar.csv,OBS_URL_CONV=https://.../obs_conv.csv run.sh
mkdir -p data/custom

if [ -n "$OBS_URL_CONV" ]; then
  echo "Fetching observed conventional generation from $OBS_URL_CONV"
  curl -fsSL "$OBS_URL_CONV" -o data/custom/observed_conv.csv || { echo "Failed to download OBS_URL_CONV"; exit 1; }
else
  echo "OBS_URL_CONV not set — skipping conventional download"
fi

# Network file to post-process (override with NETWORK_PATH env var)
: ${NETWORK_PATH:="results/networks/elec_s_10_ec_lcopt_Co2L-3h.nc"}
: ${OUTPUT_NETWORK:="results/networks/elec_s_10_ec_lcopt_Co2L-3h_scaled.nc"}

echo "Post-processing network: $NETWORK_PATH -> $OUTPUT_NETWORK"

# Run scaling script 
python3 scripts/scale_generation.py \
  --network "$NETWORK_PATH" \
  --obs-solar data/custom/observed_solar.csv \
  --obs-conv data/custom/observed_conv.csv \
  --output "$OUTPUT_NETWORK"

