#!/usr/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=multi-country-full
#SBATCH --partition=standard
#SBATCH --qos=high
#SBATCH --nodes=1
#SBATCH --time=2-00:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err

set -euo pipefail

eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"
conda activate pypsa

echo "Running full workflow..."

snakemake \
    -s Snakefile \
    -j 1 \
    solve_all_networks \
    --rerun-incomplete \
    --latency-wait 60 \
    --printshellcmds

echo "Full workflow finished."