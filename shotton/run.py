from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/pypsa-earth-jasmin")
RUNS_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/multi-runs")
RUN_SCRIPT = "shotton/run.sh"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def sanitize_country(country: str) -> str:
    country = country.strip().upper()

    if len(country) != 2:
        raise ValueError(f"Invalid country code: {country}")

    return country


def create_clone(country: str) -> Path:
    run_dir = RUNS_ROOT / country

    if run_dir.exists():
        print(f"[{country}] removing existing directory")
        shutil.rmtree(run_dir)

    print(f"[{country}] copying repository")

    shutil.copytree(
        REPO_ROOT,
        run_dir,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".snakemake",
            "*.pyc",
        ),
    )

    return run_dir


def configure_country(run_dir: Path, country: str) -> None:
    config_path = run_dir / "config.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"No config.yaml found in {run_dir}")

    with config_path.open() as f:
        config = yaml.safe_load(f)

    config["countries"] = [country]

    scenario_clusters = config.get("scenario", {}).get("clusters", [])

    with config_path.open("w") as f:
        yaml.safe_dump(config, f, sort_keys=False)

    print(f"[{country}] configured config.yaml")
    print(f"[{country}] scenario.clusters = {scenario_clusters}")


def submit_job(run_dir: Path, country: str) -> None:
    logs_dir = run_dir / "logs"
    logs_dir.mkdir(exist_ok=True)

    cmd = [
        "sbatch",
        "--job-name",
        f"pypsa-{country}",
        "--chdir",
        str(run_dir),
        "--output",
        str(logs_dir / "slurm-%j.out"),
        "--error",
        str(logs_dir / "slurm-%j.err"),
        RUN_SCRIPT,
    ]

    print(f"[{country}] submitting")
    print(" ".join(cmd))

    cp = run(cmd, cwd=run_dir)

    print(cp.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--countries",
        required=True,
        help="Comma-separated list, e.g. DE,FR,ES",
    )

    args = parser.parse_args()

    countries = [
        sanitize_country(c)
        for c in args.countries.split(",")
        if c.strip()
    ]

    RUNS_ROOT.mkdir(parents=True, exist_ok=True)

    for country in countries:
        print("=" * 80)
        print(f"Preparing {country}")
        print("=" * 80)

        run_dir = create_clone(country)

        configure_country(run_dir, country)

        submit_job(run_dir, country)


if __name__ == "__main__":
    main()
