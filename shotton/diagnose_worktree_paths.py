#!/usr/bin/env python3
"""Diagnose missing demand input files for a country worktree run.

This script inspects a worktree config, computes expected GEGIS demand paths,
checks whether files exist in the worktree, and verifies whether those paths
are present in the databundle output declarations.

Example:
  python shotton/diagnose_worktree_paths.py \
    --worktree /gws/ssde/j25b/gbov/PyPSA-Earth/multi-runs/FR
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml


CONTINENTS = ["Africa", "Asia", "Europe", "NorthAmerica", "SouthAmerica", "Oceania"]


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = yaml.safe_load(f)
    return data or {}


def get_config(worktree: Path) -> tuple[dict[str, Any], Path]:
    # Snakefile loads config.default first and config.yaml last.
    cfg_default = worktree / "config.default.yaml"
    cfg_runtime = worktree / "config.yaml"

    if not cfg_default.exists():
        raise FileNotFoundError(f"Missing {cfg_default}")

    merged = read_yaml(cfg_default)
    source = cfg_default
    if cfg_runtime.exists():
        override = read_yaml(cfg_runtime)
        merged.update(override)
        source = cfg_runtime
    return merged, source


def get_regions_definition(repo_root: Path) -> dict[str, Any]:
    p = repo_root / "configs" / "regions_definition_config.yaml"
    if not p.exists():
        raise FileNotFoundError(f"Missing {p}")
    return read_yaml(p)


def resolve_gegis_regions(countries: list[str], regions_def: dict[str, Any]) -> list[str]:
    gegis = regions_def.get("gegis_regions", {}) or {}
    world_iso = regions_def.get("world_iso", {}) or {}

    regions: list[str] = []
    for group in (gegis, world_iso):
        for region_name, mapping in group.items():
            iso_map = mapping or {}
            if set(countries).intersection(set(iso_map.keys())):
                if region_name not in regions:
                    regions.append(region_name)
    return regions


def declared_bundle_outputs(config: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    databundles = config.get("databundles")
    if isinstance(databundles, str):
        path = repo_root / databundles
        if not path.exists():
            raise FileNotFoundError(f"Configured databundle file not found: {path}")
        loaded = read_yaml(path)
        return loaded.get("databundles", {}) or {}
    if isinstance(databundles, dict):
        return databundles
    return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose worktree demand input paths")
    parser.add_argument("--worktree", required=True, help="Country worktree path")
    parser.add_argument(
        "--repo-root",
        default="/gws/ssde/j25b/gbov/PyPSA-Earth/pypsa-earth-jasmin",
        help="Main repository root",
    )
    parser.add_argument(
        "--tail-logs",
        action="store_true",
        help="Print tail hints for relevant log files",
    )
    args = parser.parse_args()

    worktree = Path(args.worktree).resolve()
    repo_root = Path(args.repo_root).resolve()

    config, source = get_config(worktree)
    countries = config.get("countries", []) or []
    load_options = config.get("load_options", {}) or {}
    ssp = load_options.get("ssp")
    prediction_year = load_options.get("prediction_year")
    weather_year = load_options.get("weather_year")

    print(f"Worktree: {worktree}")
    print(f"Config source precedence ends at: {source}")
    print(f"Countries: {countries}")
    print(
        "Load options: "
        f"ssp={ssp}, prediction_year={prediction_year}, weather_year={weather_year}"
    )
    print(
        "Enable flags: "
        f"retrieve_databundle={config.get('enable', {}).get('retrieve_databundle')}, "
        f"build_cutout={config.get('enable', {}).get('build_cutout')}"
    )

    regions_def = get_regions_definition(repo_root)
    regions = resolve_gegis_regions(countries, regions_def)
    print(f"GEGIS regions resolved from countries: {regions}")

    load_dir = Path("data") / str(ssp) / str(prediction_year) / f"era5_{weather_year}"
    print(f"Expected demand directory: {load_dir}")

    missing: list[str] = []
    print("\nDemand input checks:")
    for region in regions:
        nc_rel = load_dir / f"{region}.nc"
        csv_rel = load_dir / f"{region}.csv"
        nc_abs = worktree / nc_rel
        csv_abs = worktree / csv_rel
        if nc_abs.exists():
            print(f"  OK  {nc_rel}")
        elif csv_abs.exists():
            print(f"  OK  {csv_rel}")
        else:
            print(f"  MISSING  {nc_rel} (and .csv alternative)")
            missing.append(str(nc_rel))

    bundles = declared_bundle_outputs(config, repo_root)
    all_outputs: set[str] = set()
    for bname, bcfg in bundles.items():
        for out in (bcfg or {}).get("output", []) or []:
            all_outputs.add(str(out))

    print("\nDatabundle declaration checks:")
    if not bundles:
        print("  No databundle definitions found in merged config.")
    else:
        for rel in missing:
            if rel in all_outputs:
                print(f"  DECLARED  {rel}")
            else:
                print(f"  NOT_DECLARED  {rel}")

    # Extra directory view for quick diagnosis
    demand_abs = worktree / load_dir
    print("\nDirectory state:")
    if demand_abs.exists():
        files = sorted([p.name for p in demand_abs.iterdir() if p.is_file()])
        print(f"  Exists: {demand_abs}")
        preview = ", ".join(files[:12])
        if len(files) > 12:
            preview += ", ..."
        print(f"  Files: {preview if preview else '(none)'}")
    else:
        print(f"  Missing directory: {demand_abs}")

    if args.tail_logs:
        print("\nRelevant log paths to inspect:")
        print(f"  {worktree / 'logs' / 'retrieve_databundle.log'}")
        print(f"  {worktree / 'logs' / 'build_demand_profiles.log'}")

    print("\nTip: run Snakemake with verbose diagnostics:")
    print(
        "  snakemake -s Snakefile -j 1 solve_all_networks "
        "--printshellcmds --verbose --reason --show-failed-logs --debug-dag"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
