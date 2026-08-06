#!/usr/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=multi-country
#SBATCH --partition=standard
#SBATCH --qos=high
#SBATCH --nodes=1
#SBATCH --time=2-00:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err

# ---------------------------------------------------
# Run workflow
# ---------------------------------------------------
set -euo pipefail
# ---------------------------------------------------
# Run workflow
# ---------------------------------------------------

STAGE="${STAGE:-full}"

eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"
conda activate pypsa

# Use config.default.yaml as the country source-of-truth by preventing
# config.yaml from overriding it during this run.
CONFIG_YAML_BACKUP=""
if [[ -f "config.yaml" ]]; then
    CONFIG_YAML_BACKUP="config.yaml.runsh.bak"
    mv "config.yaml" "$CONFIG_YAML_BACKUP"
fi

restore_config_yaml() {
    if [[ -n "$CONFIG_YAML_BACKUP" && -f "$CONFIG_YAML_BACKUP" ]]; then
        mv "$CONFIG_YAML_BACKUP" "config.yaml"
    fi
}

trap restore_config_yaml EXIT

if [[ "$STAGE" == "cutout" ]]; then

    echo "===================================================="
    echo "STAGE 1: BUILD CUTOUT"
    echo "===================================================="

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

    echo
    echo "Cutout completed successfully."
    echo "Switching build_cutout -> false"

    python - <<'PY'
import yaml

with open("config.default.yaml") as f:
    cfg = yaml.safe_load(f)

cfg.setdefault("enable", {})["build_cutout"] = False

with open("config.default.yaml", "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
PY

    echo "Submitting continuation job..."

    sbatch \
        --dependency=afterok:${SLURM_JOB_ID} \
        --job-name="${SLURM_JOB_NAME/-cutout/-full}" \
        --chdir="$PWD" \
        --output="logs/slurm-%j.out" \
        --error="logs/slurm-%j.err" \
        --export=ALL,STAGE=full \
        "$0"

    echo "Continuation job submitted."
    exit 0

fi

echo "===================================================="
echo "STAGE 2: FULL WORKFLOW"
echo "===================================================="

snakemake \
    -s Snakefile \
    -j 1 \
    solve_all_networks \
    --rerun-incomplete \
    --latency-wait 60 \
    --printshellcmds