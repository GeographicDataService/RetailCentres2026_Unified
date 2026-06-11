from argparse import ArgumentParser
from pathlib import Path
import duckdb
import geopandas as gpd

# conn = duckdb.connect()
# schema_info = conn.execute("DESCRIBE SELECT * FROM read_parquet('data/downloaded/places-00000.zstd.parquet')").fetchall()
# Print the schema information
# for column in schema_info:
#     print(column)

# Set up argument parser
parser = ArgumentParser(description="Process and filter data by country code.")
parser.add_argument("--countrycode", type=str, required=True, help="ISO country code to filter by (e.g., 'US', 'UK').")
parser.add_argument("--filename", type=str, required=True, help="Output file name without extension.")
parser.add_argument("--local", type=bool, default=False, help="Use local data instead of S3.")
args = parser.parse_args()

# Set up directories
filename = Path(args.filename)
raw_dir = Path("data/raw")
processed_dir = Path("data/processed")

raw_dir.mkdir(parents=True, exist_ok=True)
processed_dir.mkdir(parents=True, exist_ok=True)

# Set file location
location = 'data/downloaded/places*.zstd.parquet' if args.local else "s3://fsq-os-places-us-east-1/release/dt=2025-08-07/places/parquet/*"

        # ST_Point(longitude, latitude) AS geometry, -- Create geometry column
# Query to filter data and write output
query = f"""
-- adapted from https://github.com/OvertureMaps/data/blob/main/duckdb_queries/places.sql
-- bounding box from https://epsg.io/27700
INSTALL httpfs;
INSTALL spatial;

LOAD httpfs;
LOAD spatial;

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
        read_parquet('{location}')
    WHERE
        country = '{args.countrycode}' -- Filter by country code
        AND latitude IS NOT NULL --creates inval
        AND longitude IS NOT NULL
) TO 'data/raw/{filename}.gpkg'
WITH (FORMAT GDAL, DRIVER 'GPKG'); -- Specify the spatial column

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
