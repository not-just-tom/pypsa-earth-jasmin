#!/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=china_run
#SBATCH --partition=standard
#SBATCH --qos=high
#SBATCH --nodes=1
#SBATCH --time=2-00:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err

# Load modules
module unload jaspy
source ~/miniforge3/bin/activate
conda activate pypsa

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
python -m snakemake -s Snakefile -j 1 solve_all_networks \
  --rerun-incomplete \
  --latency-wait 60 \
  --printshellcmds




