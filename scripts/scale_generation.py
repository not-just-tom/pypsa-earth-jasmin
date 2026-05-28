#!/usr/bin/env python3
"""Scale solved generation by monthly observed totals.

This script applies month-by-month scale factors to ``n.generators_t.p`` for an
explicit set of carriers. It is designed for external calibration workflows
where the observed data are trusted at country-month granularity while the
model's intramonth temporal profile and spatial distribution are preserved.

Expected observed CSV formats:

1. Whole-network totals:

   datetime,value
   2023-01-31,1234.0
   2023-02-28,1175.0

2. Country totals:

   datetime,country,value
   2023-01-31,NG,1234.0
   2023-02-28,NG,1175.0

Multiple rows per month are allowed; values are aggregated to monthly totals.
"""

import argparse
import logging
import os
import sys

import pandas as pd
import pypsa


LOGGER = logging.getLogger(__name__)


def _parse_carrier_list(raw_value):
    if raw_value is None:
        return None
    items = [item.strip() for item in raw_value.split(",")]
    carriers = [item for item in items if item]
    return carriers or None


def load_observed_data(path, datetime_col="datetime", value_col=None, country_col="country"):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Observed CSV {path} not found")

    df = pd.read_csv(path)
    if datetime_col not in df.columns:
        raise ValueError(f"Observed CSV {path} must contain a `{datetime_col}` column")

    df = df.copy()
    df[datetime_col] = pd.to_datetime(df[datetime_col])

    if value_col is None:
        excluded = {datetime_col}
        if country_col in df.columns:
            excluded.add(country_col)
        candidates = [col for col in df.columns if col not in excluded]
        if not candidates:
            raise ValueError(
                f"Observed CSV {path} must contain a value column in addition to `{datetime_col}`"
            )
        value_col = candidates[0]
    elif value_col not in df.columns:
        raise ValueError(f"Observed CSV {path} does not contain value column `{value_col}`")

    out = pd.DataFrame(index=pd.DatetimeIndex(df[datetime_col]))
    out["value"] = pd.to_numeric(df[value_col], errors="coerce")
    if country_col in df.columns:
        out["country"] = df[country_col].astype(str).str.strip()

    out = out.dropna(subset=["value"])
    return out.sort_index()


def aggregate_monthly(series):
    if series.empty:
        return pd.Series(dtype=float)
    return series.groupby(series.index.to_period("M")).sum().sort_index()


def compute_monthly_factors(
    model_series,
    obs_series,
    factor_floor=None,
    factor_cap=None,
):
    model_month = aggregate_monthly(model_series)
    obs_month = aggregate_monthly(obs_series)
    idx = model_month.index.union(obs_month.index)
    model_month = model_month.reindex(idx).fillna(0.0)
    obs_month = obs_month.reindex(idx)

    factors = pd.Series(index=idx, dtype=float)
    tiny = 1e-9
    for month in idx:
        model_value = model_month.at[month]
        obs_value = obs_month.at[month]
        if pd.isna(obs_value):
            factors.at[month] = 1.0
            continue
        if model_value == 0 and obs_value == 0:
            factor = 1.0
        elif model_value == 0 and obs_value > 0:
            LOGGER.warning(
                "Model production is zero for %s but observed > 0 (%.3f)",
                month,
                obs_value,
            )
            factor = obs_value / max(model_value, tiny)
        else:
            factor = obs_value / model_value

        if factor_floor is not None:
            factor = max(factor, factor_floor)
        if factor_cap is not None:
            factor = min(factor, factor_cap)
        factors.at[month] = factor
    return factors


def build_factor_by_snapshot(snapshots, monthly_factors):
    snap_periods = pd.DatetimeIndex(snapshots).to_period("M")
    factor_by_snap = pd.Series(1.0, index=snapshots, dtype=float)
    for snapshot, month in zip(snapshots, snap_periods):
        if month in monthly_factors.index:
            factor_by_snap.at[snapshot] = monthly_factors.at[month]
    return factor_by_snap


def get_generator_country(n):
    if "country" not in n.buses.columns:
        raise ValueError("Network buses do not contain a `country` column")
    return n.generators.bus.map(n.buses.country)


def select_generators(n, include_carriers=None, exclude_carriers=None, country=None):
    carriers = n.generators.carrier.copy()
    mask = pd.Series(True, index=n.generators.index)

    if include_carriers:
        mask &= carriers.isin(include_carriers)
    if exclude_carriers:
        mask &= ~carriers.isin(exclude_carriers)
    if country is not None:
        generator_country = get_generator_country(n)
        mask &= generator_country == country

    return n.generators.index[mask]


def get_model_series(n, generator_names):
    if getattr(n, "generators_t", None) is None or n.generators_t.p.empty:
        raise RuntimeError("Network has no `generators_t.p` dispatch time series to scale")
    if len(generator_names) == 0:
        return pd.Series(0.0, index=n.snapshots)
    return n.generators_t.p.loc[:, generator_names].sum(axis=1)


def apply_monthly_factors(n, generator_names, monthly_factors):
    if len(generator_names) == 0:
        return 0.0, 0.0

    factor_by_snap = build_factor_by_snapshot(n.snapshots, monthly_factors)
    dispatch = n.generators_t.p.loc[:, generator_names]
    total_before = dispatch.sum().sum()
    scaled_dispatch = dispatch.mul(factor_by_snap.values, axis=0)
    n.generators_t.p.loc[:, generator_names] = scaled_dispatch
    total_after = n.generators_t.p.loc[:, generator_names].sum().sum()
    return total_before, total_after


def scale_from_observed(
    n,
    observed,
    include_carriers=None,
    exclude_carriers=None,
    factor_floor=None,
    factor_cap=None,
    country_mode="auto",
    group_name="generation",
):
    total_before = 0.0
    total_after = 0.0

    has_country_data = "country" in observed.columns
    if country_mode == "by-country" and not has_country_data:
        raise ValueError("Country mode `by-country` requires a `country` column in observed data")

    use_country_mode = country_mode == "by-country" or (
        country_mode == "auto" and has_country_data
    )

    if use_country_mode:
        for country, group in observed.groupby("country"):
            generator_names = select_generators(
                n,
                include_carriers=include_carriers,
                exclude_carriers=exclude_carriers,
                country=country,
            )
            if len(generator_names) == 0:
                LOGGER.info(
                    "No generators found for %s in country=%s; skipping",
                    group_name,
                    country,
                )
                continue

            model_series = get_model_series(n, generator_names)
            factors = compute_monthly_factors(
                model_series,
                group["value"],
                factor_floor=factor_floor,
                factor_cap=factor_cap,
            )
            before, after = apply_monthly_factors(n, generator_names, factors)
            total_before += before
            total_after += after
            LOGGER.info(
                "Scaled %s for country=%s: before=%.3f after=%.3f",
                group_name,
                country,
                before,
                after,
            )
    else:
        generator_names = select_generators(
            n,
            include_carriers=include_carriers,
            exclude_carriers=exclude_carriers,
        )
        if len(generator_names) == 0:
            LOGGER.info("No generators found for %s; skipping", group_name)
            return total_before, total_after

        model_series = get_model_series(n, generator_names)
        factors = compute_monthly_factors(
            model_series,
            observed["value"],
            factor_floor=factor_floor,
            factor_cap=factor_cap,
        )
        total_before, total_after = apply_monthly_factors(n, generator_names, factors)
        LOGGER.info(
            "Scaled %s: before=%.3f after=%.3f",
            group_name,
            total_before,
            total_after,
        )

    return total_before, total_after


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--network", required=True, help="Path to network .nc file to load and modify")
    parser.add_argument("--output", required=True, help="Output network path to write adjusted network")
    parser.add_argument("--obs", help="Observed generation CSV")
    parser.add_argument(
        "--include-carriers",
        default=None,
        help="Comma-separated generator carriers to include",
    )
    parser.add_argument(
        "--exclude-carriers",
        default="solar",
        help="Comma-separated generator carriers to exclude",
    )
    parser.add_argument(
        "--group-name",
        default="generation",
        help="Label used in logging for the selected generator group",
    )
    parser.add_argument(
        "--datetime-column",
        default="datetime",
        help="Datetime column name in the observed CSV",
    )
    parser.add_argument(
        "--value-column",
        default=None,
        help="Observed value column name in the observed CSV",
    )
    parser.add_argument(
        "--country-column",
        default="country",
        help="Country column name in the observed CSV",
    )
    parser.add_argument(
        "--country-mode",
        choices=["auto", "whole-network", "by-country"],
        default="auto",
        help="Whether to scale the whole network or split factors by country",
    )
    parser.add_argument(
        "--factor-floor",
        type=float,
        default=None,
        help="Optional lower bound for computed monthly scale factors",
    )
    parser.add_argument(
        "--factor-cap",
        type=float,
        default=None,
        help="Optional upper bound for computed monthly scale factors",
    )
    parser.add_argument("--obs-solar", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--obs-conv", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--carrier-solar", default="solar", help=argparse.SUPPRESS)
    parser.add_argument("--carrier-conv", default="conv", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def run_legacy_mode(n, args):
    if args.obs_solar:
        observed = load_observed_data(args.obs_solar)
        scale_from_observed(
            n,
            observed,
            include_carriers=[args.carrier_solar],
            exclude_carriers=None,
            group_name="solar",
        )

    if args.obs_conv:
        observed = load_observed_data(args.obs_conv)
        scale_from_observed(
            n,
            observed,
            include_carriers=[args.carrier_conv],
            exclude_carriers=None,
            group_name="conventional",
        )


def main(argv=None):
    args = parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not os.path.exists(args.network):
        LOGGER.error("Network file %s not found", args.network)
        sys.exit(1)

    if not args.obs and not (args.obs_solar or args.obs_conv):
        LOGGER.error("Provide either `--obs` or legacy `--obs-solar`/`--obs-conv` inputs")
        sys.exit(1)

    LOGGER.info("Loading network %s", args.network)
    n = pypsa.Network(args.network)

    if args.obs:
        observed = load_observed_data(
            args.obs,
            datetime_col=args.datetime_column,
            value_col=args.value_column,
            country_col=args.country_column,
        )
        include_carriers = _parse_carrier_list(args.include_carriers)
        exclude_carriers = _parse_carrier_list(args.exclude_carriers)
        scale_from_observed(
            n,
            observed,
            include_carriers=include_carriers,
            exclude_carriers=exclude_carriers,
            factor_floor=args.factor_floor,
            factor_cap=args.factor_cap,
            country_mode=args.country_mode,
            group_name=args.group_name,
        )
    else:
        run_legacy_mode(n, args)

    LOGGER.info("Writing adjusted network to %s", args.output)
    n.export_to_netcdf(args.output)


if __name__ == "__main__":
    main()
