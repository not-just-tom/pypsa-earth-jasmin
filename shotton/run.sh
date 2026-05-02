#!/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=china_run
#SBATCH --partition=standard
#SBATCH --nodes=1
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

# Change to repository root
cd $SLURM_SUBMIT_DIR

# Ensure no stale Snakemake lock remains in the working directory
echo "Attempting to unlock Snakemake working directory if locked"
# Try the supported unlock command first (harmless if no lock exists)
snakemake -s Snakefile --unlock || true
# Fallback: remove local .snakemake lock files if they still exist
if [ -d ".snakemake" ]; then
  echo "Removing stale .snakemake lock files"
  rm -rf .snakemake/locks .snakemake/lock || true
fi

# Run 
mkdir -p logs
which snakemake >/dev/null 2>&1 || { echo "snakemake not found in PATH; ensure it's installed in the conda env" >&2; exit 1; }

# Run snakemake target explicitly
snakemake -s Snakefile -j 1 solve_all_networks \
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

