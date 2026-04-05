#!/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=china_run
#SBATCH --partition=standard
#SBATCH --qos=standard
#SBATCH --nodes=1
#SBATCH --time=24:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err

# Load modules
module unload jaspy
source ~/miniforge3/bin/activate
conda activate pypsa

# Change to repository root
cd $SLURM_SUBMIT_DIR

# Run 
python -m snakemake -s Snakefile -j 1 solve_all_networks \
  --rerun-incomplete \
  --latency-wait 60 \
  --printshellcmds




