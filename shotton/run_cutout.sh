#!/usr/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=multi-country-cutout
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

echo "Building cutout..."

python - <<'PY'
import yaml

with open("config.default.yaml") as f:
    cfg = yaml.safe_load(f)

cfg.setdefault("enable", {})["build_cutout"] = True

with open("config.default.yaml", "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
PY

snakemake \
    -s Snakefile \
    -j 1 \
    cutouts/cutout-2023-era5.nc \
    --rerun-incomplete \
    --latency-wait 60 \
    --printshellcmds

echo "Cutout finished."

python - <<'PY'
import yaml

with open("config.default.yaml") as f:
    cfg = yaml.safe_load(f)

cfg.setdefault("enable", {})["build_cutout"] = False

with open("config.default.yaml", "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
PY

echo "Submitting full workflow..."

sbatch run_full.sh