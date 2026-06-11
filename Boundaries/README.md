# Retail Centre Boundaries

This project provides tools and scripts for identifying, analysing, and exporting UK retail centre boundaries. The boundaries are created using open source POI (Point of Interest) data (Foursquare) and landuse data (OSM).



<img width="1407" height="726" alt="image" src="https://github.com/user-attachments/assets/57fa2bca-145c-400d-ab2b-0883a24c748e" />

## Method 
**Methodology:** See [method.md](method.md) for pipeline details.

**Previous boundaries** :
- [Retail Centre Boundaries and Open Indicators Dataset](https://data.geods.ac.uk/dataset/retail-centre-boundaries-and-open-indicators)
- [Open Retail Centres: A National Open Data Set of Retail Centre Boundaries and Indicators (Nature Scientific Data, 2022)](https://www.nature.com/articles/s41597-022-01556-3)

## Code Structure
```
RetailCentres/
│
├── src/
│   ├── main.py                         # Parameter sweep workflow
│   ├── generate_networks.py            # Core pipeline orchestrator
│   ├── config.py                       # Configuration parameters
│   ├── config/
│   │   └── lookup_tables/              # Reference data (committed to git)
│   │       ├── defunct_retailers.csv   # Defunct UK retailer brands
│   │       └── retail_park_brands.csv  # Big-box retail park brands
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
│       └── utils.py                    # H3 aggregation, network creation
├── data/
│   ├── inputs/
│   │   ├── poi/                        # Foursquare POI data
│   │   ├── boundaries/                 # Local Authority boundaries
│   │   ├── landuse/                    # OSM land use data (H3 cells)
│   │   └── onspd/                      # UK postcode data
│   ├── intermediate/                   # Reusable filter and land-use artifacts
│   └── outputs/
│       └── runs/                       # Per-run parameter outputs
├── notebooks/                          # Jupyter notebooks for analysis
├── tests/                              # Unit tests
├── method.md                           # Methodology documentation
└── README.md / method.md               # Documentation
```

## Data Structure

### Inputs (in `data/inputs/`)
- **poi/** - Foursquare POI parquet files with lat/lng and categories
- **landuse/** - OSM retail/commercial land use (H3 cells, generated via separate script)

### Outputs (in `data/intermediate/` and `data/outputs/`)
For each run, the pipeline writes shared filtered POI files under
`data/outputs/runs/<run_name>/`, then one folder per parameter combination:
```
data/outputs/runs/<run_name>/
├── foursquare_quality_filtered.parquet
├── foursquare_filtered.parquet
├── retail_parks/
└── foursquare_mrc_2_mrn_10_mtf_6_splitthresh_<threshold>_merge_y/
├── 0_input_cells.parquet              # Filtered H3 cells meeting criteria
├── 1_initial_networks.parquet         # Connected components
├── 2_filtered_networks.parquet        # After network thresholding / one-cell merging
├── 3_afterfill.parquet                # After gap filling
└── 4_finalcentres_las.parquet         # Final boundaries + Local Authority IDs
```

## How to Run

### Installation

Dependencies are managed from the **repository root** (single `pyproject.toml` +
`uv.lock` covering Boundaries, Classification, and Naming). Install from there:

```bash
# From the repo root (recommended)
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

### Run Pipeline
```bash
# Activate the root environment, then run from the Boundaries/ directory
source ../.venv/bin/activate

# Basic run (parameters configured in src/config.py)
python src/main.py --run_name "test_run"

# Use presaved quality filters for faster execution
python src/main.py --run_name "test_run" --use_presaved_filters
```

**Note:** Edit `src/config.py` to configure:
- Data paths (POI files, land use, boundaries)
- Parameter sweep values (min POI thresholds, fill settings, etc.)
- Feature flags (retail parks, land use filters)

### Package Inputs

To bundle all data needed to run the Boundaries stage standalone:

```bash
./make_inputs_zip.sh
```

This writes `boundaries_inputs.zip` with entries under `data/inputs/...`.
Unzip it from `Boundaries/` to restore the paths expected by `src/config.py`.

### Testing
```bash
pytest
```

---

## Acquiring Input Data

The following input datasets are required but not included in this repository:

### Quick Start (GeoDS Members)

**For GeoDS members:** A packaged version of all input files is available on SharePoint:
- **Location:** `GeoDS > Shared Documents > 1 Data Products > Product Development > RetailCentreBounds2025 > inputs.zip`
- **Direct link:** [Download inputs.zip](https://liveuclac.sharepoint.com/:u:/r/sites/GeoDS/Shared%20Documents/1%20Data%20Products/Product%20Development/RetailCentreBounds2025/inputs.zip?csf=1&web=1&e=pTauSG)
- **Extract to:** `data/inputs/`
- **Contents:** Foursquare POI data, OSM land use data, boundaries, reference data

After extracting, your folder structure should look like:
```
data/inputs/
├── poi/
├── landuse/
├── boundaries/
└── reference/
```

### Manual Data Acquisition

If you don't have GeoDS access, you can acquire the following datasets individually:

### Core POI Data
**Foursquare POI Data** - Use the Foursquare POI package 
- Place in: `data/inputs/poi/`

### OSM Land Use Data
**OpenStreetMap Land Use** - Download from OSMNX using the provided script:
```bash
python scripts/grab_osm_landuse.py --landuse both
```
This creates H3 cell versions of retail and commercial land use areas.
- Output location: `data/inputs/landuse/`
- See `docs/OSM_LANDUSE_GRABBER.md` for detailed documentation

### Administrative Boundaries

**ONSPD (Postcode Directory)**
- Source: [ONS Open Geography Portal - ONSPD](https://geoportal.statistics.gov.uk/search?q=ONSPD)
- UK postcode to coordinate lookup data
- Place in: `data/inputs/onspd/`

**UK Country Boundary**
- Source: [ONS Open Geography Portal - Countries (December 2022) Boundaries UK BGC](https://geoportal.statistics.gov.uk/datasets/countries-december-2022-boundaries-uk-bgc/explore)
- GeoPackage format, used for filtering POIs to UK extent
- Place in: `data/inputs/boundaries/`

**Local Authority Boundaries**
- Source: [ONS Open Geography Portal - Local Authority Districts (December 2022) Boundaries UK BGC](https://geoportal.statistics.gov.uk/datasets/local-authority-districts-december-2022-boundaries-uk-bgc/explore)
- GeoPackage format, used for assigning centres to Local Authorities
- Place in: `data/inputs/boundaries/`
