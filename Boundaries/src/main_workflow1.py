#!/usr/bin/env python3
"""
Main workflow with Retail Park Integration - Workflow 1: Pre-Exclusion

This is a modified version of main.py that:
1. Loads retail park H3 cells
2. Filters the combined cells table to exclude retail park cells
3. Runs the standard pipeline on filtered cells
4. Adds retail parks back as separate networks at the end
"""

import argparse
import polars as pl
import pandas as pd
import geopandas as gpd
import numpy as np
from pathlib import Path
from utils import utils as ut
from retail import retailfilter
from retail import foursquare_qualityfilter
from generate_networks import generate_networks
import itertools
import random

# Command line arguments
parser = argparse.ArgumentParser(description="Generate retail networks with pre-excluded retail parks.")
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
    "--parks",
    type=str,
    required=True,
    help="Path to retail park H3 cells parquet (required for workflow 1)."
)
parser.add_argument(
    "--use_presaved_filters",
    action="store_true",
    help="Use presaved quality filter results instead of running filters from scratch."
)
parser.add_argument(
    "--save_filter_ids",
    action="store_true",
    help="Save quality filter IDs for reuse in future runs."
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
ENABLE_LANDUSE_FILTER = True
LANDUSE_OVERLAP_THRESHOLD = 75.0
LANDUSE_MIN_POIS_EXEMPT = 20

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

# ========================================
# LOAD RETAIL PARK CELLS
# ========================================
print("\n" + "="*80)
print("LOADING RETAIL PARK CELLS FOR PRE-EXCLUSION")
print("="*80)

park_cells_df = pd.read_parquet(args.parks)
if 'h3_11' not in park_cells_df.columns:
    raise ValueError("Parks file must have 'h3_11' column")

park_cells_set = set(park_cells_df['h3_11'].unique())
print(f"\nRetail park cells to exclude: {len(park_cells_set):,}")
print(f"Unique parks: {park_cells_df['park_id'].nunique():,}")

# ========================================
# LOAD AND FILTER POIs
# ========================================
foursquare = pl.read_parquet(args.foursquare)
overture = pl.read_parquet("data/input_files/poi_uk_overture_proc.parquet")

# Apply quality filters
if args.use_presaved_filters:
    print(f"\nUsing presaved quality filter results from: {args.filter_ids_path}")
    foursquare = foursquare_qualityfilter.load_and_apply_presaved_filters(
        foursquare,
        filter_ids_path=args.filter_ids_path
    )
else:
    print("\nRunning quality filters from scratch")
    foursquare = foursquare_qualityfilter.filter_foursquare_quality(
        foursquare,
        save_filter_ids=args.save_filter_ids,
        filter_ids_path=args.filter_ids_path
    )

# Apply category filters
foursquare = retailfilter.filter_foursquare(foursquare)
overture = retailfilter.filter_overture(overture)

# Save unique categories
(
    foursquare
    .select(pl.col("fsq_category_labels").explode().alias("category"))
    .unique()
    .sort("category")
    .write_csv("unique_categories.csv")
)

# Add H3 cells
foursquare = ut.add_h3_11_column(foursquare)
overture = ut.add_h3_11_column(overture)

# Aggregate to cells
foursquare_cells = ut.agg_to_cells_foursquare(foursquare)
overture_cells = ut.agg_to_cells(overture)

# Load land use data
land_use_cells = pd.read_parquet("data/input_files/retail_landuse_h3_geo.parquet")
land_use_cells = pl.DataFrame(land_use_cells)
combined = ut.create_combined_table(foursquare_cells, overture_cells, land_use_cells)

# ========================================
# FILTER OUT RETAIL PARK CELLS
# ========================================
print("\n" + "="*80)
print("FILTERING COMBINED CELLS TO EXCLUDE RETAIL PARKS")
print("="*80)

original_cell_count = combined.shape[0]
print(f"\nOriginal cell count: {original_cell_count:,}")

# Filter out park cells
combined_filtered = combined.filter(~pl.col("h3_11").is_in(list(park_cells_set)))

filtered_cell_count = combined_filtered.shape[0]
excluded_cell_count = original_cell_count - filtered_cell_count

print(f"Cells in retail parks (excluded): {excluded_cell_count:,} ({excluded_cell_count/original_cell_count*100:.1f}%)")
print(f"Cells remaining: {filtered_cell_count:,} ({filtered_cell_count/original_cell_count*100:.1f}%)")

# ========================================
# RUN PIPELINE ON FILTERED CELLS
# ========================================
print("\n" + "="*80)
print("RUNNING PIPELINE ON FILTERED CELLS (EXCLUDING PARKS)")
print("="*80)

for idx, (
    source,
    min_retail_in_cell,
    min_retail_in_island,
    min_retail_in_network,
    min_to_fill,
    split_threshold,
    merge_adjacent
) in enumerate(param_combinations_list, start=1):
    print(f"\nProcessing combination {idx} of {total_combos}")
    print(
        f"Parameters: source={source}, min_cell={min_retail_in_cell}, min_island={min_retail_in_island}, "
        f"min_network={min_retail_in_network}, min_to_fill={min_to_fill}, split_threshold={split_threshold}, "
        f"merge_adjacent={merge_adjacent}"
    )

    # Generate networks on filtered cells
    generate_networks(
        combined_filtered,
        run_name=f"{run_name}_workflow1",
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

    # ========================================
    # ADD RETAIL PARKS BACK AS SEPARATE NETWORKS
    # ========================================
    print("\n" + "="*80)
    print("ADDING RETAIL PARKS BACK AS SEPARATE NETWORKS")
    print("="*80)

    # Construct output folder name
    merge_flag = "y" if merge_adjacent else "n"
    folder_name = (
        f"{run_name}_workflow1_{source}_mrc_{min_retail_in_cell}_mri_{min_retail_in_island}_"
        f"mrn_{min_retail_in_network}_mtf_{min_to_fill}_splitthresh_{split_threshold}"
        f"_merge_{merge_flag}"
    )
    output_folder = Path(f"data/output_files/{folder_name}")

    # Load centres from pipeline output
    centres_path = output_folder / "3_afterfill.parquet"
    if not centres_path.exists():
        print(f"Warning: {centres_path} not found, skipping park integration")
        continue

    centres = gpd.read_parquet(centres_path)
    print(f"\nLoaded centres: {centres['network_number'].nunique():,} networks, {len(centres):,} cells")

    # Create park networks
    park_cells_geo = ut.to_geoframe(park_cells_df)

    # Assign network IDs
    starting_id = centres['network_number'].max() + 100000 if len(centres) > 0 else 1000000
    park_cells_geo['network_number'] = park_cells_geo['park_id'] + starting_id
    park_cells_geo['centre_type'] = 'retail_park'

    # Add POI count column to match centres
    if 'centre_poi_total' in park_cells_geo.columns and 'foursquare_count' not in park_cells_geo.columns:
        park_cells_geo['foursquare_count'] = park_cells_geo['centre_poi_total']

    print(f"Created park networks: {park_cells_geo['network_number'].nunique():,} networks, {len(park_cells_geo):,} cells")

    # Add type to centres
    if 'centre_type' not in centres.columns:
        centres['centre_type'] = 'retail_centre'

    # Find common columns and combine
    common_cols = list(set(centres.columns) & set(park_cells_geo.columns))
    if 'geometry' not in common_cols:
        common_cols.append('geometry')

    combined_output = pd.concat([
        centres[common_cols],
        park_cells_geo[common_cols]
    ], ignore_index=True)

    print(f"Combined total: {combined_output['network_number'].nunique():,} networks, {len(combined_output):,} cells")

    # Save H3 cell outputs
    centres.to_parquet(output_folder / "retail_centres.parquet")
    park_cells_geo.to_parquet(output_folder / "retail_parks.parquet")
    combined_output.to_parquet(output_folder / "combined_centres_and_parks.parquet")

    print(f"\n✓ Saved retail_centres.parquet (H3 cells)")
    print(f"✓ Saved retail_parks.parquet (H3 cells)")
    print(f"✓ Saved combined_centres_and_parks.parquet (H3 cells)")

    # Create dissolved polygon versions
    print("\nCreating dissolved polygon outputs...")
    from shapely.geometry import Polygon, MultiPolygon

    def dissolve_to_polygons(gdf, name):
        """Dissolve cells to polygons by network."""
        # Standardize POI count column
        if 'poi_count' not in gdf.columns:
            if 'foursquare_count' in gdf.columns:
                gdf['poi_count'] = gdf['foursquare_count']
            elif 'centre_poi_total' in gdf.columns:
                gdf['poi_count'] = gdf['centre_poi_total']
            else:
                gdf['poi_count'] = 0

        # Compute stats
        network_stats = gdf.groupby('network_number').agg({
            'h3_11': 'count',
            'poi_count': 'sum',
            'centre_type': 'first'
        }).rename(columns={'h3_11': 'cell_count'})

        # Dissolve
        dissolved = gdf.dissolve(by='network_number')
        dissolved = dissolved.join(network_stats, rsuffix='_stats')
        dissolved['centre_type'] = dissolved['centre_type_stats']
        dissolved = dissolved[['centre_type', 'cell_count', 'poi_count', 'geometry']]

        # Fill holes
        def fill_holes(geom):
            if geom.geom_type == 'Polygon':
                return Polygon(geom.exterior)
            elif geom.geom_type == 'MultiPolygon':
                return MultiPolygon([Polygon(p.exterior) for p in geom.geoms])
            return geom

        dissolved['geometry'] = dissolved['geometry'].apply(fill_holes)

        # Add area
        dissolved_27700 = dissolved.to_crs('EPSG:27700')
        dissolved['area_sqm'] = dissolved_27700.geometry.area
        dissolved['area_sqkm'] = dissolved['area_sqm'] / 1_000_000

        dissolved = dissolved.reset_index()
        dissolved = dissolved.sort_values(['centre_type', 'poi_count'], ascending=[True, False])

        print(f"  {name}: {len(dissolved):,} networks, {dissolved['poi_count'].sum():,.0f} POIs, {dissolved['area_sqkm'].sum():.1f} km²")
        return dissolved

    centres_polygons = dissolve_to_polygons(centres, "Centres")
    centres_polygons.to_parquet(output_folder / "retail_centres_polygons.parquet")

    parks_polygons = dissolve_to_polygons(park_cells_geo, "Parks")
    parks_polygons.to_parquet(output_folder / "retail_parks_polygons.parquet")

    combined_polygons = dissolve_to_polygons(combined_output, "Combined")
    combined_polygons.to_parquet(output_folder / "combined_centres_and_parks_polygons.parquet")

    print(f"\n✓ Saved retail_centres_polygons.parquet")
    print(f"✓ Saved retail_parks_polygons.parquet")
    print(f"✓ Saved combined_centres_and_parks_polygons.parquet")

print("\n" + "="*80)
print("WORKFLOW 1 COMPLETE - ALL COMBINATIONS PROCESSED")
print("="*80)
