# Retail Centres Project

This project provides tools and scripts for identifying, analyzing, and exporting UK retail centre boundaries. The boundaries are created using open source POI (Point of Interest) data (Foursquare and/or Overture).

**Methodology:** See [method.md](method.md) for pipeline details.

## References
Previous boundaries:
- [Retail Centre Boundaries and Open Indicators Dataset](https://data.geods.ac.uk/dataset/retail-centre-boundaries-and-open-indicators)
- [Open Retail Centres: A National Open Data Set of Retail Centre Boundaries and Indicators (Nature Scientific Data, 2022)](https://www.nature.com/articles/s41597-022-01556-3)

## Code Structure
```
RetailCentres/
│
├── src/
│   ├── main.py                         # Parameter sweep workflow (recommended)
│   ├── generate_networks.py            # Core pipeline orchestrator
│   ├── config.py                       # Configuration parameters
│   ├── retail/                         # Core retail centre logic
│   │   ├── retailfilter.py             # POI filtering
│   │   ├── foursquare_qualityfilter.py # Quality filters for Foursquare data
│   │   ├── network_merger.py           # Network refinement and merging
│   │   ├── find_subcentres.py          # Leiden clustering for subcentres
│   │   ├── centre_postprocessing.py    # Polygon finalization
│   │   ├── manual_edits.py             # Manual boundary corrections
│   │   ├── detect_retail_parks.py      # Retail park detection
│   │   ├── integrate_retail_parks.py   # Retail park integration
│   │   ├── landuse_filter.py           # Land use filtering
│   │   └── retail_landuse_poi_filter.py
│   └── utils/
│       └── utils.py                    # H3 aggregation and geospatial utilities
├── data/
│   ├── inputs/
│   │   ├── poi/                        # Foursquare POI data
│   │   ├── boundaries/                 # Local Authority boundaries
│   │   ├── landuse/                    # OSM land use data (H3 cells)
│   │   ├── brands/                     # Brand classification data (defunct and big box)
│   │   └── onspd/                      # UK postcode data
│   ├── intermediate/                   # Pipeline stage outputs (0-3)
│   └── outputs/                        # Final centre boundaries (4)
├── notebooks/                          # Jupyter notebooks for analysis
├── tests/                              # Unit tests
├── method.md                           # Methodology documentation
└── pyproject.toml                      # Project dependencies
```

## Data Structure

### Inputs (in `data/inputs/`)
- **poi/** - Foursquare POI parquet files with lat/lng and categories
- **landuse/** - OSM retail/commercial land use (H3 cells, generated via separate script)

### Outputs (in `data/intermediate/` and `data/outputs/`)
For each parameter combination, the pipeline produces:
```
{run_name}_{parameters}/
├── 0_input_cells.parquet              # Filtered H3 cells meeting criteria
├── 1_initial_networks.parquet         # Connected components
├── 2_merged_filtered_networks.parquet # After merging and thresholding
├── 3_afterfill.parquet                # After gap filling
└── 4_finalcentres_las.parquet         # Final boundaries + Local Authority IDs
```

## How to Run

### Installation
```bash
uv pip install -e .
```

### Run Pipeline
```bash
# Basic run (parameters configured in src/config.py)
python src/main.py --run_name "test_run"

# Use presaved quality filters for faster execution
python src/main.py --run_name "test_run" --use_presaved_filters
```

**Note:** Edit `src/config.py` to configure:
- Data paths (POI files, land use, boundaries)
- Parameter sweep values (min POI thresholds, fill settings, etc.)
- Feature flags (retail parks, land use filters)

### Format Conversion (for ArcGIS Online)
```bash
# Convert to Shapefile
python src/utils/convtoshp.py output.parquet -f shapefile

# Convert to GeoJSON
python src/utils/convtoshp.py output.parquet -f geojson
```

### Testing
```bash
pytest
```

