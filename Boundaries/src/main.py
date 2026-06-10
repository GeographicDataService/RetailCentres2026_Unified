import argparse
import polars as pl
import numpy as np
import itertools
import random

from utils import utils as ut
from retail import retailfilter
from retail import foursquare_qualityfilter
from retail import retail_landuse_poi_filter
from retail import detect_retail_parks
from generate_networks import generate_networks
import config

# Command line arguments
parser = argparse.ArgumentParser(description="Generate retail networks from parameter lists.")
parser.add_argument(
    "--run_name",
    type=str,
    required=True,
    help="Name for this run (required)."
)
parser.add_argument(
    "--use_presaved_filters",
    action="store_true",
    help="Use presaved quality filter results (faster). If not set, runs filters from scratch and saves IDs for future use."
)
args = parser.parse_args()

# Set random seed for reproducibility
random.seed(config.RANDOM_SEED)
np.random.seed(config.RANDOM_SEED)

# Define parameter values
run_name = args.run_name
print(f"Run name: {run_name}")
min_retail_in_cell_values = config.PARAM_SWEEP_MIN_RETAIL_IN_CELL
min_retail_in_network_values = config.PARAM_SWEEP_MIN_RETAIL_IN_NETWORK
min_to_fill = config.PARAM_SWEEP_MIN_TO_FILL
split_threshold = config.PARAM_SWEEP_SPLIT_THRESHOLD
merge_adjacent = config.PARAM_SWEEP_MERGE_ADJACENT

# Generate all parameter combinations
param_combinations = itertools.product(
    min_retail_in_cell_values,
    min_retail_in_network_values,
    min_to_fill,
    split_threshold,
    merge_adjacent
)
param_combinations_list = list(param_combinations)
total_combos = len(param_combinations_list)
print(f"Total combinations: {total_combos}")

foursquare = pl.read_parquet(config.FOURSQUARE_PATH)

# Apply quality filters (closed venues, defunct retailers, UK boundary)
if args.use_presaved_filters:
    print(f"Using presaved quality filter results from: {config.FILTER_IDS_PATH}")
    foursquare = foursquare_qualityfilter.load_and_apply_presaved_filters(
        foursquare,
        filter_ids_path=str(config.FILTER_IDS_PATH)
    )
else:
    print("Running quality filters from scratch (will save filter IDs for future use)")
    foursquare = foursquare_qualityfilter.filter_foursquare_quality(
        foursquare,
        save_filter_ids=True,
        filter_ids_path=str(config.FILTER_IDS_PATH)
    )

# Create run directory and save quality-filtered data as geoparquet
run_dir = config.RUNS_DIR / run_name
run_dir.mkdir(parents=True, exist_ok=True)
quality_filtered_gdf = ut.poi_to_geoframe(foursquare)
quality_filtered_gdf.to_parquet(run_dir / "foursquare_quality_filtered.parquet")
print(f"Saved quality-filtered geoparquet: {len(quality_filtered_gdf):,} POIs to {run_dir / 'foursquare_quality_filtered.parquet'}")
del quality_filtered_gdf

# Apply category filters
foursquare = retailfilter.filter_foursquare(foursquare)
(
    foursquare
    .select(pl.col("fsq_category_labels").explode().alias("category"))
    .unique()
    .sort("category")
    .write_csv("data/intermediate/unique_categories.csv")
)

# Add custom taxonomy (high-level category grouping)
CATEGORY_MAP = {
    "Retail": "Retail",
    "Business and Professional Services": "Retail",
    "Dining and Drinking": "Dining and Drinking",
    "Sports and Recreation": "Leisure & Travel",
    "Arts and Entertainment": "Leisure & Travel",
    "Travel and Transportation": "Leisure & Travel",
    "Community and Government": "Community & Health",
    "Health and Medicine": "Community & Health",
}
foursquare = foursquare.with_columns(
    pl.col("level1_category_name").replace(CATEGORY_MAP).alias("retail_type")
)

# Save retail-filtered foursquare data as geoparquet
print(f"Saving filtered POIs as geoparquet to {run_dir / 'foursquare_filtered.parquet'}...")
foursquare_gdf = ut.poi_to_geoframe(foursquare)
foursquare_gdf.to_parquet(run_dir / "foursquare_filtered.parquet")
print(f"  ✓ Saved {len(foursquare_gdf):,} filtered POIs with Point geometries\n")

foursquare = ut.add_h3_11_column(foursquare)
foursquare_cells = ut.agg_to_cells_foursquare(foursquare)

# Convert retail land use polygons to H3 cells (regenerated each run).
# When FILTER_RETAIL_LANDUSE is True the polygons are pruned by POI count;
# otherwise all retail land use polygons are kept.
land_use_cells = retail_landuse_poi_filter.filter_retail_landuse_by_pois(
    foursquare=foursquare,
    min_pois_per_polygon=(
        config.MIN_POIS_PER_LANDUSE_POLYGON if config.FILTER_RETAIL_LANDUSE else None
    ),
    retail_landuse_path=str(config.RETAIL_LANDUSE_POLYGONS_PATH),
    output_h3_path=str(config.RETAIL_LANDUSE_H3_GEO_PATH),
    filtered_polygons_path=str(config.RETAIL_LANDUSE_FILTERED_PATH),
)

combined = ut.create_combined_table(foursquare_cells, land_use_cells)

# Detect retail parks if enabled
retail_parks_path = None
if config.INTEGRATE_RETAIL_PARKS:
    print("\n" + "="*80)
    print("DETECTING RETAIL PARKS")
    print("="*80)

    # Create retail parks output folder inside run directory
    run_dir = config.RUNS_DIR / run_name
    retail_parks_output_dir = run_dir / "retail_parks"
    retail_parks_output_dir.mkdir(parents=True, exist_ok=True)

    # Save filtered POIs for retail park detection
    print("Saving filtered POIs for retail park detection...")
    filtered_poi_path = retail_parks_output_dir / "foursquare_filtered_for_parks.parquet"
    foursquare.write_parquet(filtered_poi_path)

    # Detect retail parks using FILTERED POIs
    retail_parks_polygons = detect_retail_parks.identify_retail_parks(
        retail_landuse_path=str(config.RETAIL_LANDUSE_POLYGONS_PATH),
        foursquare_pois_path=str(filtered_poi_path),
        brands_csv_path=str(config.RETAIL_PARK_BRANDS_PATH),
        min_ratio=config.RETAIL_PARK_MIN_RATIO,
        min_matched_pois=config.RETAIL_PARK_MIN_MATCHED_POIS,
        output_path=str(retail_parks_output_dir / "detected_retail_parks.parquet")
    )

    # Convert to H3 cells
    retail_parks_h3, retail_parks_dissolved = detect_retail_parks.convert_retail_parks_to_h3(
        retail_parks_polygons=retail_parks_polygons,
        output_h3_path=str(retail_parks_output_dir / "retail_park_cells.parquet"),
        output_polygons_path=str(retail_parks_output_dir / "retail_parks_polygons.parquet"),
        merge_adjacent=config.RETAIL_PARK_MERGE_ADJACENT,
        min_area_sqkm=config.RETAIL_PARK_MIN_AREA_SQKM
    )

    # Save merged and filtered version (this is what gets used in integration)
    retail_parks_h3.to_parquet(retail_parks_output_dir / "retail_park_cells_merged_filtered.parquet")
    retail_parks_path = str(retail_parks_output_dir / "retail_park_cells_merged_filtered.parquet")

    print(f"\n✓ Retail parks detected and saved to: {retail_parks_output_dir}")
    print(f"  Parks detected: {len(retail_parks_polygons)}")
    print(f"  After merging/filtering: {retail_parks_h3['park_id'].nunique()} parks, {len(retail_parks_h3)} cells")
else:
    print("\n✓ Retail parks integration disabled (config.INTEGRATE_RETAIL_PARKS = False)")

for idx, (
    min_retail_in_cell,
    min_retail_in_network,
    min_to_fill,
    split_threshold,
    merge_adjacent
) in enumerate(param_combinations_list, start=1):
    print(f"Processing combination {idx} of {total_combos}")
    print(
        f"Parameters: min_cell={min_retail_in_cell}, min_network={min_retail_in_network}, min_to_fill={min_to_fill}, split_threshold={split_threshold}, merge_adjacent={merge_adjacent}"
    )

    generate_networks(
        combined,
        run_name=run_name,
        min_retail_in_cell=min_retail_in_cell,
        min_retail_in_network=min_retail_in_network,
        min_to_fill=min_to_fill,
        split_threshold=split_threshold,
        merge_adjacent=merge_adjacent,
        enable_landuse_filter=config.ENABLE_LANDUSE_FILTER,
        landuse_overlap_threshold=config.LANDUSE_OVERLAP_THRESHOLD,
        landuse_poi_threshold=config.LANDUSE_MIN_POIS_EXEMPT,
        integrate_retail_parks=config.INTEGRATE_RETAIL_PARKS,
        retail_parks_path=retail_parks_path,
        min_remainder_pois=config.MIN_REMAINDER_POIS
    )