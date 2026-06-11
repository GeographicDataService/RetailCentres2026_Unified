# Retail Centres — Unified Workspace (2026)

A single repository for the four subprojects of the 2026 GeoDS UK Retail Centres.
**Authors:** Owen Goodwin (owen.goodwin@liverpool.ac.uk), Carol Yin (carolyin@liverpool.ac.uk)

**Method adapted from:** [Open Retail Centres: A National Open Data Set of Retail Centre Boundaries and Indicators](https://www.nature.com/articles/s41597-022-01556-3) — *Nature Scientific Data* (2022)

<img width="1407" height="726" alt="UK retail centre boundaries" src="https://github.com/user-attachments/assets/57fa2bca-145c-400d-ab2b-0883a24c748e" />

The repository is made out of 4 separate subprojects which should be run in turn to produce the final data product:

| # | Subfolder | Purpose |
|---|-----------|---------|
| 1 | [`Foursquare_POI_retrieval/`](Foursquare_POI_retrieval/) | Retrieves & cleans the UK Foursquare POI file that feeds Boundaries |
| 2 | [`Boundaries/`](Boundaries/) | Identifies the centres & defines the centre bounds |
| 3 | [`Classification/`](Classification/) | Classifies the centres into a hierarchy based on size and rank in LAD/BUA |
| 4 | [`Naming/`](Naming/) | Assigns each centre a unique name |


## Code Structure
```
├── .venv/                         # single shared venv (uv-managed)
├── pyproject.toml                 # union of deps from all four subprojects
├── .python-version                # 3.12
├── README.md                      # this file
│
├── Foursquare_POI_retrieval/      # upstream POI retrieval (feeds Boundaries)
│   ├── run_foursquare.sh          # 2-stage wrapper (query → clean)
│   ├── src/                       # query_foursquare_bycc_iceberg / clean_foursquare
│   ├── pipelines/                 # params.yaml (filename / country code)
│   └── data/                      # POI inputs/outputs (gitignored)
│
├── Boundaries/                    # boundary generation toolkit
│   ├── src/
│   │   ├── main.py                # parameter sweep workflow
│   │   ├── generate_networks.py   # core orchestrator
│   │   ├── retail/                # POI filtering, clustering, postprocessing
│   │   └── utils/
│   ├── data/                      # inputs / intermediate / outputs
│   ├── notebooks/, scripts/, tests/, docs/
│   └── method.md                  # methodology doc
│
├── Classification/                # classification pipeline
│   ├── 0_run_all.py               # main entry point
│   ├── config.yaml                # all paths and settings
│   ├── rc_classification.py
│   └── rc_id_lookup_build.py / rc_lookup.py / rc_foursquare_anchors.py
│
└── Naming/                        # naming pipeline
    ├── naming.py                  # stage 1: build lookup tables
    ├── generate_names.py          # stage 2: assemble final names
    ├── download_data.py           # ONS / Scottish / NI reference data
    ├── scripts/                   # compare_names.py / naming_comparison.py / ad-hoc analysis
    ├── data/                      # reference boundaries, POI, gazetteers
    └── exports/                   # final named centres (.gpkg, .parquet, .csv)
```

## How to Run

### Installation

A single shared venv at the workspace root services all four subprojects.

```bash
# From RetailCentres_Unified/
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
```

The `pyproject.toml` is the union of dependencies from all four subprojects. After install, every script in every subfolder runs against this same `.venv`.

Fallback (no `uv`):
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Run everything (single command)

[`run_all.sh`](run_all.sh) runs all stages in order (Foursquare POI retrieval → Boundaries →
Classification → Naming) and copies each stage's output into the next stage's input:

```bash
source .venv/bin/activate
./run_all.sh my_run
```

The first stage needs `FOURSQUARE_ICEBERG_TOKEN` in `Foursquare_POI_retrieval/.env`
(see [`Foursquare_POI_retrieval/README.md`](Foursquare_POI_retrieval/README.md)).

Or run the stages individually:

### Run Pipelines (individually)

**Foursquare POI retrieval** (`Foursquare_POI_retrieval/`) — *upstream of Boundaries*:
```bash
cd Foursquare_POI_retrieval
cp .env.example .env          # set FOURSQUARE_ICEBERG_TOKEN — JWT from the "Access via code"
                              # section of https://places.foursquare.com/dataset/OS%20Places/code
./run_foursquare.sh           # query → clean (November Foursquare release)
```
Generates the UK Foursquare POI parquet that Boundaries reads at
`Boundaries/data/inputs/poi/uk_foursquare_cc_nov_iceberg.parquet`. Only the Foursquare token
is needed.

**Boundary generation** (`Boundaries/`):
```bash
# Basic run — parameters in Boundaries/src/config.py
python Boundaries/src/main.py --run_name "test_run"

# With pre-saved quality filters (faster)
python Boundaries/src/main.py --run_name "test_run" --use_presaved_filters
```
See [`Boundaries/method.md`](Boundaries/method.md) for methodology and [`Boundaries/README.md`](Boundaries/README.md) for input-data acquisition (Foursquare POI, OSM landuse, ONSPD, LAD boundaries).

**Boundary post-processing** (`Boundaries/`): turn a network-generation run into the final bounds GPKGs that Classification consumes (split IDs with `Parent_ID`, optional legacy RC_ID remap):
```bash
cd Boundaries
python scripts/boundary_postprocessing.py --run-dir data/outputs/runs/test_run
# add --legacy-ids to remap workshop split-centre RC_IDs onto the IDs which match the published version (The numbering was orignally non-determistic when centres had tied POI totals)
```
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

### Input Data Zips

The Boundaries, Classification, and Naming stages rely on a large number of
auxiliary geographic datasets. The locations and access dates for these files
are documented in each project's README.

For convenience, GeoDS members can download the input zip files from SharePoint:

- **Path:** `GeoDS > Shared Documents > 1 Data Products > Product Development > RetailCentreBounds2026 > inputs`
- **Link:** [RetailCentreBounds2026 inputs](https://liveuclac.sharepoint.com/:f:/r/sites/GeoDS/Shared%20Documents/1%20Data%20Products/Product%20Development/RetailCentreBounds2026/inputs?csf=1&web=1&e=pkjJ4q)

The data needed to run the three data-dependent stages is stored as stage-level
zip files:

- `boundaries_inputs.zip`
- `classification_inputs.zip`
- `naming_inputs.zip`

Place each zip in its matching stage folder and unzip it there:

- put `boundaries_inputs.zip` in `Boundaries/`
- put `classification_inputs.zip` in `Classification/`
- put `naming_inputs.zip` in `Naming/`


### Testing
```bash
pytest Boundaries/tests
```

## Acquiring Input Data

Each subproject has its own input-data needs documented in its own README. 
