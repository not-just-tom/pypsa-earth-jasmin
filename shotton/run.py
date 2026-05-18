#!/usr/bin/env python3
"""
Minimal multi-country launcher with heavy diagnostics.

What it does:
1) Runs diagnostics in the main repository clone.
2) Submits one compare job from the main repository using shotton/run.sh.
3) Recreates one fresh clone per country.
4) Writes a per-country config file with countries=[CC].
5) Runs diagnostics in each country clone.
6) Submits one Slurm job per country using shotton/run.sh.

Usage:
  python shotton/run.py --countries DE,US,UK
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


DEFAULT_CLONES_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/multi-runs")
DEFAULT_REPO_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/pypsa-earth-jasmin")
DEFAULT_RUNNER = "shotton/run.sh"
DEFAULT_TEMPLATE_CANDIDATES = ("config.yaml", "config.default.yaml")


def banner(title: str) -> None:
    line = "=" * 88
    print(f"\n{line}\n{title}\n{line}")


def run_cmd(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)
    except subprocess.CalledProcessError as err:
        stderr = (err.stderr or "").strip()
        stdout = (err.stdout or "").strip()
        details = stderr or stdout or "(no output)"
        raise RuntimeError(f"Command failed: {' '.join(cmd)}\n{details}") from err


def print_cmd(name: str, cmd: list[str], cwd: Path | None) -> None:
    where = str(cwd) if cwd else os.getcwd()
    print(f"[diag] {name}")
    print(f"       cwd: {where}")
    print(f"       cmd: {' '.join(cmd)}")
    cp = run_cmd(cmd, cwd=cwd, check=False)
    print(f"       rc : {cp.returncode}")
    stdout = (cp.stdout or "").strip()
    stderr = (cp.stderr or "").strip()
    if stdout:
        print("       out:")
        for line in stdout.splitlines()[:40]:
            print(f"         {line}")
    if stderr:
        print("       err:")
        for line in stderr.splitlines()[:20]:
            print(f"         {line}")


def sanitize_country(country: str) -> str:
    value = country.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", value):
        raise ValueError(f"Invalid country code '{country}'. Expected ISO alpha-2.")
    return value


def parse_job_id(sbatch_output: str) -> str | None:
    match = re.search(r"(\d+)$", sbatch_output.strip())
    return match.group(1) if match else None


def resolve_template_config(repo: Path) -> Path:
    for candidate in DEFAULT_TEMPLATE_CANDIDATES:
        path = repo / candidate
        if path.exists():
            return path
    expected = ", ".join(DEFAULT_TEMPLATE_CANDIDATES)
    raise FileNotFoundError(f"No template config found in {repo}. Expected one of: {expected}")


def print_path_state(root: Path) -> None:
    print("[diag] path state")
    inspect = [
        root,
        root / ".git",
        root / "Snakefile",
        root / "shotton" / "run.sh",
        root / "config.yaml",
        root / "config.default.yaml",
        root / "data",
        root / "logs",
        root / ".snakemake",
    ]
    for path in inspect:
        kind = "dir" if path.is_dir() else "file" if path.is_file() else "missing"
        print(f"       - {path}: {kind}")

    lock_file = root / ".snakemake" / "lock"
    locks_dir = root / ".snakemake" / "locks"
    has_locks_dir = locks_dir.is_dir() and any(locks_dir.iterdir())
    print(f"       - lock file present: {lock_file.is_file()}")
    print(f"       - locks dir has files: {has_locks_dir}")

    data_dir = root / "data"
    if data_dir.is_dir():
        top = sorted(child.name for child in data_dir.iterdir())[:30]
        print(f"       - data/ top entries (up to 30): {', '.join(top)}")


def print_env_snapshot() -> None:
    print("[diag] environment snapshot")
    keep = [
        "USER",
        "HOME",
        "SHELL",
        "HOSTNAME",
        "CONDA_DEFAULT_ENV",
        "CONDA_PREFIX",
        "PYTHONPATH",
        "CONFIG_FILE",
        "OBS_URL_CONV",
        "OBS_URL_SOLAR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "SLURM_JOB_ID",
        "SLURM_SUBMIT_DIR",
    ]
    for key in keep:
        print(f"       - {key}={os.environ.get(key, '')}")


def diagnostics(repo_dir: Path, label: str) -> None:
    banner(f"DIAGNOSTICS: {label}")
    print(f"[diag] timestamp utc: {datetime.now(timezone.utc).isoformat()}")
    print(f"[diag] python: {sys.executable}")
    print(f"[diag] python version: {platform.python_version()}")
    print(f"[diag] platform: {platform.platform()}")
    print(f"[diag] cwd when called: {Path.cwd()}")
    print(f"[diag] target repo dir: {repo_dir}")
    print_env_snapshot()
    print_path_state(repo_dir)

    print_cmd("git root", ["git", "rev-parse", "--show-toplevel"], cwd=repo_dir)
    print_cmd("git commit", ["git", "rev-parse", "HEAD"], cwd=repo_dir)
    print_cmd("git branch", ["git", "branch", "--show-current"], cwd=repo_dir)
    print_cmd("git status short", ["git", "status", "--short"], cwd=repo_dir)
    print_cmd("which python3", ["which", "python3"], cwd=repo_dir)
    print_cmd("python3 version", ["python3", "--version"], cwd=repo_dir)
    print_cmd("which snakemake", ["which", "snakemake"], cwd=repo_dir)
    print_cmd("snakemake version", ["snakemake", "--version"], cwd=repo_dir)
    print_cmd("which sbatch", ["which", "sbatch"], cwd=repo_dir)
    print_cmd("scontrol version", ["scontrol", "--version"], cwd=repo_dir)


def ensure_fresh_clone(repo: Path, clones_root: Path, country: str) -> Path:
    clone_dir = clones_root / country
    git_marker = clone_dir / ".git"

    if clone_dir.exists():
        if git_marker.is_dir():
            print(f"[{country}] Removing existing clone for clean run: {clone_dir}")
            shutil.rmtree(clone_dir)
        else:
            raise RuntimeError(
                f"Refusing to delete non-git directory: {clone_dir}. Please remove it manually."
            )

    print(f"[{country}] Cloning repo into {clone_dir}")
    run_cmd(["git", "clone", "--no-local", str(repo), str(clone_dir)])
    return clone_dir


def write_country_config(template: Path, clone_dir: Path, country: str) -> Path:
    with template.open() as file:
        config = yaml.safe_load(file)

    config["countries"] = [country]
    destination = clone_dir / f"config.country.{country}.yaml"
    with destination.open("w") as file:
        yaml.safe_dump(config, file, sort_keys=False)
    return destination


def submit_job(repo_dir: Path, job_name: str, config_file: Path | None) -> str:
    log_dir = repo_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    export_items = ["ALL", "OBS_URL_CONV=", "OBS_URL_SOLAR="]
    if config_file is not None:
        export_items.append(f"CONFIG_FILE={config_file.resolve()}")

    cmd = [
        "sbatch",
        "--job-name",
        job_name,
        "--chdir",
        str(repo_dir),
        "--output",
        str(log_dir / "slurm-%j.out"),
        "--error",
        str(log_dir / "slurm-%j.err"),
        "--export=" + ",".join(export_items),
        DEFAULT_RUNNER,
    ]

    print(f"[submit] {' '.join(cmd)}")
    cp = run_cmd(cmd, cwd=repo_dir)
    print(f"[submit] sbatch stdout: {(cp.stdout or '').strip()}")
    job_id = parse_job_id(cp.stdout)
    if not job_id:
        raise RuntimeError(f"Could not parse job id from sbatch output: {(cp.stdout or '').strip()}")

    print(f"[submit] job={job_id} out={log_dir / f'slurm-{job_id}.out'} err={log_dir / f'slurm-{job_id}.err'}")
    return job_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal per-country launcher with heavy diagnostics")
    parser.add_argument("--countries", required=True, help="Comma-separated ISO alpha-2 countries, e.g. DE,US,UK")
    args = parser.parse_args()

    repo = DEFAULT_REPO_ROOT
    clones_root = DEFAULT_CLONES_ROOT

    if not (repo / ".git").exists():
        print(f"Not a git repository: {repo}", file=sys.stderr)
        return 2

    countries = [sanitize_country(value) for value in args.countries.split(",") if value.strip()]
    if not countries:
        print("No countries provided after parsing --countries", file=sys.stderr)
        return 2

    template_config = resolve_template_config(repo)
    clones_root.mkdir(parents=True, exist_ok=True)

    diagnostics(repo, "MAIN CLONE BEFORE COUNTRY CLONES")
    print("[main] Submitting compare job from main clone")
    main_job = submit_job(repo, "MAIN-COMPARE", config_file=None)
    print(f"[main] Submitted compare job id={main_job}")

    for country in countries:
        clone_dir = ensure_fresh_clone(repo, clones_root, country)
        config_path = write_country_config(template_config, clone_dir, country)
        diagnostics(clone_dir, f"COUNTRY CLONE {country} BEFORE SUBMIT")
        print(f"[{country}] Submitting country job")
        country_job = submit_job(clone_dir, country, config_file=config_path)
        print(f"[{country}] Submitted job id={country_job} config={config_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
