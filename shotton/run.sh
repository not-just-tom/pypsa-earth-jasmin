#!/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=multi-country
#SBATCH --partition=standard
#SBATCH --qos=standard
#SBATCH --nodes=1
#SBATCH --time=2-00:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err

set -euo pipefail

# Load modules / initialise conda for non-interactive shells
if [ -f "$HOME/miniforge3/bin/conda" ]; then
  eval "$("$HOME"/miniforge3/bin/conda shell.bash hook)" || true
fi
# Try to activate the expected environment names
conda activate pypsa 2>/dev/null || conda activate pypsa-earth 2>/dev/null || true

# Change to repository root
cd $SLURM_SUBMIT_DIR

# Unlock only when explicitly requested.
# Auto-unlocking from every job can let concurrent jobs bypass lock safety.
if [ "${ALLOW_SNAKEMAKE_UNLOCK:-0}" = "1" ]; then
  echo "ALLOW_SNAKEMAKE_UNLOCK=1 set, running one-time unlock"
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

