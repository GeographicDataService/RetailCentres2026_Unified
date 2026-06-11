import ast
import json
import os
from argparse import ArgumentParser
from collections.abc import Iterable
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
from dotenv import load_dotenv
from tqdm import tqdm  # Import tqdm for progress bars

# Set up progress bars globally (optional, if you want to disable it in some places)
tqdm.pandas()


def load_categories() -> pd.DataFrame:
    """Fetch the Foursquare category taxonomy from the ICEBERG catalog.

    Replaces the old `s3://fsq-os-places-us-east-1/.../categories/parquet` path,
    which was removed when Foursquare retired the S3 open release.
    """
    load_dotenv()
    token = os.getenv("FOURSQUARE_ICEBERG_TOKEN")
    if not token:
        raise ValueError("FOURSQUARE_ICEBERG_TOKEN not found in environment. Check your .env file.")
    con = duckdb.connect()
    con.execute("INSTALL httpfs; INSTALL iceberg; LOAD httpfs; LOAD iceberg;")
    con.execute(f"CREATE SECRET iceberg_secret (TYPE ICEBERG, TOKEN '{token}');")
    con.execute(
        "ATTACH 'places' AS places (TYPE iceberg, SECRET iceberg_secret, "
        "ENDPOINT 'https://catalog.h3-hub.foursquare.com/iceberg');"
    )
    return con.execute("SELECT * FROM places.datasets.categories_os").df()

parser = ArgumentParser()
parser.add_argument("--filename", type=str, required=True)

args = parser.parse_args()

filename = Path(args.filename)


def add_geometry(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    # Rename lat and lon
    df = df.rename(columns={"latitude": "lat", "longitude": "lng"})

    #create geometry column
    df["geometry"] = gpd.points_from_xy(df["lng"], df["lat"])
    # Set the GeoDataFrame's coordinate reference system (CRS) to EPSG:4326
    df = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:4326")
    # Note: precomputed h3_1..h3_11 columns are intentionally not added here.
    # Downstream (Boundaries) recomputes h3_11 itself via h3.latlng_to_cell
    # (h3 v4), so the old h3pandas v3 geo_to_h3 step was removed to keep this
    # pipeline compatible with the repo-wide pinned h3==4.2.2.
    return df


def add_list_cols(df: gpd.GeoDataFrame, cols: list[str]) -> gpd.GeoDataFrame:
    # Add list columns with progress bar
    for col in tqdm(cols, desc="Adding list columns", unit="column"):
        df[col] = df[col].progress_apply(
            lambda x: [] if isinstance(x, (float, type(None))) else ast.literal_eval(x)
        )
    return df


def remove_list_cols(df: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    list_cols = df.apply(lambda x: any(isinstance(i, list) for i in x))
    for col in tqdm(list_cols[list_cols].index, desc="Removing list columns", unit="column"):
        df[col] = df[col].astype(str)
    return df


if __name__ == "__main__":
    # Read the GeoPackage file
    print("Reading the GeoPackage file...")
    places = gpd.read_file(f"./data/raw/{filename}.gpkg")
    print(f"Data loaded from './data/raw/{filename}.gpkg'")
    # Apply the functions with progress bars
    places = add_geometry(places)
    places = add_list_cols(places, ["fsq_category_ids", "fsq_category_labels", "unresolved_flags"])

    # Exploding the 'fsq_category_ids' column
    places_exploded = places.explode('fsq_category_ids').reset_index(drop=True)
    # Rename column to sing
    places_exploded = places_exploded.rename(columns={'fsq_category_ids': 'fsq_category_id'})    

    #load the cat data from the ICEBERG catalog
    cats = load_categories()
    #join the two dataframes on category_id
    places_exploded = places_exploded.merge(cats, left_on='fsq_category_id', right_on='category_id', how='left')

    # Save the processed data to parquet file.
    # Write geometry as plain WKB bytes (not geopandas' geoarrow extension type, whose
    # BinaryView encoding cannot be read by polars, which Boundaries uses to load this file).
    out = pd.DataFrame(places_exploded.drop(columns="geometry"))
    out["geometry"] = places_exploded.geometry.to_wkb()
    out.to_parquet(f"./data/processed/{filename}.parquet")
    print(f"Processing complete. Data saved to './data/processed/{filename}.parquet'")
