import argparse
import polars as pl
import pandas as pd
import numpy as np
from utils import utils as ut
from retail import retailfilter
from retail import foursquare_qualityfilter
from generate_networks import generate_networks
import itertools
import random

# Command line arguments
parser = argparse.ArgumentParser(description="Generate retail networks from parameter lists.")
parser.add_argument(
    "--foursquare",
    type=str,
    default="data/input_files/uk_foursquare_cc_nov_iceberg.parquet",
    help="Path to the input Foursquare parquet file."
)
parser.add_argument(
    "--run_name",
    type=str,
    required=True,
    help="Name for this run (required)."
)
parser.add_argument(
    "--use_presaved_filters",
    action="store_true",
    help="Use presaved quality filter results instead of running filters from scratch."
)
parser.add_argument(
    "--save_filter_ids",
    action="store_true",
    help="Save quality filter IDs for reuse in future runs (only used when not using presaved filters)."
)
parser.add_argument(
    "--filter_ids_path",
    type=str,
    default="data/POI_files/quality_filter_ids.parquet",
    help="Path to save/load quality filter IDs."
)
args = parser.parse_args()

# ========================================
# LANDUSE FILTER CONFIGURATION
# ========================================
# Enable/disable landuse filtering
ENABLE_LANDUSE_FILTER = True

# Overlap threshold: networks with >= this % overlap are flagged
LANDUSE_OVERLAP_THRESHOLD = 75.0

# POI exemption threshold: networks with >= this many POIs are exempt from removal
# Set to None to remove ALL high-overlap networks regardless of POI count
LANDUSE_MIN_POIS_EXEMPT = 20

# ========================================

# Set random seed for reproducibility
seed = 505
random.seed(seed)
np.random.seed(seed)

# Define parameter values
run_name = args.run_name
print(f"Run name: {run_name}")
sources = ["foursquare"]
min_retail_in_cell_values = [2]
min_retail_in_island_values = [1]
min_retail_in_network_values = [10]
min_to_fill = [6]
split_threshold = [1500, 9999999]
merge_adjacent = [True]

# Generate all parameter combinations
param_combinations = itertools.product(
    sources,
    min_retail_in_cell_values,
    min_retail_in_island_values,
    min_retail_in_network_values,
    min_to_fill,
    split_threshold,
    merge_adjacent
)
param_combinations_list = list(param_combinations)
total_combos = len(param_combinations_list)
print(f"Total combinations: {total_combos}")

foursquare = pl.read_parquet(args.foursquare)
overture = pl.read_parquet("data/input_files/poi_uk_overture_proc.parquet")

# Apply quality filters (closed venues, defunct retailers, UK boundary)
if args.use_presaved_filters:
    print(f"Using presaved quality filter results from: {args.filter_ids_path}")
    foursquare = foursquare_qualityfilter.load_and_apply_presaved_filters(
        foursquare,
        filter_ids_path=args.filter_ids_path
    )
else:
    print("Running quality filters from scratch")
    foursquare = foursquare_qualityfilter.filter_foursquare_quality(
        foursquare,
        save_filter_ids=args.save_filter_ids,
        filter_ids_path=args.filter_ids_path
    )

# Apply category filters
foursquare = retailfilter.filter_foursquare(foursquare)
overture = retailfilter.filter_overture(overture)

(
    foursquare
    .select(pl.col("fsq_category_labels").explode().alias("category"))
    .unique()
    .sort("category")
    .write_csv("unique_categories.csv")
)

foursquare = ut.add_h3_11_column(foursquare)
overture = ut.add_h3_11_column(overture)

foursquare_cells = ut.agg_to_cells_foursquare(foursquare)
overture_cells = ut.agg_to_cells(overture)

# Load land use data
land_use_cells = pd.read_parquet("data/input_files/retail_landuse_h3_geo.parquet")
land_use_cells = pl.DataFrame(land_use_cells)
combined = ut.create_combined_table(foursquare_cells, overture_cells, land_use_cells)

for idx, (
    source,
    min_retail_in_cell,
    min_retail_in_island,
    min_retail_in_network,
    min_to_fill,
    split_threshold,
    merge_adjacent
) in enumerate(param_combinations_list, start=1):
    print(f"Processing combination {idx} of {total_combos}")
    print(
        f"Parameters: source={source}, min_cell={min_retail_in_cell}, min_island={min_retail_in_island}, min_network={min_retail_in_network}, min_to_fill={min_to_fill}, split_threshold={split_threshold}, merge_adjacent={merge_adjacent}"
    )

    generate_networks(
        combined,
        run_name=run_name,
        source=source,
        min_retail_in_cell=min_retail_in_cell,
        min_retail_in_island=min_retail_in_island,
        min_retail_in_network=min_retail_in_network,
        min_to_fill=min_to_fill,
        split_threshold=split_threshold,
        merge_adjacent=merge_adjacent,
        enable_landuse_filter=ENABLE_LANDUSE_FILTER,
        landuse_overlap_threshold=LANDUSE_OVERLAP_THRESHOLD,
        landuse_poi_threshold=LANDUSE_MIN_POIS_EXEMPT
    )