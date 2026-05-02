#!/bin/bash
# Simple per-country Slurm runner for PyPSA-Earth
# Usage: sbatch run_country.sh <config-file>
# Expects to be submitted from repository root (SLURM_SUBMIT_DIR)

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

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <config-file>"
  exit 2ada
fi
snakemake -s Snakefile --unlock || true
CONFIG_FILE="$1"

# Activate conda environment (adjust path if necessary)
if [ -f "$HOME/miniforge3/bin/conda" ]; then
  # Initialise conda for non-interactive shells
  eval "$("$HOME"/miniforge3/bin/conda shell.bash hook)" || true
fi
# Try a couple of known environment names; prefer the shorter one found on this host
conda activate pypsa 

cd "$SLURM_SUBMIT_DIR"

echo "Running snakemake with configfile: $CONFIG_FILE"
# Run snakemake in the repository root, using the provided config file
snakemake -j 1 solve_all_networks --configfile "$CONFIG_FILE" 
