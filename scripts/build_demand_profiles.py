# -*- coding: utf-8 -*-
# SPDX-FileCopyrightText:  PyPSA-Earth and PyPSA-Eur Authors
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# -*- coding: utf-8 -*-
"""
Creates electric demand profile csv.

Relevant Settings
-----------------

.. code:: yaml

    load:
        scale:
        ssp:
        weather_year:
        prediction_year:
        region_load:

Inputs
------

- ``networks/base.nc``: confer :ref:`base`, a base PyPSA Network
- ``resources/bus_regions/regions_onshore.geojson``: confer :mod:`build_bus_regions`
- ``load_data_paths``: paths to load profiles, e.g. hourly country load profiles produced by GEGIS
- ``resources/shapes/gadm_shapes.geojson``: confer :ref:`shapes`, file containing the gadm shapes

Outputs
-------

- ``resources/demand_profiles.csv``: the content of the file is the electric demand profile associated to each bus. The file has the snapshots as rows and the buses of the network as columns.

Description
-----------

The rule :mod:`build_demand` creates load demand profiles in correspondence of the buses of the network.
It creates the load paths for GEGIS outputs by combining the input parameters of the countries, weather year, prediction year, and SSP scenario.
Then with a function that takes in the PyPSA network "base.nc", region and gadm shape data, the countries of interest, a scale factor, and the snapshots,
it returns a csv file called "demand_profiles.csv", that allocates the load to the buses of the network according to GDP and population.
"""
import os
import os.path
from itertools import product

import geopandas as gpd
import numpy as np
import pandas as pd
import pypsa
import scipy.sparse as sparse
import xarray as xr
from _helpers import (
    BASE_DIR,
    configure_logging,
    create_logger,
    read_csv_nafix,
    read_osm_config,
)
from shapely.prepared import prep
from shapely.validation import make_valid

logger = create_logger(__name__)


def normed(s):
    if s.sum() == 0:
        return s
    return s / s.sum()


def get_gegis_regions(countries):
    """
    Get the GEGIS region from the config file.

    Parameters
    ----------
    region : str
        The region of the bus

    Returns
    -------
    str
        The GEGIS region
    """
    gegis_dict, world_iso = read_osm_config("gegis_regions", "world_iso")

    regions = []

    for d_region in [gegis_dict, world_iso]:
        for key, value in d_region.items():
            # ignore if the key is already in the regions list
            if key not in regions:
                # if a country is in the regions values, then load it
                cintersect = set(countries).intersection(set(value.keys()))
                if cintersect:
                    regions.append(key)
    return regions


def get_load_paths_gegis(ssp_parentfolder, config):
    """
    Create load paths for GEGIS outputs.

    The paths are created automatically according to included country,
    weather year, prediction year and ssp scenario

    Example
    -------
    ["/data/ssp2-2.6/2030/era5_2013/Africa.nc", "/data/ssp2-2.6/2030/era5_2013/Africa.nc"]
    """
    countries = config.get("countries")
    region_load = get_gegis_regions(countries)
    weather_year = config.get("load_options")["weather_year"]
    prediction_year = config.get("load_options")["prediction_year"]
    ssp = config.get("load_options")["ssp"]

    scenario_path = os.path.join(ssp_parentfolder, ssp)

    load_paths = []
    load_dir = os.path.join(
        ssp_parentfolder,
        str(ssp),
        str(prediction_year),
        "era5_" + str(weather_year),
    )

    file_names = []
    for continent in region_load:
        sel_ext = ".nc"
        for ext in [".nc", ".csv"]:
            load_path = os.path.join(BASE_DIR, str(load_dir), str(continent) + str(ext))
            if os.path.exists(load_path):
                sel_ext = ext
                break
        file_name = str(continent) + str(sel_ext)
        load_path = os.path.join(str(load_dir), file_name)
        load_paths.append(load_path)
        file_names.append(file_name)

    logger.info(
        f"Demand data folder: {load_dir}, load path is {load_paths}.\n"
        + f"Expected files: "
        + "; ".join(file_names)
    )

    return load_paths


def shapes_to_shapes(orig, dest):
    """
    Adopted from vresutils.transfer.Shapes2Shapes()
    """
    orig_prepped = list(map(prep, orig))
    transfer = sparse.lil_matrix((len(dest), len(orig)), dtype=float)

    for i, j in product(range(len(dest)), range(len(orig))):
        if orig_prepped[j].intersects(dest[i]):
            area = orig[j].intersection(dest[i]).area
            transfer[i, j] = area / dest[i].area

    return transfer


def load_demand_csv(path):
    df = read_csv_nafix(path, sep=";")
    df.time = pd.to_datetime(df.time, format="%Y-%m-%d %H:%M:%S")
    load_regions = {c: n for c, n in zip(df.region_code, df.region_name)}

    gegis_load = df.set_index(["region_code", "time"]).to_xarray()
    gegis_load = gegis_load.assign_coords(
        {
            "region_name": (
                "region_code",
                [name for (code, name) in load_regions.items()],
            )
        }
    )
    return gegis_load


def build_demand_profiles(
    n,
    load_paths,
    regions,
    admin_shapes,
    countries,
    scale,
    start_date,
    end_date,
    out_path,
):
    """
    Create csv file of electric demand time series.

    Parameters
    ----------
    n : pypsa network
    load_paths: paths of the load files
    regions : .geojson
        Contains bus_id of low voltage substations and
        bus region shapes (voronoi cells)
    admin_shapes : .geojson
        contains subregional gdp, population and shape data
    countries : list
        List of countries that is config input
    scale : float
        The scale factor is multiplied with the load (1.3 = 30% more load)
    start_date: parameter
        The start_date is the first hour of the first day of the snapshots
    end_date: parameter
        The end_date is the last hour of the last day of the snapshots

    Returns
    -------
    demand_profiles.csv : csv file containing the electric demand time series
    """
    substation_lv_i = n.buses.index[n.buses["substation_lv"]]
    regions = gpd.read_file(regions).set_index("name").reindex(substation_lv_i)
    load_paths = load_paths

    gegis_load_list = []

    for path in load_paths:
        if str(path).endswith(".csv"):
            gegis_load_xr = load_demand_csv(path)
        else:
            # Merge load .nc files: https://stackoverflow.com/questions/47226429/join-merge-multiple-netcdf-files-using-xarray
            gegis_load_xr = xr.open_mfdataset(path, combine="nested")
        gegis_load_list.append(gegis_load_xr)

    logger.info(f"Merging demand data from paths {load_paths} into the load data frame")
    gegis_load = xr.merge(gegis_load_list)
    gegis_load = gegis_load.to_dataframe().reset_index().set_index("time")

    # filter load for analysed countries
    gegis_load = gegis_load.loc[gegis_load.region_code.isin(countries)]

    if isinstance(scale, dict):
        logger.info(f"Using custom scaling factor for load data.")
        DEFAULT_VAL = scale.get("DEFAULT", 1.0)
        for country in countries:
            scale.setdefault(country, DEFAULT_VAL)

        for country, scale_country in scale.items():
            gegis_load.loc[
                gegis_load.region_code == country, "Electricity demand"
            ] *= scale_country

    elif isinstance(scale, (int, float)):
        logger.info(f"Load data scaled with scaling factor {scale}.")

        gegis_load["Electricity demand"] *= scale

    elif scale == "yes": # shotton: addition for triggering the scaling option within the rule I placed.
        logger.info(f"Scaling data to the ember statistics found in shotton/data/monthly_ember.csv")
        ember = pd.read_csv(
            "shotton/data/monthly_ember.csv",
            parse_dates=["Date"],
            dayfirst=True,
        )

        ember = ember[
            (ember["Category"] == "Electricity demand")
            & (ember["Subcategory"] == "Demand")
            & (ember["Variable"] == "Demand")
            & (ember["Unit"] == "TWh")
        ].copy()

        ember["month"] = ember["Date"].dt.to_period("M")

        for country in countries:

            ember_country = ember[
                ember["ISO 3 code"] == country
            ].copy()

            if ember_country.empty:
                raise ValueError(
                    f"No Ember electricity demand data found for {country}"
                )

            # detect annual-only data
            if ember_country["month"].nunique() <= 1:

                annual_total = ember_country["Value"].sum()

                logger.warning(
                    f"{country}: only annual Ember demand found. "
                    f"Distributing {annual_total:.2f} TWh equally across 12 months."
                )

                year = ember_country["Date"].dt.year.iloc[0]

                monthly_targets = pd.Series(
                    annual_total / 12.0,
                    index=pd.period_range(
                        f"{year}-01",
                        f"{year}-12",
                        freq="M",
                    ),
                )

            else:

                monthly_targets = (
                    ember_country.groupby("month")["Value"]
                    .sum()
                )

            country_mask = gegis_load.region_code == country

            country_load = gegis_load.loc[
                country_mask,
                "Electricity demand",
            ]

            months = country_load.index.to_period("M")

            for month, ember_total in monthly_targets.items():

                month_mask = country_mask & (
                    gegis_load.index.to_period("M") == month
                )

                gegis_total = gegis_load.loc[
                    month_mask,
                    "Electricity demand",
                ].sum()

                if gegis_total <= 0:
                    raise ValueError(
                        f"{country} {month}: "
                        f"GEGIS monthly demand is zero."
                    )

                ratio = ember_total / gegis_total

                logger.info(
                    f"{country} {month}: "
                    f"GEGIS={gegis_total:.3f} "
                    f"Ember={ember_total:.3f} "
                    f"ratio={ratio:.3f}"
                )

                gegis_load.loc[
                    month_mask,
                    "Electricity demand",
                ] *= ratio 

                # end of shotton clause

    shapes = gpd.read_file(admin_shapes).set_index("GADM_ID")
    shapes["geometry"] = shapes["geometry"].apply(lambda x: make_valid(x))

    def upsample(cntry, group):
        """
        Distributes load in country according to population and gdp.
        """
        l = gegis_load.loc[gegis_load.region_code == cntry]["Electricity demand"]
        if len(group) == 1:
            return pd.DataFrame({group.index[0]: l})
        else:
            shapes_cntry = shapes.loc[shapes.country == cntry]
            transfer = shapes_to_shapes(group, shapes_cntry.geometry).T.tocsr()
            gdp_n = pd.Series(
                transfer.dot(shapes_cntry["gdp"].fillna(1.0).values), index=group.index
            )
            pop_n = pd.Series(
                transfer.dot(shapes_cntry["pop"].fillna(1.0).values), index=group.index
            )

            # relative factors 0.6 and 0.4 have been determined from a linear
            # regression on the country to EU continent load data
            # (refer to vresutils.load._upsampling_weights)
            # TODO: require adjustment for Africa
            factors = normed(0.6 * normed(gdp_n) + 0.4 * normed(pop_n))
            if factors.sum() == 0:
                logger.warning(
                    f"Upsampling factors for {cntry} are all zero, returning uniform distribution across {len(factors)} shapes."
                )
                factors = pd.Series(
                    np.ones(len(factors)) / len(factors), index=factors.index
                )
            return pd.DataFrame(
                factors.values * l.values[:, np.newaxis],
                index=l.index,
                columns=factors.index,
            )

    demand_profiles = pd.concat(
        [
            upsample(cntry, group)
            for cntry, group in regions.geometry.groupby(regions.country)
        ],
        axis=1,
    )

    start_date = pd.to_datetime(start_date)
    end_date = pd.to_datetime(end_date) - pd.Timedelta(hours=1)
    demand_profiles = demand_profiles.loc[start_date:end_date]

    # === shotton === #
    
    from pathlib import Path
    import re
    countries = snakemake.params.countries  # list from config
    base = Path('power_generation_hourly_by_country')
    for country in countries:
        country_dir = base / country
        files = sorted(country_dir.glob('power_generation_2023_facility_*.csv')) # hardcoded 2023 year
        facility_ids = [re.search(r'_facility_(\d+)\.csv$', f.name).group(1) for f in files]

        # im keep with in in other loop just to preserve a multi-country run
        for facility in facility_ids:
            facility_csv = pd.read_csv(country_dir / f'power_generation_2023_facility_{facility}.csv')
            lat_col = next((c for c in facility_csv.columns if c.lower()=='grid_latitude'), None)
            lon_col = next((c for c in facility_csv.columns if c.lower()=='grid_longitude'), None)
            if lat_col is None or lon_col is None:
                logger.error(f"Facility {facility} has no lat/lon columns; skipping")
                continue

            # just take first row since per-facility files
            lat = facility_csv[lat_col].iloc[0]
            lon = facility_csv[lon_col].iloc[0]

            
            pt = gpd.GeoDataFrame(
                {"facility": [facility]},
                geometry=gpd.points_from_xy([lon], [lat]),
                crs="EPSG:4326",
            )

            if pt.crs != regions.crs:
                pt = pt.to_crs(regions.crs)

            # use spatial nearest join to find the bus
            try:
                joined = gpd.sjoin_nearest(pt, regions["geometry"].to_frame(), how="left")
                bus_id = joined["index_right"].iloc[0]
            except Exception:
                # fallback: compute min-distance to region centroids
                centroids = regions.geometry.centroid
                dists = centroids.distance(pt.geometry.iloc[0])
                bus_id = dists.idxmin()

            # now we have the bus remove the additional solar from the relevant column 
            # load facility time series using known columns and subtract from demand_profiles
            # facility CSV columns are known: 'datetime' and 'power_POA_cln'- check this last one. 
            time_col = 'datetime'
            gen_col = 'power_POA_cln'

            if time_col not in facility_csv.columns or gen_col not in facility_csv.columns:
                logger.warning(f"Facility {facility}: expected columns '{time_col}' and '{gen_col}' not found; skipping.")
                continue

            try:
                facility_csv[time_col] = pd.to_datetime(facility_csv[time_col])
            except Exception:
                logger.warning(f"Facility {facility}: failed to parse '{time_col}'; skipping.")
                continue

            # adjusted time is 30 minutes before facility timestamp; floor to hour
            facility_csv['adj_time'] = facility_csv[time_col] - pd.Timedelta(minutes=30)
            facility_csv['adj_hour'] = facility_csv['adj_time'].dt.floor('H')

            # aggregate generation per adjusted hour
            per_hour = facility_csv.groupby('adj_hour')[gen_col].sum()

            # align to demand_profiles index and subtract from the mapped bus column
            bus_col = bus_id if bus_id in demand_profiles.columns else str(bus_id)
            if bus_col not in demand_profiles.columns:
                logger.warning(f"Mapped bus {bus_id} not present in demand_profiles columns; skipping subtraction for facility {facility}.")
            else:
                per_hour = per_hour.reindex(demand_profiles.index, fill_value=0)
                sub_sum = per_hour.sum()
                demand_profiles[bus_col] = demand_profiles[bus_col].sub(per_hour, fill_value=0)
                negs = (demand_profiles[bus_col] < 0).sum()
                if negs > 0:
                    logger.warning(f"Clipping {negs} negative cells to zero on bus {bus_col} after subtracting facility {facility}.")
                    demand_profiles[bus_col] = demand_profiles[bus_col].clip(lower=0)


 # === shotton end === #

    demand_profiles.to_csv(out_path, header=True)

    logger.info(f"Demand_profiles csv file created for the corresponding snapshots.")


if __name__ == "__main__":
    if "snakemake" not in globals():
        from _helpers import mock_snakemake

        snakemake = mock_snakemake("build_demand_profiles")

    configure_logging(snakemake)

    n = pypsa.Network(snakemake.input.base_network)

    # Snakemake imports:
    regions = snakemake.input.regions
    load_paths = snakemake.input["load"]
    countries = snakemake.params.countries
    admin_shapes = snakemake.input.gadm_shapes
    scale = snakemake.params.load_options.get("scale", 1.0)
    start_date = snakemake.params.snapshots["start"]
    end_date = snakemake.params.snapshots["end"]
    out_path = snakemake.output[0]

    build_demand_profiles(
        n,
        load_paths,
        regions,
        admin_shapes,
        countries,
        'yes', # shotton: triggering the scaling option within the rule I placed. 
        start_date,
        end_date,
        out_path,
    )
