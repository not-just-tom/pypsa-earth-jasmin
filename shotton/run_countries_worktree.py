#!/usr/bin/env python3
"""
Create or reuse per-country worktrees, overwrite config.default.yaml in each
worktree with a copy from the main clone, change only the country, and submit
one Slurm job per country.

Usage example:
  python shotton/run_countries_worktree.py --country DE,US
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

import yaml


DEFAULT_WORKTREES_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/multi-runs")
DEFAULT_REPO_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/pypsa-earth-jasmin")
DEFAULT_RUNNER = "shotton/run.sh"


def run_cmd(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True)
    except subprocess.CalledProcessError as err:
        stderr = (err.stderr or "").strip()
        stdout = (err.stdout or "").strip()
        details = stderr or stdout or "(no output)"
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{details}") from err


def parse_job_id(sbatch_output: str) -> str | None:
    match = re.search(r"(\d+)$", sbatch_output.strip())
    return match.group(1) if match else None


def sanitize_country(country: str) -> str:
    value = country.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise ValueError(f"Invalid country code '{country}'. Expected ISO alpha-2.")
    return value


def ensure_worktree(repo: Path, worktrees_root: Path, country: str, stamp: str) -> Path:
    worktree_dir = worktrees_root / country
    if worktree_dir.exists() and any(worktree_dir.iterdir()):
        return worktree_dir

    print(f"[{country}] Creating worktree at {worktree_dir}")
    run_cmd(["git", "-C", str(repo), "worktree", "add", "--detach", str(worktree_dir), "main"])
    return worktree_dir


def write_country_config(repo: Path, worktree_dir: Path, country: str) -> Path:
    template = repo / "config.default.yaml"
    if not template.exists():
        raise FileNotFoundError(f"Missing config template: {template}")

    with template.open() as file:
        config = yaml.safe_load(file)

    config["countries"] = [country]

    destination = worktree_dir / "config.default.yaml"
    with destination.open("w") as file:
        yaml.safe_dump(config, file, sort_keys=False)
    return destination


def submit_country_job(worktree_dir: Path, country: str) -> str:
    cmd = [
        "sbatch",
        "--job-name",
        country,
        "--export=ALL,OBS_URL_CONV=,OBS_URL_SOLAR=",
        DEFAULT_RUNNER,
    ]
    cp = run_cmd(cmd, cwd=worktree_dir)
    job_id = parse_job_id(cp.stdout)
    if not job_id:
        raise RuntimeError(f"Could not parse job id from sbatch output: {cp.stdout.strip()}")
    return job_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Create country worktrees and submit country jobs")
    parser.add_argument("--country", required=True, help="Comma-separated ISO alpha-2 countries, e.g. DE,US,UK")
    args = parser.parse_args()

    repo = DEFAULT_REPO_ROOT
    worktrees_root = DEFAULT_WORKTREES_ROOT

    if not (repo / ".git").exists():
        print(f"Not a git repository: {repo}", file=sys.stderr)
        return 2

    worktrees_root.mkdir(parents=True, exist_ok=True)
    countries = [sanitize_country(value) for value in args.country.split(",") if value.strip()]
    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")

    for country in countries:
        worktree_dir = ensure_worktree(repo, worktrees_root, country, stamp)
        print(f"[{country}] Writing config.default.yaml")
        config_path = write_country_config(repo, worktree_dir, country)
        print(f"[{country}] Submitting job")
        job_id = submit_country_job(worktree_dir, country)
        print(f"[{country}] Submitted job {job_id} using {config_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
