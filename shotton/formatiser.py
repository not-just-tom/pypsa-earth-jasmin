import pandas as pd
import pycountry


def iso3_to_iso2(iso3):
    try:
        return pycountry.countries.get(alpha_3=iso3).alpha_2
    except:
        return None

def ember_to_custom(df):
    # ----------------------------
    #       Data comes in monthly, so here we divide to
    #       daily, and convert to ISO codes
    # ----------------------------
    
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m")
    df["days_in_month"] = df["date"].dt.days_in_month
    df["daily_demand_twh"] = df["demand_twh"] *1000/ df["days_in_month"] # check the 1000 factor here (TWh -> GWh ?)


    
    rows = []

    for _, row in df.iterrows():
        # Create a date range for the whole month (daily at midnight)
        day_range = pd.date_range(
            start=row["date"],
            end=row["date"] + pd.offsets.MonthEnd(0),
            freq="D"
        )

        for day in day_range:
            rows.append({
                "region_code": iso3_to_iso2(row["entity_code"]),   # ISO2
                "time": day.strftime("%Y-%m-%d 00:00:00"),
                "region_name": row["entity"],
                "Electricity demand": row["daily_demand_twh"]
            })

    daily_df = pd.DataFrame(rows)

    # 
    # Write semicolon-separated CSV
    daily_df.to_csv(
        "converted_daily_electricity_demand.csv",
        sep=";",
        index=False
    )

    print("Done! Output written to converted_daily_electricity_demand.csv")
    return daily_df
