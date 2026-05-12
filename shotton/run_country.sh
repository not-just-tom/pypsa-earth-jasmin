#!/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=pypsa_country
#SBATCH --partition=orchid
#SBATCH --account=orchid
#SBATCH --qos=orchid
#SBATCH --gres=gpu:1
#SBATCH --time=2-00:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <config-file>"
  exit 2
fi

CONFIG_FILE="$1"

# Initialise conda for non-interactive shells and activate environment
if [ -f "$HOME/miniforge3/bin/conda" ]; then
  eval "$("$HOME"/miniforge3/bin/conda shell.bash hook)" || true
fi
conda activate pypsa 2>/dev/null || conda activate pypsa-earth 2>/dev/null || {
  echo "Failed to activate conda env 'pypsa' or 'pypsa-earth'" >&2
  exit 1
}

# Ensure snakemake is available, then unlock if needed
which snakemake >/dev/null 2>&1 || { echo "snakemake not found in PATH; ensure it's installed in the conda env" >&2; exit 1; }
snakemake -s Snakefile --unlock || true

cd "$SLURM_SUBMIT_DIR"
mkdir -p logs

echo "Running snakemake with configfile: $CONFIG_FILE"
snakemake -j 1 solve_all_networks --configfile "$CONFIG_FILE"
