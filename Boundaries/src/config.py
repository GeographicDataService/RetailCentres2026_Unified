"""
Centralized configuration for the RetailCentres pipeline.

This module contains all configurable parameters for the retail centre detection pipeline,
including file paths, filter settings, and algorithm parameters.
"""

from pathlib import Path
from typing import Optional


# ========================================
# FILE PATHS
# ========================================

# Base directories
DATA_DIR = Path("data")
INPUTS_DIR = DATA_DIR / "inputs"
RUNS_DIR = DATA_DIR / "outputs" / "runs"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
BOUNDARIES_DIR = INPUTS_DIR / "boundaries"
LANDUSE_DIR = INPUTS_DIR / "landuse"

# Input data paths
FOURSQUARE_PATH = INPUTS_DIR / "poi" / "uk_foursquare_cc_nov_iceberg.parquet"

COMMERCIAL_LANDUSE_PATH = LANDUSE_DIR / "commercial_landuse.parquet"
INDUSTRIAL_LANDUSE_PATH = LANDUSE_DIR / "industrial_landuse.parquet"
RETAIL_LANDUSE_H3_GEO_PATH = LANDUSE_DIR / "retail_landuse_h3_geo.parquet"
RETAIL_LANDUSE_POLYGONS_PATH = LANDUSE_DIR / "retail_landuse.parquet"

# Lookup tables (brand lists, defunct retailers)
LOOKUP_TABLES_DIR = Path(__file__).parent / "config" / "lookup_tables"
RETAIL_PARK_BRANDS_PATH = LOOKUP_TABLES_DIR / "retail_park_brands.csv"
DEFUNCT_RETAILERS_PATH = LOOKUP_TABLES_DIR / "defunct_retailers.csv"

# ONSPD (postcode data)
ONSPD_DIR = INPUTS_DIR / "onspd"



## Intermediate output paths

# Filter ID paths
FILTER_IDS_PATH = INTERMEDIATE_DIR / "poi_filtered" / "quality_filter_ids.parquet"


# ========================================
# QUALITY FILTER CONFIGURATION
# ========================================

# Whether to use presaved quality filter results (faster)
USE_PRESAVED_FILTERS = False

# Whether to save quality filter IDs for future reuse
SAVE_FILTER_IDS = False


# ========================================
# LANDUSE FILTER CONFIGURATION
# ========================================

# Enable/disable commercial/industrial landuse filtering
ENABLE_LANDUSE_FILTER = True

# Overlap threshold: networks with >= this % overlap with commercial/industrial
# land use are flagged for removal (default: 75%)
LANDUSE_OVERLAP_THRESHOLD = 75.0

# POI exemption threshold: networks with >= this many POIs are exempt from removal
# even if they exceed the overlap threshold
# Set to None to remove ALL high-overlap networks regardless of POI count
LANDUSE_MIN_POIS_EXEMPT = 20


# ========================================
# RETAIL LANDUSE POI FILTER CONFIGURATION
# ========================================

# Filter retail land use polygons by POI count before network generation
# This removes retail land use areas with insufficient POI density
FILTER_RETAIL_LANDUSE = True

# Minimum POIs required in a retail land use polygon to keep it
MIN_POIS_PER_LANDUSE_POLYGON = 1


# ========================================
# RETAIL PARKS CONFIGURATION
# ========================================

# Whether to include retail parks in the pipeline
# When True, retail parks are detected from scratch and integrated into centres
# When False, no retail park processing occurs
INTEGRATE_RETAIL_PARKS = True

# Retail park detection parameters
RETAIL_PARK_MIN_RATIO = 0.05  # Minimum ratio of bigbox to total POIs (5%)
RETAIL_PARK_MIN_MATCHED_POIS = 1  # Minimum number of bigbox POIs
RETAIL_PARK_MERGE_ADJACENT = True  # Merge adjacent/overlapping parks
RETAIL_PARK_MIN_AREA_SQKM = 0.007  # Minimum area after merging (sqkm)

# Minimum POIs required in remainder centres after retail park subtraction
# Centres below this threshold are removed
MIN_REMAINDER_POIS = 10


# ========================================
# NETWORK GENERATION PARAMETERS
# ========================================

# Random seed for reproducibility (used in Leiden clustering)
RANDOM_SEED = 505

# Default parameter values for network generation
# These can be overridden via command line or in parameter sweeps

# Minimum POIs required for a H3 cell to be included
DEFAULT_MIN_RETAIL_IN_CELL = 2

# Minimum POIs required for final networks after processing
DEFAULT_MIN_RETAIL_IN_NETWORK = 10

# Minimum adjacent cells required to trigger gap-filling
# Set to 6+ to effectively disable filling (hexagons have 6 neighbors)
DEFAULT_MIN_TO_FILL = 6

# POI threshold for network splitting via Leiden clustering
# Networks below this threshold are not split into subcentres
# Set to very high value (e.g., 9999999) to disable splitting
DEFAULT_SPLIT_THRESHOLD = 1500

# Whether to merge networks separated by a single cell
DEFAULT_MERGE_ADJACENT = True


# ========================================
# PARAMETER SWEEP CONFIGURATION
# ========================================

# Parameter values to test in sweeps (main.py)
# Each creates a separate output folder with results

PARAM_SWEEP_SOURCES = ["foursquare"]
PARAM_SWEEP_MIN_RETAIL_IN_CELL = [2]
PARAM_SWEEP_MIN_RETAIL_IN_NETWORK = [10]
PARAM_SWEEP_MIN_TO_FILL = [6]
PARAM_SWEEP_SPLIT_THRESHOLD = [1500, 9999999]
PARAM_SWEEP_MERGE_ADJACENT = [True]


# ========================================
# LEIDEN CLUSTERING PARAMETERS
# ========================================
# (Used in find_subcentres.py)

# Resolution parameter for Leiden algorithm (higher = more communities)
LEIDEN_RESOLUTION = 0.15

# Alpha parameter for edge weighting (0 = pure density, 1 = pure similarity)
LEIDEN_ALPHA = 0

# Random seed for Leiden clustering (for reproducibility)
LEIDEN_SEED = 505


# ========================================
# HELPER FUNCTIONS
# ========================================

def get_output_folder_name(
    run_name: str,
    source: str,
    min_retail_in_cell: int,
    min_retail_in_network: int,
    min_to_fill: int,
    split_threshold: int,
    merge_adjacent: bool
) -> str:
    """
    Generate output folder name from parameters (without run_name prefix).

    Format: {source}_mrc_{min_cell}_mrn_{min_network}_mtf_{min_fill}_splitthresh_{threshold}_merge_{y/n}
    """
    merge_flag = "y" if merge_adjacent else "n"
    return (
        f"{source}_mrc_{min_retail_in_cell}_"
        f"mrn_{min_retail_in_network}_mtf_{min_to_fill}_splitthresh_{split_threshold}"
        f"_merge_{merge_flag}"
    )
