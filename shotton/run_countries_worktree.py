#!/usr/bin/env python3
"""
Create or reuse per-country clones, generate a per-country config from the
main clone template, and submit one Slurm job per country with CONFIG_FILE
set explicitly.

Usage example:
    python shotton/run_countries_worktree.py --country DE,US
    python shotton/run_countries_worktree.py --country DE,US --reuse
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


DEFAULT_CLONES_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/multi-runs")
DEFAULT_REPO_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/pypsa-earth-jasmin")
DEFAULT_RUNNER = "shotton/run.sh"
DEFAULT_TEMPLATE_CANDIDATES = ("config.yaml", "config.default.yaml")


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


def resolve_template_config(repo: Path) -> Path:
    for candidate in DEFAULT_TEMPLATE_CANDIDATES:
        path = repo / candidate
        if path.exists():
            return path
    expected = ", ".join(DEFAULT_TEMPLATE_CANDIDATES)
    raise FileNotFoundError(f"No template config found in {repo}. Expected one of: {expected}")


def ensure_clone(repo: Path, clones_root: Path, country: str, fresh: bool = True) -> Path:
    clone_dir = clones_root / country
    git_marker = clone_dir / ".git"

    if fresh and clone_dir.exists():
        if git_marker.is_dir():
            print(f"[{country}] Removing existing clone for a clean run: {clone_dir}")
            shutil.rmtree(clone_dir)
        else:
            raise RuntimeError(
                f"Refusing to delete non-git directory for --fresh: {clone_dir}. "
                "Please inspect/remove it manually."
            )

    if git_marker.is_dir():
        return clone_dir
    if git_marker.exists() and not git_marker.is_dir():
        raise RuntimeError(
            f"Target is a git worktree, not a standalone clone: {clone_dir}. "
            "Remove existing country dirs/worktrees first."
        )
    if clone_dir.exists() and any(clone_dir.iterdir()):
        raise RuntimeError(f"Target exists but is not a git clone: {clone_dir}")

    print(f"[{country}] Cloning repo into {clone_dir}")
    # Avoid local clone optimizations so each clone is fully independent.
    run_cmd(["git", "clone", "--no-local", str(repo), str(clone_dir)])
    return clone_dir


def write_country_config(template: Path, clone_dir: Path, country: str) -> Path:
    if not template.exists():
        raise FileNotFoundError(f"Missing config template: {template}")

    with template.open() as file:
        config = yaml.safe_load(file)

    config["countries"] = [country]

    destination = clone_dir / f"config.country.{country}.yaml"
    with destination.open("w") as file:
        yaml.safe_dump(config, file, sort_keys=False)
    return destination


def submit_country_job(clone_dir: Path, country: str, config_path: Path) -> str:
    config_file = str(config_path.resolve())
    log_dir = clone_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "sbatch",
        "--job-name",
        country,
        "--chdir",
        str(clone_dir),
        "--output",
        str(log_dir / "slurm-%j.out"),
        "--error",
        str(log_dir / "slurm-%j.err"),
        f"--export=ALL,CONFIG_FILE={config_file},OBS_URL_CONV=,OBS_URL_SOLAR=",
        DEFAULT_RUNNER,
    ]
    cp = run_cmd(cmd, cwd=clone_dir)
    job_id = parse_job_id(cp.stdout)
    if not job_id:
        raise RuntimeError(f"Could not parse job id from sbatch output: {cp.stdout.strip()}")
    return job_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Create country clones and submit country jobs")
    parser.add_argument("--country", required=True, help="Comma-separated ISO alpha-2 countries, e.g. DE,US,UK")
    freshness = parser.add_mutually_exclusive_group()
    freshness.add_argument(
        "--fresh",
        dest="fresh",
        action="store_true",
        help="Force a clean clone per country (default)",
    )
    freshness.add_argument(
        "--reuse",
        dest="fresh",
        action="store_false",
        help="Reuse existing per-country clones instead of recreating them",
    )
    parser.set_defaults(fresh=True)
    args = parser.parse_args()

    repo = DEFAULT_REPO_ROOT
    clones_root = DEFAULT_CLONES_ROOT

    if not (repo / ".git").exists():
        print(f"Not a git repository: {repo}", file=sys.stderr)
        return 2

    clones_root.mkdir(parents=True, exist_ok=True)
    countries = [sanitize_country(value) for value in args.country.split(",") if value.strip()]
    template_config = resolve_template_config(repo)

    print(f"Using template config: {template_config}")
    if args.fresh:
        print("Fresh mode enabled: existing country clones will be re-created")
    else:
        print("Reuse mode enabled: existing country clones will be reused")

    for country in countries:
        clone_dir = ensure_clone(repo, clones_root, country, fresh=args.fresh)
        print(f"[{country}] Writing per-country config")
        config_path = write_country_config(template_config, clone_dir, country)
        print(f"[{country}] Submitting job")
        job_id = submit_country_job(clone_dir, country, config_path)
        print(f"[{country}] Submitted job {job_id} using {config_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
