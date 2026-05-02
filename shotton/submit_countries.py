#!/usr/bin/env python3
"""
Create per-country config overrides and submit one Slurm job per country.

Behavior
- Uses `pycountry` to enumerate ISO alpha_2 country codes. If unavailable,
  falls back to a small builtin list of common codes (can be extended).
- For each country it creates a generated config in `configs/generated/` that:
  - sets the `countries` list to the single alpha2 code
  - sets `run.shared_cutouts` to False so cutouts are unique per run
  - renames the atlite cutout key by appending the alpha2 code
  - sets `scenario.clusters` to ["min"] so clustering picks the minimal
    allowed number for that country (avoids the n_clusters < groups error)
- Skips countries that have an existing cutout file or an existing results file

Usage: python shotton/submit_countries.py
"""
import os
import sys
import subprocess
from pathlib import Path
import argparse

try:
    import yaml
except Exception:
    print("PyYAML is required. Please install it in your environment.")
    raise

try:
    import pycountry
except Exception:
    pycountry = None

ROOT = Path(__file__).resolve().parents[1]
CONFIG_TEMPLATE = ROOT / "config.yaml"
GENERATED_DIR = ROOT / "configs" / "generated"
GENERATED_DIR.mkdir(parents=True, exist_ok=True)

# Output locations to check for completion
CUTOUTS_DIR = ROOT / "cutouts"
RESULTS_DIR = ROOT / "results"

def all_alpha2_codes():
    if pycountry is None:
        raise RuntimeError("pycountry is required unless you pass --countries on the command line")
    return sorted({c.alpha_2 for c in pycountry.countries})

def load_yaml(p: Path):
    with p.open() as f:
        return yaml.safe_load(f)

def dump_yaml(data, p: Path):
    with p.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False)

def make_country_config(alpha2: str):
    cfg = load_yaml(CONFIG_TEMPLATE)
    # set single country
    cfg["countries"] = [alpha2]
    # force unique cutouts per run
    cfg.setdefault("run", {})
    cfg["run"]["shared_cutouts"] = False
    # prefix results and outputs by setting the run name; this makes RDIR = '<alpha2>/'
    cfg["run"]["name"] = alpha2
    # rename atlite cutout key so Snakemake writes cutouts/cutout-XXX-<alpha2>.nc
    # we append the alpha2 to the configured cutout keys
    if "atlite" in cfg and "cutouts" in cfg["atlite"]:
        new = {}
        for k, v in cfg["atlite"]["cutouts"].items():
            new_key = f"{k}-{alpha2}"
            new[new_key] = v
        cfg["atlite"]["cutouts"] = new
    # set clusters to `min` so the workflow chooses minimal allowed clusters
    cfg.setdefault("scenario", {})
    cfg["scenario"]["clusters"] = ["min"]
    # write generated config
    out = GENERATED_DIR / f"config_{alpha2}.yaml"
    dump_yaml(cfg, out)
    return out

def is_done(alpha2: str):
    # If cutout exists, skip
    # We expect cutout files named like cutouts/<cutoutkey>.nc where cutoutkey ends with -<alpha2>
    for p in CUTOUTS_DIR.glob(f"*{alpha2}*.nc"):
        if p.exists():
            return True
    # Or if results directory has any files for that country (best-effort)
    for p in RESULTS_DIR.rglob(f"*{alpha2}*.nc"):
        if p.exists():
            return True
    return False

def submit_job(config_path: Path):
    # Submit the real job script directly to sbatch so the SBATCH directives
    # in shotton/run_country.sh are used. Avoid creating an outer wrapper
    # that itself calls sbatch (some clusters reject such double-submission).
    alpha2 = config_path.stem.split("_")[-1]
    job_cmd = ["sbatch", "shotton/run_country.sh", str(config_path)]
    print(f"Submitting {config_path} for {alpha2}")
    try:
        subprocess.check_call(job_cmd)
    except subprocess.CalledProcessError as e:
        print(f"sbatch failed for {alpha2}: {e}")
    except FileNotFoundError:
        print("sbatch not found in PATH; are you on the login node?")

def main():
    parser = argparse.ArgumentParser(description="Generate per-country configs and submit sbatch jobs")
    parser.add_argument("--account", help="Slurm account to pass to sbatch (-A)")
    parser.add_argument("--countries", help="Comma-separated list of ISO alpha2 codes to run (overrides pycountry)")
    args = parser.parse_args()

    if args.countries:
        codes = [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    else:
        codes = all_alpha2_codes()

    print(f"Found {len(codes)} country codes to process")
    for code in codes:
        if is_done(code):
            print(f"Skipping {code}: already appears complete")
            continue
        cfg = make_country_config(code)
        # If an account was requested, set SBATCH_ACCOUNT env so sbatch sees it
        if args.account:
            os.environ.setdefault("SBATCH_ACCOUNT", args.account)
        submit_job(cfg)

if __name__ == "__main__":
    main()
