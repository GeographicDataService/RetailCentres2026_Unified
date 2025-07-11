##Script to generate the retail networks from lists of parameters

import polars as pl
import pandas as pd
import numpy as np
from utils import utils as ut
from retail import retailfilter_new as retailfilter
from generate_networks import generate_networks
import itertools
import random

#set random seed for reproducibility (of the subnetwork finding algorithm)
seed = 505
random.seed(seed)        # or any integer
np.random.seed(seed)

# # Define parameter values
sources = ["foursquare"]
min_retail_in_cell_values = [2]
min_retail_in_island_values = [1]
min_retail_in_network_values = [10]
min_to_fill = [6]
# split_threshold = [1500,9999999]  # Threshold for splitting networks based on POI count
split_threshold = [1500,9999999]  # Threshold for splitting networks based on POI count
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
# Convert to a list once for both counting and iteration
param_combinations_list = list(param_combinations)
total_combos = len(param_combinations_list)
print(f"Total combinations: {total_combos}")

foursquare = pl.read_parquet(
    "data/input_files/uk_foursquare_datefields_admin_categories.parquet"
)
overture = pl.read_parquet(
    "data/input_files/poi_uk_overture_proc.parquet"
)


foursquare = retailfilter.filter_foursquare(foursquare)
overture = retailfilter.filter_overture(overture)

(
    foursquare
    .select(pl.col("fsq_category_labels").explode().alias("category"))  # name the column
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
#
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

    # Generate networks with the current parameters
    generate_networks(
        combined,
        source=source,
        min_retail_in_cell=min_retail_in_cell,
        min_retail_in_island=min_retail_in_island,
        min_retail_in_network=min_retail_in_network,
        min_to_fill=min_to_fill,
        split_threshold=split_threshold,
        merge_adjacent=merge_adjacent
    )