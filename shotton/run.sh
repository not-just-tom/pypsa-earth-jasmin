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

# ---------------------------------------------------
# Snakemake unlock just in case
# ---------------------------------------------------

if [ -d ".snakemake" ]; then
    snakemake --unlock || true
fi

# ---------------------------------------------------
# Run workflow
# ---------------------------------------------------

snakemake \
    -s Snakefile \
    -j 1 \
    solve_all_networks \
    --rerun-incomplete \
    --latency-wait 60 \
    --printshellcmds

# ---------------------------------------------------
# Optional post-solve generation scaling
# ---------------------------------------------------

OBS_GENERATION_CSV="${OBS_GENERATION_CSV:-}"
if [[ -z "$OBS_GENERATION_CSV" ]]; then
    echo "Skipping generation scaling: OBS_GENERATION_CSV is not set"
    exit 0
fi

if [[ ! -f "$OBS_GENERATION_CSV" ]]; then
    echo "ERROR: OBS_GENERATION_CSV not found: $OBS_GENERATION_CSV"
    exit 1
fi

SCALE_EXCLUDE_CARRIERS="${SCALE_EXCLUDE_CARRIERS:-solar}"
SCALE_INCLUDE_CARRIERS="${SCALE_INCLUDE_CARRIERS:-}"
SCALE_COUNTRY_MODE="${SCALE_COUNTRY_MODE:-auto}"
SCALE_GROUP_NAME="${SCALE_GROUP_NAME:-non-solar-generation}"
SCALE_DATETIME_COLUMN="${SCALE_DATETIME_COLUMN:-datetime}"
SCALE_VALUE_COLUMN="${SCALE_VALUE_COLUMN:-}"
SCALE_COUNTRY_COLUMN="${SCALE_COUNTRY_COLUMN:-country}"
SCALE_FACTOR_FLOOR="${SCALE_FACTOR_FLOOR:-}"
SCALE_FACTOR_CAP="${SCALE_FACTOR_CAP:-}"
SCALE_OUTPUT_MODE="${SCALE_OUTPUT_MODE:-suffix}"  # suffix|replace
SCALE_SUFFIX="${SCALE_SUFFIX:-_scaled}"

echo "Running generation scaling with observed data: $OBS_GENERATION_CSV"

mapfile -t solved_networks < <(find results -type f -path "*/networks/*.nc" -name "elec_s*_ec_l*.nc" ! -name "*${SCALE_SUFFIX}.nc" | sort)

if [[ ${#solved_networks[@]} -eq 0 ]]; then
    echo "No solved network files found under results/*/networks"
    exit 1
fi

for network in "${solved_networks[@]}"; do
    if [[ "$SCALE_OUTPUT_MODE" == "replace" ]]; then
        output="${network%.nc}${SCALE_SUFFIX}.tmp.nc"
    else
        output="${network%.nc}${SCALE_SUFFIX}.nc"
    fi

    cmd=(
        python scripts/scale_generation.py
        --network "$network"
        --output "$output"
        --obs "$OBS_GENERATION_CSV"
        --exclude-carriers "$SCALE_EXCLUDE_CARRIERS"
        --country-mode "$SCALE_COUNTRY_MODE"
        --group-name "$SCALE_GROUP_NAME"
        --datetime-column "$SCALE_DATETIME_COLUMN"
        --country-column "$SCALE_COUNTRY_COLUMN"
    )

    if [[ -n "$SCALE_INCLUDE_CARRIERS" ]]; then
        cmd+=(--include-carriers "$SCALE_INCLUDE_CARRIERS")
    fi
    if [[ -n "$SCALE_VALUE_COLUMN" ]]; then
        cmd+=(--value-column "$SCALE_VALUE_COLUMN")
    fi
    if [[ -n "$SCALE_FACTOR_FLOOR" ]]; then
        cmd+=(--factor-floor "$SCALE_FACTOR_FLOOR")
    fi
    if [[ -n "$SCALE_FACTOR_CAP" ]]; then
        cmd+=(--factor-cap "$SCALE_FACTOR_CAP")
    fi

    echo "Scaling network: $network"
    "${cmd[@]}"

    if [[ "$SCALE_OUTPUT_MODE" == "replace" ]]; then
        mv "$output" "$network"
        echo "Replaced original network after scaling: $network"
    else
        echo "Wrote scaled network: $output"
    fi
done

echo "Generation scaling completed"