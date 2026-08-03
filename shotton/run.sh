#!/usr/bin/env bash

# ---------------------------------------------------
# Run workflow
# ---------------------------------------------------
set -euo pipefail

echo "===================================================="
echo "STAGE 1: BUILD CUTOUT"
echo "===================================================="

snakemake \
    -s Snakefile \
    -j 1 \
    build_cutout \
    --rerun-incomplete \
    --latency-wait 60 \
    --printshellcmds

echo "Cutout completed successfully."
echo "Disabling enable.build_cutout for the rest of the workflow."

python - <<'PY'
import yaml

with open("config.yaml") as f:
    cfg = yaml.safe_load(f) or {}

cfg.setdefault("enable", {})["build_cutout"] = False

with open("config.yaml", "w") as f:
    yaml.safe_dump(cfg, f, sort_keys=False)
PY

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
