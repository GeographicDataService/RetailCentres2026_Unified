# OSM Land Use Data Grabber

This script downloads and processes land use data from OpenStreetMap for the UK.

## Overview

The `grab_osm_landuse.py` script:
1. Queries OpenStreetMap for retail and/or commercial land use polygons
2. Splits the UK into a grid for parallel downloading (faster)
3. Converts polygons to H3 hexagonal cells (resolution 11)
4. Saves both polygon and H3 versions

## Usage

### Basic Usage

```bash
# Grab all land use types (retail, commercial, industrial)
python src/grab_osm_landuse.py

# Grab specific types
python src/grab_osm_landuse.py --landuse retail      # Retail only
python src/grab_osm_landuse.py --landuse commercial  # Commercial only
python src/grab_osm_landuse.py --landuse industrial  # Industrial only
```

### Advanced Options

```bash
# Custom output directory
python src/grab_osm_landuse.py --output_dir "data/osm_landuse"

# Adjust grid splits (higher = more parallel queries, but smaller chunks)
python src/grab_osm_landuse.py --num_splits 15  # 15x15 = 225 sub-areas

# Adjust parallelism
python src/grab_osm_landuse.py --max_workers 8  # Reduce if hitting rate limits
```

## Output Files

For each land use type (retail, commercial, industrial), the script creates:

### Polygon Files
- `retail_landuse.parquet` - GeoParquet with polygon geometries
- `commercial_landuse.parquet` - GeoParquet with polygon geometries
- `industrial_landuse.parquet` - GeoParquet with polygon geometries

Columns:
- `geometry`: Polygon or MultiPolygon
- `landuse`: "retail", "commercial", or "industrial"
- `name`: OSM name tag (if available)

### H3 Cell Files
- `retail_landuse_h3.parquet` - H3 cells covering retail polygons
- `commercial_landuse_h3.parquet` - H3 cells covering commercial polygons
- `industrial_landuse_h3.parquet` - H3 cells covering industrial polygons

Columns:
- `h3_11`: H3 cell index (resolution 11, ~100-200m cell size)
- `landuse`: "retail", "commercial", or "industrial"

## How It Works

### 1. Grid-Based Parallel Downloading
The script splits the UK into a grid (default 10x10 = 100 sub-areas) and queries each in parallel. This:
- Speeds up downloads significantly
- Avoids OSM query timeout issues
- Reduces memory usage per query

### 2. H3 Conversion Strategy
For each polygon:
- Convert to H3 cells at resolution 13 (fine detail, ~30m cells)
- Derive parent resolution 11 cells (aggregated, ~200m cells)
- This ensures complete coverage while matching the pipeline's H3 resolution

### 3. Deduplication
- Polygons are deduplicated after clipping to UK boundary
- H3 cells are deduplicated across all polygons

## Performance

Typical runtime (UK-wide):
- **Retail land use**: ~20-30 seconds (10x10 grid, 16 workers)
- **Commercial land use**: ~20-30 seconds (10x10 grid, 16 workers)
- **Industrial land use**: ~20-30 seconds (10x10 grid, 16 workers)
- **All three**: ~60-90 seconds total

Memory usage:
- Peak: ~2-4 GB (depending on data volume)

## Integration with Pipeline

The H3 files are used in the main retail centre pipeline:

```python
# In main.py
land_use_cells = pd.read_parquet("data/input_files/retail_landuse_h3.parquet")
```

### Commercial Land Use Filter
The commercial land use data can be used to filter out retail centres that are primarily commercial areas (e.g., office parks). See the prototype in `notebooks/process_input_data/GrabOSMdata_comm.ipynb` for coverage analysis.

## Dependencies

Required packages:
- `osmnx` - OpenStreetMap data access
- `geopandas` - Geospatial data handling
- `h3` - H3 hexagonal indexing
- `pandas` - Data manipulation
- `shapely` - Geometric operations
- `tqdm` - Progress bars

Install with:
```bash
pip install osmnx geopandas h3 pandas shapely tqdm
```

## Troubleshooting

### OSM Query Timeouts
If queries timeout, try:
- Increase grid splits: `--num_splits 15` (creates smaller query areas)
- Reduce workers: `--max_workers 8` (reduces concurrent load on OSM)

### Memory Issues
If running out of memory:
- Reduce workers: `--max_workers 4`
- Increase grid splits: `--num_splits 12` (smaller batches)

### Rate Limiting
OSM has rate limits. If hitting them:
- Reduce max_workers: `--max_workers 4`
- Wait a few minutes between runs

## Background: OSM Land Use Tags

### Retail Land Use (`landuse=retail`)
OSM tag for areas primarily used for retail shops:
- Shopping centers / malls
- Retail parks
- High streets with continuous retail frontage
- Market areas

### Commercial Land Use (`landuse=commercial`)
OSM tag for areas primarily used for business/services:
- Office parks
- Business districts
- Mixed commercial areas
- Service industry zones

Note: There's overlap between retail and commercial in OSM tagging practice. Some areas are tagged as both.

## Example: Using the Data

```python
import pandas as pd
import geopandas as gpd

# Load H3 cells
retail_h3 = pd.read_parquet("data/input_files/retail_landuse_h3.parquet")
commercial_h3 = pd.read_parquet("data/input_files/commercial_landuse_h3.parquet")

# How many unique H3 cells?
print(f"Retail H3 cells: {retail_h3['h3_11'].nunique():,}")
print(f"Commercial H3 cells: {commercial_h3['h3_11'].nunique():,}")

# Load polygons for visualization
retail_polys = gpd.read_parquet("data/input_files/retail_landuse.parquet")
retail_polys.plot()
```

## Related Files

- `notebooks/process_input_data/GrabOSMdata.ipynb` - Original retail prototype
- `notebooks/process_input_data/GrabOSMdata_comm.ipynb` - Original commercial prototype
- `src/main.py` - Main pipeline that uses land use data
