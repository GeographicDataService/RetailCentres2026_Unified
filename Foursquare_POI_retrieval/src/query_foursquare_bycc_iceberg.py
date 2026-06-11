from argparse import ArgumentParser
from pathlib import Path
import duckdb
import geopandas as gpd
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Snapshot the published UK retail-centre boundaries were built from:
# Iceberg snapshot 5561305087318422558 (2025-10-14) of places.datasets.places_os,
# = 4,168,961 GB POIs. places_os is updated ~monthly, so an unpinned query drifts to
# whatever the latest release is; pin to a snapshot for reproducibility. Pass
# --snapshot latest to deliberately pull the newest release.
OCT2025_SNAPSHOT = "5561305087318422558"

# Set up argument parser
parser = ArgumentParser(description="Process and filter data by country code from Foursquare ICEBERG.")
parser.add_argument("--countrycode", type=str, required=True, help="ISO country code to filter by (e.g., 'US', 'UK').")
parser.add_argument("--filename", type=str, required=True, help="Output file name without extension.")
parser.add_argument("--snapshot", type=str, default=OCT2025_SNAPSHOT,
                    help="Iceberg snapshot id to pin (default: the 2025-10-14 snapshot). "
                         "Pass 'latest' to read the newest release.")
args = parser.parse_args()

# Iceberg time-travel clause: pin to a snapshot unless 'latest' was requested
snapshot_clause = "" if args.snapshot.lower() == "latest" else f"AT (VERSION => {args.snapshot})"

# Set up directories
filename = Path(args.filename)
raw_dir = Path("data/raw")
processed_dir = Path("data/processed")

raw_dir.mkdir(parents=True, exist_ok=True)
processed_dir.mkdir(parents=True, exist_ok=True)

# Load Foursquare ICEBERG token from environment
ICEBERG_TOKEN = os.getenv("FOURSQUARE_ICEBERG_TOKEN")
if not ICEBERG_TOKEN:
    raise ValueError("FOURSQUARE_ICEBERG_TOKEN not found in environment variables. Please check your .env file.")

# Query to filter data and write output
query = f"""
-- adapted from https://github.com/OvertureMaps/data/blob/main/duckdb_queries/places.sql
-- Accessing Foursquare data via ICEBERG
INSTALL httpfs;
INSTALL spatial;
INSTALL iceberg;

LOAD httpfs;
LOAD spatial;
LOAD iceberg;

CREATE SECRET iceberg_secret (
    TYPE ICEBERG,
    TOKEN "{ICEBERG_TOKEN}"
);


ATTACH 'places' AS places (
    TYPE iceberg,
    SECRET iceberg_secret,
    ENDPOINT 'https://catalog.h3-hub.foursquare.com/iceberg'
);

COPY (
    SELECT
        fsq_place_id,
        name,
        latitude,
        longitude,
        address,
        locality,
        region,
        postcode,
        admin_region,
        post_town,
        po_box,
        country,
        date_created,
        date_refreshed,
        date_closed,
        tel,
        website,
        email,
        facebook_id,
        instagram,
        twitter,
        CAST(fsq_category_ids AS JSON) AS fsq_category_ids,
        CAST(fsq_category_labels AS JSON) AS fsq_category_labels,
        CAST(unresolved_flags AS JSON) AS unresolved_flags,
    FROM
        places.datasets.places_os {snapshot_clause}
    WHERE
        country = '{args.countrycode}' -- Filter by country code
        AND latitude IS NOT NULL
        AND longitude IS NOT NULL
) TO 'data/raw/{filename}.gpkg'
WITH (FORMAT GDAL, DRIVER 'GPKG'); -- Export to GeoPackage

"""

duckdb.query(query)

# # # Load the exported GeoPackage and set the CRS to EPSG:4326 (WGS 84)
# places = gpd.read_file(f"data/raw/{filename}.gpkg")
# #print crs
# print(places.crs)
# # Set CRS to EPSG:4326 (WGS 84)
# places = places.set_crs("EPSG:4326", allow_override=True)

# # Optionally, save the updated GeoPackage with the CRS set
# places.to_file(f"data/raw/{filename}.gpkg", driver="GPKG")

# Clean up temporary files if they exist
rtree_file = Path(f"data/raw/{filename}.gpkg.tmp_rtree_{filename}.db")
if rtree_file.exists():
    rtree_file.unlink()

print(f"Data successfully exported to 'data/raw/{filename}.gpkg' with CRS set to EPSG:4326")
