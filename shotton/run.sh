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

echo "cwd=$(pwd)"

export CONDA_PKGS_DIRS=$PWD/.conda_pkgs

conda activate pypsa

snakemake \
    -j 1 \
    solve_all_networks \
    --rerun-incomplete \
    --latency-wait 60