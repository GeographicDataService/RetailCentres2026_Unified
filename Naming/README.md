# Retail Centre Naming Pipeline

Python pipeline for assigning place names and classifications to UK retail centre boundaries. Re-implementation of the original R pipeline (`Retail-Centre-Boundaries/Code/`), using Foursquare POI data in place of VOA/LDC sources.

## Pipeline

Run the stages **in this order** from `Naming/`:

| Step | Command | Purpose |
|------|---------|---------|
| 0 (setup, once) | `python download_data.py` | Download reference boundary data into `data/` (see [Acquiring Input Data](#acquiring-input-data)) |
| 1 | `python naming.py` | Build the naming lookup tables → `exports/RC_Naming_*.csv` |
| 2 | `python generate_names.py` | Assemble the final names → `exports/rc2025_named.{gpkg,parquet}` |

Stages 1 and 2 can be run together with the orchestrator:

```bash
python 0_run_all.py
```

Stage detail:

1. **`naming.py`** — Builds naming lookup tables by spatially matching centres against reference boundaries and gazetteers:
   - ONS naming (LA, County, Region, Neighbourhood)
   - OS Open Names nearest and internal place search
   - Street naming from Foursquare POI addresses
   - OSM retail park names
   - OSM neighbourhood names

2. **`generate_names.py`** — Combines the lookup tables to assemble final names, applying classification hierarchy, name formatting, duplicate disambiguation, and sub-area naming.

## Input Data

The main input is a set of pre-delineated and pre-classified retail centre polygons with Foursquare POI data joined.

### Acquiring Input Data

Everything the pipeline reads lives in `data/` and comes from one of four places.

#### 1. Pipeline hand-off inputs (from the upstream stages)

| File | Description | Where it comes from |
|------|-------------|---------------------|
| `rc2025_foursquare_LondonMannual.gpkg` | Pre-delineated, pre-classified retail centre polygons (EPSG:27700); also carries pre-joined Local Authority / County / Region columns | Output of the **Classification** stage; `run_all.sh` copies it here |
| `foursquare_quality_retail_filtered.parquet` | Quality/retail-filtered Foursquare POI points (street/address extraction) | Output of the **Boundaries** stage |

Running the whole pipeline via the repo-root `run_all.sh` places these automatically. To run Naming standalone, copy them in from the Classification/Boundaries outputs.

#### 2. Auto-downloaded reference data — `python download_data.py`

| File | Description | Source |
|------|-------------|--------|
| `MSOA_Dec2021_EW.gpkg` | Neighbourhood geography for **England & Wales** (MSOA) | ONS Open Geography |
| `scotland/SG_IntermediateZone_2011/` | Neighbourhood geography for **Scotland** (Intermediate Zones) | Scottish Government |

#### 3. Manual downloads

| File | Description | Where to get it |
|------|-------------|-----------------|
| `os_open_names/Data/opname_gb.gpkg` | OS Open Names gazetteer (city/town/village/suburb…) | [OS Data Hub](https://osdatahub.os.uk/downloads/open/OpenNames) — download the **GeoPackage** (~2GB), extract to `data/os_open_names/` |
| `northern_ireland/`*SDZ*`.shp`/`.gpkg` | Neighbourhood geography for **Northern Ireland** (Super Data Zones 2021) | [NISRA](https://www.nisra.gov.uk/support/geography/northern-ireland-super-data-zones) — extract so a `*SDZ*` file lands under `data/northern_ireland/` |

`download_data.py` prints `[MISSING]` with instructions for any manual dataset it can't find.

#### 4. OSM-derived data

| File | Description | How to generate |
|------|-------------|-----------------|
| `retail_landuse.parquet` | OSM retail landuse polygons (retail-park naming) | `python ../Boundaries/scripts/grab_osm_landuse.py --landuse both`, then copy `retail_landuse.parquet` into `data/` |
| `osm_neighbourhoods.parquet` | OSM `place=neighbourhood/quarter` nodes (neighbourhood-name fallback) | Auto-grabbed from Overpass by `python download_data.py`; `naming.py` warns if missing |
| `osm_ni_places.parquet` | OSM `place=city/town/village/suburb/hamlet` nodes for NI (OS Open Names doesn't cover NI) | Auto-grabbed from Overpass by `python download_data.py` |

`download_data.py` skips any file already present in `data/`, so it never overwrites an existing grab. OSM is live, so a fresh grab won't byte-match an older file; delete the parquet first if you want to refresh it.

### Package Inputs

To bundle all data needed to run Naming standalone:

```bash
./make_inputs_zip.sh
```

This writes `naming_inputs.zip` with entries under `data/...`. Unzip it from
`Naming/` to restore the paths expected by `naming.py` and `generate_names.py`.

## Usage

```bash
source .venv/bin/activate
pip install geopandas fiona pandas numpy shapely pyogrio

# Run both stages in order
python 0_run_all.py

# ...or run the stages individually:
python naming.py            # Stage 1: build lookup tables
python generate_names.py    # Stage 2: assemble final names
```

Output is written to `exports/`:
- `rc2025_named.gpkg` — final named retail centres
- `rc2025_named.parquet` — same, in Parquet format
- `rc2025_naming_lookup.csv` — combined lookup table

## Other Scripts

`download_data.py` (pipeline step 0) downloads the England & Wales (MSOA) and Scottish (Intermediate Zone) neighbourhood boundaries, and grabs the OSM `osm_neighbourhoods.parquet` and `osm_ni_places.parquet` place nodes from Overpass — see [Acquiring Input Data](#acquiring-input-data).

Ad-hoc analysis/comparison utilities live in `scripts/` and are not part of the main pipeline. Run them from the project root, e.g. `python scripts/compare_names.py`:

- `scripts/compare_names.py` — compares new names against a previous version
- `scripts/compare_old_vs_new.py` — old (R) vs new (Python) centre metrics for the paper
- `scripts/naming_comparison.py` — sub-area "own centre" vs "whole area" name comparison
- `scripts/find_lcr_centres.py` — filters named centres to the Liverpool City Region
