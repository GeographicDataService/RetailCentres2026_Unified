# Retail Centres — Unified Workspace

A single git repository bundling the three active UK Retail Centre projects under one shared Python environment:

| Subfolder | Purpose | Main entry point |
|-----------|---------|------------------|
| [`Boundaries/`](Boundaries/) | Boundary generation from Foursquare POI + OSM landuse | [`Boundaries/src/main.py`](Boundaries/src/main.py) |
| [`Classification/`](Classification/) | Classification, lookup tables, retail counts (config-driven) | [`Classification/0_run_all.py`](Classification/0_run_all.py) |
| [`Naming/`](Naming/) | Place-name & classification assignment for centre polygons | [`Naming/naming.py`](Naming/naming.py) |

This repository was unified from three previously separate projects (`RetailCentres`, `RetailCenter`, `RetailCentres_Naming`), renamed to `Boundaries`, `Classification`, and `Naming`. Their full commit histories are preserved in this repo. The canonical originals at `/home/ogoodwin/projects/{RetailCentre,RetailCentres,RetailCentres_Naming}/` are unmodified. `RetailCentres_Paper` (the Quarto manuscript) is intentionally excluded.

## Code Structure
```
RetailCentres_Unified2/
├── .venv/                         # single shared venv (uv-managed)
├── pyproject.toml                 # union of deps from all three subprojects
├── .python-version                # 3.12
├── README.md                      # this file
│
├── Boundaries/                    # boundary generation toolkit
│   ├── src/
│   │   ├── main.py                # parameter sweep workflow
│   │   ├── generate_networks.py   # core orchestrator
│   │   ├── retail/                # POI filtering, clustering, postprocessing
│   │   └── utils/
│   ├── data/                      # inputs / intermediate / outputs
│   ├── notebooks/, scripts/, tests/, docs/
│   ├── method.md                  # methodology doc
│   └── pyproject.toml             # subproject manifest (kept for reference)
│
├── Classification/                # classification pipeline
│   ├── 0_run_all.py               # main entry point
│   ├── config.yaml                # all paths and settings
│   ├── rc_classification.py
│   ├── rc_classification_rank.py / rc_classification_rerank.py
│   ├── rc_id_lookup_build.py / rc_lookup.py / rc_ldcN.py
│   └── *.ipynb                    # exploratory notebooks
│
└── Naming/                        # naming pipeline
    ├── naming.py                  # stage 1: build lookup tables
    ├── generate_names.py          # stage 2: assemble final names
    ├── download_data.py           # ONS / Scottish / NI reference data
    ├── compare_names.py / naming_comparison.py
    ├── data/                      # reference boundaries, POI, gazetteers
    └── exports/                   # final named centres (.gpkg, .parquet, .csv)
```

## How to Run

### Installation

A single shared venv at the workspace root services all three subprojects.

```bash
# From RetailCentres_Unified2/
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

The `pyproject.toml` is the union of dependencies from all three subprojects. After install, every script in every subfolder runs against this same `.venv`.

Fallback (no `uv`):
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run Pipelines

**Boundary generation** (`Boundaries/`):
```bash
# Basic run — parameters in Boundaries/src/config.py
python Boundaries/src/main.py --run_name "test_run"

# With pre-saved quality filters (faster)
python Boundaries/src/main.py --run_name "test_run" --use_presaved_filters
```
See [`Boundaries/method.md`](Boundaries/method.md) for methodology and [`Boundaries/README.md`](Boundaries/README.md) for input-data acquisition (Foursquare POI, OSM landuse, ONSPD, LAD boundaries).

**Classification** (`Classification/`):
```bash
cd Classification
python 0_run_all.py
```
All paths and settings live in [`Classification/config.yaml`](Classification/config.yaml). The pipeline (1) builds the old→new `RC_ID` lookup, (2) builds LAD/county/region/BUA lookup attributes, (3) counts retail activity per polygon, (4) runs the final classification → GeoPackage. The `RC_ID` lookup step normally only needs to be run once per boundary set.

**Naming** (`Naming/`):
```bash
cd Naming
python naming.py             # stage 1: build lookup tables
python generate_names.py     # stage 2: assemble final names
```
Reference data fetch:
```bash
python Naming/download_data.py
```
**OS Open Names** (~2 GB) needs a manual download from [OS Data Hub](https://osdatahub.os.uk/downloads/open/OpenNames); extract to `Naming/data/os_open_names/`. Outputs land in `Naming/exports/`.

### Testing
```bash
pytest Boundaries/tests
```

## Acquiring Input Data

Each subproject has its own input-data needs documented in its own README. The most data-heavy is `Boundaries/`:

- **GeoDS members:** packaged inputs zip on SharePoint — see [`Boundaries/README.md`](Boundaries/README.md) → *Quick Start (GeoDS Members)*.
- **Manual:** Foursquare POI, OSM landuse (via `python Boundaries/src/grab_osm_landuse.py --landuse both`), ONSPD postcodes, ONS Local Authority + Country boundaries.

`Classification/` consumes pre-delineated boundaries plus an LDC historical-snapshot CSV — paths configured in `Classification/config.yaml`. `Naming/` consumes the classified centre polygons output by `Classification/`, plus the gazetteers fetched by `download_data.py`.

## Notes

- The canonical originals at `/home/ogoodwin/projects/RetailCenter`, `/home/ogoodwin/projects/RetailCentres`, and `/home/ogoodwin/projects/RetailCentres_Naming` remain unchanged; this unified repo carries copies of their source plus their preserved git histories.
- `.venv/`, `cache/`, `__pycache__/`, and `.ipynb_checkpoints/` were excluded during the copy and are regenerated on demand.
- Each subfolder retains its own original `README.md` — refer to those for project-specific details.
