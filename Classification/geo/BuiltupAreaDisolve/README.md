# RetailTyp

Geospatial analysis project for processing UK Built-Up Area (BUA) polygon data. Merges near-touching polygons using a buffer-dissolve-negative buffer technique and compares the result against ONS reference boundaries.

## Data Setup

Download these two files into the `data/` directory:

1. **OS Open Built Up Areas** (source data)
   - Download from: https://osdatahub.os.uk/downloads/open/BuiltUpAreas
   - Select "GeoPackage" format
   - Place `os_open_built_up_areas.gpkg` in `data/`

2. **Built Up Areas Dec 2011 Boundaries V2** (reference data)
   - Download from: https://geoportal.statistics.gov.uk
   - Search for "Built Up Areas Dec 2011 Boundaries V2"
   - Select GeoPackage format
   - Rename to `Built_up_Areas_Dec_2011_Boundaries_V2_2022.gpkg` and place in `data/`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install geopandas shapely fiona tqdm
```

## Usage

### 1. Merge near-touching polygons

```bash
python merge_polygons.py
```

Reads `data/os_open_built_up_areas.gpkg`, applies a 100m buffer to each polygon, unions them together, then applies a -100m negative buffer to restore approximate original sizes. This effectively merges any polygons within 200m of each other. The result is exploded from multipolygons into individual polygons and saved to `output/merged_bua.gpkg`.

### 2. Compare with reference boundaries

```bash
python compare_datasets.py
```

Compares the merged output against the ONS reference boundaries. Reports:

- Total area of each dataset
- Intersection and union areas
- IoU (Jaccard index) as a spatial similarity metric
- Coverage percentages in both directions

Also generates simplified (50m tolerance) GeoParquet files for faster viewing:

- `output/merged_bua_simplified.parquet`
- `output/reference_bua_simplified.parquet`

## Project Structure

```
├── merge_polygons.py       # Polygon merging via buffer-dissolve-negative buffer
├── compare_datasets.py     # Spatial comparison against ONS reference data
├── data/                   # Input GeoPackages (not tracked in git)
└── output/                 # Merged results and simplified parquet files
```

## Notes

- All data uses EPSG:27700 (British National Grid)
- The buffer distance (100m) is configurable in `merge_polygons.py`
- The simplification tolerance (50m) is configurable in `compare_datasets.py`
- Source data: Contains Ordnance Survey data Crown copyright and database right 2024
