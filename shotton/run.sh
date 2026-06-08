#!/bin/bash
#SBATCH --account=gbov
#SBATCH --job-name=multi-country
#SBATCH --partition=standard
#SBATCH --qos=high
#SBATCH --nodes=1
#SBATCH --time=2-00:00:00
#SBATCH --mem=64G
#SBATCH -o logs/slurm-%j.out
#SBATCH -e logs/slurm-%j.err


set -euo pipefail

echo "===================================================="
echo "JOB START"
echo "===================================================="

echo "hostname: $(hostname)"
echo "pwd: $(pwd)"
echo "date: $(date)"

echo "python: $(which python3)"
echo "snakemake: $(which snakemake)"

echo "top-level repo contents:"
ls -lah

eval "$("$HOME/miniforge3/bin/conda" shell.bash hook)"
conda activate pypsa

# isolate conda package cache
export CONDA_PKGS_DIRS=$PWD/.conda_pkgs

# print cluster config from config.default.yaml (config.yaml may be a minimal stub)
echo "scenario.clusters (from config.default.yaml):"
python - <<'PY'
import yaml, sys
for p in ["config.yaml", "config.default.yaml"]:
    try:
        with open(p) as f:
            cfg = yaml.safe_load(f) or {}
        clusters = cfg.get("scenario", {}).get("clusters")
        if clusters is not None:
            print(f"  {p}: scenario.clusters = {clusters}")
            break
    except FileNotFoundError:
        continue
else:
    print("  WARNING: could not find scenario.clusters in config.yaml or config.default.yaml")
PY

# ---------------------------------------------------
# Snakemake unlock just in case
# ---------------------------------------------------

if [ -d ".snakemake" ]; then
    snakemake --unlock || true
fi

# ---------------------------------------------------
# Run workflow
# ---------------------------------------------------

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

snakemake \
    -s Snakefile \
    -j 1 \
    solve_all_networks \
    --rerun-incomplete \
    --latency-wait 60 \
    --printshellcmds

# ---------------------------------------------------
# Post-solve Ember generation calibration
# ---------------------------------------------------

EMBER_CSV="data/monthly_ember.csv"

if [[ ! -f "$EMBER_CSV" ]]; then
    echo "ERROR: Ember file not found: $EMBER_CSV"
    exit 1
fi

echo "===================================================="
echo "POST-SOLVE GENERATION CALIBRATION"
echo "===================================================="

mapfile -t solved_networks < <(
    find results \
        -type f \
        -path "*/networks/*.nc" \
        -name "elec_s*_ec_l*.nc" \
        ! -name "*_ember.nc" \
        | sort
)

if [[ ${#solved_networks[@]} -eq 0 ]]; then
    echo "No solved networks found."
    exit 1
fi

for network in "${solved_networks[@]}"; do

    output="${network%.nc}_ember.nc"

    echo
    echo "----------------------------------------------------"
    echo "Calibrating:"
    echo "  Input : $network"
    echo "  Output: $output"
    echo "----------------------------------------------------"

    python scripts/scale_generation.py \
        --network "$network" \
        --output "$output" \
        --ember "$EMBER_CSV"

done

echo
echo "Generation calibration complete."