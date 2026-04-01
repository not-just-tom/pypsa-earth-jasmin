#!/usr/bin/env python3
"""Scale modelled generation by monthly country totals from observed data.

This script is intentionally conservative: it applies month-by-month scale
factors to the modelled `n.generators_t.p` time series for a given carrier
(solar, or conventional). It writes a new network file with adjusted
dispatch time series.

Expected observed CSV format: a `datetime` column and a single value column
containing country-level generation in MW. If the CSV has multiple columns,
the first non-datetime column is used.
"""
import argparse
import logging
import os
import sys

import numpy as np
import pandas as pd
import pypsa


def load_observed_series(path):
    if not os.path.exists(path):
        logging.info("Observed file %s not found — skipping", path)
        return None
    df = pd.read_csv(path, parse_dates=["datetime"] )
    if df.shape[1] < 2:
        raise ValueError(f"Observed CSV {path} must contain a datetime and a value column")
    # assume first non-datetime column is the observed value
    val_col = [c for c in df.columns if c.lower() != "datetime"][0]
    s = pd.Series(df[val_col].values, index=pd.DatetimeIndex(df["datetime"]))
    s = s.sort_index()
    return s


def compute_monthly_factors(model_series, obs_series):
    # model_series and obs_series are time-indexed series (hourly/datetime)
    model_month = model_series.resample("M").sum()
    obs_month = obs_series.resample("M").sum()
    # align indices
    idx = obs_month.index.union(model_month.index)
    model_month = model_month.reindex(idx).fillna(0.0)
    obs_month = obs_month.reindex(idx).fillna(0.0)

    factors = pd.Series(index=idx, dtype=float)
    tiny = 1e-9
    for ts in idx:
        m = model_month.at[ts]
        o = obs_month.at[ts]
        if m == 0 and o == 0:
            factors.at[ts] = 1.0
        elif m == 0 and o > 0:
            logging.warning("Model production is zero for %s but observed >0 (%.3f). Using large factor", ts.strftime("%Y-%m"), o)
            factors.at[ts] = o / max(m, tiny)
        else:
            factors.at[ts] = o / m
    return factors


def apply_monthly_factors_to_generators(n, carrier, factors):
    gens = n.generators.index[n.generators.carrier == carrier].tolist()
    if len(gens) == 0:
        logging.info("No generators with carrier=%s found in network — skipping", carrier)
        return 0.0, 0.0

    if getattr(n, "generators_t", None) is None or n.generators_t.p.empty:
        raise RuntimeError("Network has no `generators_t.p` dispatch time series to scale")

    # model total before
    model_total_before = n.generators_t.p.loc[:, gens].sum().sum()

    # build a factor series aligned to snapshots
    # map each snapshot to its month-end timestamp in factors
    snap_month = pd.to_datetime(n.snapshots).to_period("M").to_timestamp("M")
    factor_by_snap = pd.Series(index=n.snapshots, dtype=float)
    for snap, mstamp in zip(n.snapshots, snap_month):
        if mstamp in factors.index:
            factor_by_snap.at[snap] = factors.at[mstamp]
        else:
            factor_by_snap.at[snap] = 1.0

    # multiply dispatch time series in-place (post-processing)
    df = n.generators_t.p.loc[:, gens]
    df_scaled = df.mul(factor_by_snap.values, axis=0)
    n.generators_t.p.loc[:, gens] = df_scaled

    model_total_after = n.generators_t.p.loc[:, gens].sum().sum()
    return model_total_before, model_total_after


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--network", required=True, help="Path to network .nc file to load and modify")
    p.add_argument("--obs-solar", default=None, help="Observed country-level solar CSV (datetime + value)")
    p.add_argument("--obs-conv", default=None, help="Observed country-level conventional generation CSV (datetime + value)")
    p.add_argument("--carrier-solar", default="solar", help="Generator carrier name for solar in the network")
    p.add_argument("--carrier-conv", default="conv", help="Generator carrier name for conventional in the network")
    p.add_argument("--output", required=True, help="Output network path to write adjusted network")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if not os.path.exists(args.network):
        logging.error("Network file %s not found", args.network)
        sys.exit(1)

    logging.info("Loading network %s", args.network)
    n = pypsa.Network(args.network)

    # Solar
    if args.obs_solar:
        s = load_observed_series(args.obs_solar)
        if s is not None:
            # align to hourly snapshots before monthly aggregation
            s = s.sort_index()
            s = s.reindex(n.snapshots).fillna(0.0)
            model_series = n.generators_t.p.loc[:, n.generators.index[n.generators.carrier == args.carrier_solar]].sum(axis=1)
            factors = compute_monthly_factors(model_series, s)
            before, after = apply_monthly_factors_to_generators(n, args.carrier_solar, factors)
            logging.info("Solar scaled: total before=%.3f MW, after=%.3f MW", before, after)

    # Conventional
    if args.obs_conv:
        s2 = load_observed_series(args.obs_conv)
        if s2 is not None:
            s2 = s2.sort_index()
            s2 = s2.reindex(n.snapshots).fillna(0.0)
            model_series2 = n.generators_t.p.loc[:, n.generators.index[n.generators.carrier == args.carrier_conv]].sum(axis=1)
            factors2 = compute_monthly_factors(model_series2, s2)
            before2, after2 = apply_monthly_factors_to_generators(n, args.carrier_conv, factors2)
            logging.info("Conventional scaled: total before=%.3f MW, after=%.3f MW", before2, after2)

    logging.info("Writing adjusted network to %s", args.output)
    n.export_to_netcdf(args.output)


if __name__ == "__main__":
    main()
