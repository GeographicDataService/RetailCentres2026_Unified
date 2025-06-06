import geopandas as gpd
import sys
from pathlib import Path

# Usage: python script.py data/output_files/uk_foursquare_filtered.parquet

# Get the input file from command line
input_file = Path(sys.argv[1])

# Load the data
data = gpd.read_parquet(input_file)

# Prepare output path
output_dir = Path("data/forarcgis")
output_dir.mkdir(parents=True, exist_ok=True)
output_file = output_dir / (input_file.stem + ".gpkg")

# Save to GeoPackage
data.to_file(output_file, driver="GPKG")

print(f"Saved: {output_file}")
