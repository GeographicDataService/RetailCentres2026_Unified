# Retail Centre Naming Pipeline

Python pipeline for assigning place names and classifications to UK retail centre boundaries. Re-implementation of the original R pipeline (`Retail-Centre-Boundaries/Code/`), using Foursquare POI data in place of VOA/LDC sources.

## Pipeline

The pipeline runs in two stages:

1. **`naming.py`** — Builds naming lookup tables by spatially matching centres against reference boundaries and gazetteers:
   - ONS naming (LA, County, Region, Neighbourhood)
   - OS Open Names nearest and internal place search
   - Street naming from Foursquare POI addresses
   - OSM retail park names
   - OSM neighbourhood names

2. **`generate_names.py`** — Combines the lookup tables to assemble final names, applying classification hierarchy, name formatting, duplicate disambiguation, and sub-area naming.

## Input Data

The main input is a set of pre-delineated and pre-classified retail centre polygons with Foursquare POI data joined.

### `data/` contents

| File | Description | Source |
|------|-------------|--------|
| `rc2025_foursquare_LondonMannual.gpkg` | 9624 retail centre polygons (EPSG:27700) | Pre-processed input |
| `foursquare_quality_retail_filtered.parquet` | Foursquare POI points for street/address extraction | Foursquare |
| `LAD_Dec2024_UK.gpkg` | Local Authority District boundaries | ONS Open Geography |
| `MSOA_Dec2021_EW.gpkg` | MSOA boundaries (England & Wales) | ONS Open Geography |
| `os_open_names/Data/opname_gb.gpkg` | OS Open Names gazetteer (cities, towns, villages, etc.) | OS Data Hub (manual download) |
| `retail_landuse.parquet` | OSM retail/commercial landuse polygons | OpenStreetMap |
| `osm_neighbourhoods.parquet` | OSM neighbourhood/suburb place names | OpenStreetMap |
| `osm_ni_places.parquet` | OSM place names for Northern Ireland | OpenStreetMap |
| `scotland/SG_IntermediateZone_2011/` | Scottish Intermediate Zone boundaries | Scottish Government |
| `northern_ireland/SDZ2021.*` | NI Super Data Zones (neighbourhood proxy) | NISRA |

### Setup

Most reference data can be downloaded automatically:

```bash
python download_data.py
```

**OS Open Names** requires manual download from the [OS Data Hub](https://osdatahub.os.uk/downloads/open/OpenNames) (GeoPackage format, ~2GB). Extract to `data/os_open_names/`.

All other input data (retail centre polygons, Foursquare POI) is bundled in `data_inputs.zip` (excludes OS Open Names due to size).

## Usage

```bash
source .venv/bin/activate
pip install geopandas fiona pandas numpy shapely pyogrio

# Stage 1: build lookup tables
python naming.py

# Stage 2: assemble final names
python generate_names.py
```

Output is written to `exports/`:
- `rc2025_named.gpkg` — final named retail centres
- `rc2025_named.parquet` — same, in Parquet format
- `rc2025_naming_lookup.csv` — combined lookup table

## Other Scripts

- `download_data.py` — downloads ONS/Scottish/NI reference boundary data
- `compare_names.py` — compares new names against a previous version
- `naming_comparison.py` — detailed comparison analysis of naming changes
