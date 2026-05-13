#!/usr/bin/env python3
"""
Create isolated git worktrees per country, generate per-country config files,
submit one Slurm job per country, and optionally clean up worktrees after jobs.

Usage example:
  python shotton/run_countries_worktree.py \
    --countries DE,US
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except Exception:
    print("PyYAML is required. Please install it in your environment.")
    raise


DEFAULT_WORKTREES_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/multi-runs")
DEFAULT_REPO_ROOT = Path("/gws/ssde/j25b/gbov/PyPSA-Earth/pypsa-earth-jasmin")


def run_cmd(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def parse_job_id(sbatch_output: str) -> str | None:
    m = re.search(r"(\d+)$", sbatch_output.strip())
    return m.group(1) if m else None


def sanitize_country(country: str) -> str:
    c = country.strip().upper()
    if not re.fullmatch(r"[A-Z]{2}", c):
        raise ValueError(f"Invalid country code '{country}'. Expected ISO alpha-2 (e.g. DE, US).")
    return c


def next_branch_name(repo: Path, base_name: str) -> str:
    cp = run_cmd(["git", "-C", str(repo), "branch", "--list", f"{base_name}*"], check=True)
    existing = {line.strip().lstrip("*").strip() for line in cp.stdout.splitlines() if line.strip()}
    if base_name not in existing:
        return base_name
    i = 1
    while f"{base_name}-{i}" in existing:
        i += 1
    return f"{base_name}-{i}"


def create_country_config(worktree_dir: Path, repo_dir: Path, country: str) -> Path:
    config_template = repo_dir / "config.default.yaml"
    if not config_template.exists():
        raise FileNotFoundError(f"Missing config template: {config_template}")

    with config_template.open() as f:
        cfg = yaml.safe_load(f)

    # Only change the modelled country; keep all other defaults from config.default.yaml.
    cfg["countries"] = [country]

    out = worktree_dir / "config.yaml"
    with out.open("w") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)
    return out


def submit_country_job(
    worktree_dir: Path,
    runner_relpath: str,
    country: str,
    account: str | None,
) -> str:
    export_items = [
        "ALL",
        "OBS_URL_CONV=",
        "OBS_URL_SOLAR=",
    ]
    cmd = ["sbatch", "--job-name", country]
    if account:
        cmd.extend(["-A", account])
    cmd.extend([f"--export={','.join(export_items)}", runner_relpath])

    cp = run_cmd(cmd, cwd=worktree_dir, check=True)
    job_id = parse_job_id(cp.stdout)
    if not job_id:
        raise RuntimeError(f"Could not parse job id from sbatch output: {cp.stdout.strip()}")
    return job_id


def submit_cleanup_job(
    repo: Path,
    worktree_dir: Path,
    branch_name: str,
    country: str,
    dependency_jobid: str,
    account: str | None,
    delete_branch: bool,
) -> str:
    cleanup_branch_cmd = f" && git -C '{repo}' branch -D '{branch_name}'" if delete_branch else ""
    cleanup_script = (
        f"set -euo pipefail; "
        f"git -C '{repo}' worktree remove --force '{worktree_dir}'"
        f"{cleanup_branch_cmd}"
    )

    cmd = [
        "sbatch",
        "--job-name",
        f"cleanup-{country}",
        "--dependency",
        f"afterany:{dependency_jobid}",
    ]
    if account:
        cmd.extend(["-A", account])
    cmd.extend([
        "--wrap",
        cleanup_script,
    ])

    cp = run_cmd(cmd, check=True)
    cleanup_jobid = parse_job_id(cp.stdout)
    if not cleanup_jobid:
        raise RuntimeError(f"Could not parse cleanup job id from sbatch output: {cp.stdout.strip()}")
    return cleanup_jobid


def create_fresh_worktree(
    repo: Path,
    country_worktree: Path,
    country: str,
    base_branch: str,
    stamp: str,
) -> str:
    base_branch_name = f"wt-{country.lower()}-{stamp}"
    branch_name = next_branch_name(repo, base_branch_name)

    print(f"[{country}] Creating branch {branch_name} from {base_branch}")
    run_cmd(["git", "-C", str(repo), "branch", branch_name, base_branch], check=True)

    print(f"[{country}] Creating worktree at {country_worktree}")
    run_cmd(["git", "-C", str(repo), "worktree", "add", str(country_worktree), branch_name], check=True)
    return branch_name


def force_remove_country_worktree(repo: Path, worktrees_root: Path, country_worktree: Path, country: str) -> None:
    # Safety guard to avoid accidental removal outside the configured worktrees root.
    if not str(country_worktree.resolve()).startswith(str(worktrees_root.resolve()) + "/"):
        raise RuntimeError(f"Refusing to remove path outside worktrees root: {country_worktree}")

    try:
        print(f"[{country}] Removing existing git worktree {country_worktree}")
        run_cmd(["git", "-C", str(repo), "worktree", "remove", "--force", str(country_worktree)], check=True)
    except Exception:
        # If the path is not a registered worktree, remove it directly.
        if country_worktree.exists():
            print(f"[{country}] Forcing directory removal for {country_worktree}")
            shutil.rmtree(country_worktree)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create per-country worktrees, generate configs, and submit Slurm jobs"
    )
    parser.add_argument("--countries", required=True, help="Comma-separated ISO alpha-2 countries, e.g. DE,US,UK")
    parser.add_argument("--base-branch", default="main", help="Base branch to create per-country branches from")
    parser.add_argument("--runner", default="shotton/run.sh", help="Runner path relative to each worktree")
    parser.add_argument("--account", default=None, help="Optional Slurm account override")
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Submit a dependent cleanup job to remove each worktree after country job completes",
    )
    parser.add_argument(
        "--delete-branch-on-cleanup",
        action="store_true",
        help="When used with --cleanup, also delete the per-country git branch",
    )
    args = parser.parse_args()

    repo = DEFAULT_REPO_ROOT
    worktrees_root = DEFAULT_WORKTREES_ROOT

    if not (repo / ".git").exists():
        print(f"Not a git repository: {repo}", file=sys.stderr)
        return 2

    worktrees_root.mkdir(parents=True, exist_ok=True)

    countries = [sanitize_country(c) for c in args.countries.split(",") if c.strip()]
    if not countries:
        print("No valid countries provided.", file=sys.stderr)
        return 2

    stamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    submitted: list[dict[str, str]] = []

    for country in countries:
        country_worktree = worktrees_root / country
        reuse_existing = country_worktree.exists() and any(country_worktree.iterdir())
        branch_name = "reused-existing-worktree"

        try:
            if reuse_existing:
                print(f"[{country}] Reusing existing worktree at {country_worktree}")
            else:
                branch_name = create_fresh_worktree(
                    repo=repo,
                    country_worktree=country_worktree,
                    country=country,
                    base_branch=args.base_branch,
                    stamp=stamp,
                )

            print(f"[{country}] Generating config override")
            cfg_path = create_country_config(country_worktree, repo, country)

            print(f"[{country}] Submitting run job")
            run_jobid = submit_country_job(
                worktree_dir=country_worktree,
                runner_relpath=args.runner,
                country=country,
                account=args.account,
            )
        except Exception as first_error:
            if not reuse_existing:
                raise
            print(f"[{country}] Reused worktree failed ({first_error}); recreating from scratch and retrying once")
            force_remove_country_worktree(repo, worktrees_root, country_worktree, country)
            country_worktree.mkdir(parents=True, exist_ok=True)
            branch_name = create_fresh_worktree(
                repo=repo,
                country_worktree=country_worktree,
                country=country,
                base_branch=args.base_branch,
                stamp=stamp,
            )
            print(f"[{country}] Regenerating config override after recreation")
            cfg_path = create_country_config(country_worktree, repo, country)
            print(f"[{country}] Re-submitting run job")
            run_jobid = submit_country_job(
                worktree_dir=country_worktree,
                runner_relpath=args.runner,
                country=country,
                account=args.account,
            )
        item = {
            "country": country,
            "branch": branch_name,
            "worktree": str(country_worktree),
            "config": str(cfg_path),
            "run_jobid": run_jobid,
        }

        if args.cleanup:
            print(f"[{country}] Submitting cleanup job (after run job {run_jobid})")
            cleanup_jobid = submit_cleanup_job(
                repo=repo,
                worktree_dir=country_worktree,
                branch_name=branch_name,
                country=country,
                dependency_jobid=run_jobid,
                account=args.account,
                delete_branch=args.delete_branch_on_cleanup,
            )
            item["cleanup_jobid"] = cleanup_jobid

        submitted.append(item)

    print("\nSubmission summary")
    for item in submitted:
        cleanup_part = f", cleanup_job={item['cleanup_jobid']}" if "cleanup_jobid" in item else ""
        print(
            f"- {item['country']}: run_job={item['run_jobid']}{cleanup_part}, "
            f"worktree={item['worktree']}, config={item['config']}, branch={item['branch']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
