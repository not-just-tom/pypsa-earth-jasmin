#!/bin/bash
# Simple per-country Slurm runner for PyPSA-Earth
# Usage: sbatch run_country.sh <config-file>
# Expects to be submitted from repository root (SLURM_SUBMIT_DIR)

#SBATCH --account=gbov
#SBATCH --job-name=pypsa_country
#SBATCH --partition=standard
#SBATCH --nodes=1
#SBATCH --time=24:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <config-file>"
  exit 2
fi

CONFIG_FILE="$1"

# Activate conda environment (adjust path if necessary)
source ~/miniforge3/bin/activate || true
conda activate pypsa-earth || conda activate pypsa || true

cd "$SLURM_SUBMIT_DIR"

echo "Running snakemake with configfile: $CONFIG_FILE"
# Run snakemake in the repository root, using the provided config file
snakemake -j 1 --configfile "$CONFIG_FILE" 
