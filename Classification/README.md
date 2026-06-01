# Retail Centre Pipeline

This repo builds retail-centre lookup tables, counts retail activity, and runs the final centre classification.

Note: the old-to-new `RC_ID` lookup does not need to be rebuilt every time. It normally only needs to be run once for a given set of retail-centre boundaries. After that, the `build_rcid_lookup(...)` step in [0_run_all.py](0_run_all.py) can be skipped unless the source retail-centre polygons change.

## What It Does

Running the pipeline does 4 things:

1. Build the old-to-new `RC_ID` lookup.
2. Build retail-centre lookup attributes such as LAD, county, region, and BUA.
3. Count retail activity for each retail-centre polygon.
4. Run the final classification and export the result to a GeoPackage.

## Main Files

- [0_run_all.py](0_run_all.py): main entry point
- [config.yaml](config.yaml): all input/output paths and settings
- [rc_classification.py](rc_classification.py): classification logic

## Source Files

With the current [config.yaml](config.yaml), the main input source files are:

- retail-centre polygons: `geo/postworkshopcentres_wgs84.gpkg`
- old retail-centre polygons for ID matching: `geo/old_retail_mapmaker/Retail_Boundaries_UK.gpkg`
- LAD boundaries: `geo/LA/Local_Authority_Districts_May_2024_Boundaries_UK_BFE_-5758551109064458912/LAD_MAY_2024_UK_BFE.shp`
- county boundaries: `geo/Counties/uk_27700.shp`
- region boundaries: `geo/Regions/GB_regions.shp`
- built-up area boundaries: `geo/buildup/merged_BUA_dissolved2025.gpkg`
- LDC input points: `data/LDC_Historical_snapshot_2015-01-01-2025-09-30.csv`
- London town centre boundaries: `geo/london_town_centre/London_Town_Centres_Boundaries.gpkg`

## Requirements

This project expects a Python environment with geospatial packages installed.

At minimum you will need:

- `pandas`
- `geopandas`
- `shapely`
- `pyyaml`

Depending on your environment, `geopandas` may also require Fiona / GDAL / pyogrio.

## Before Running

Check [config.yaml](config.yaml) and make sure these paths are correct:

- retail-centre boundary file
- old retail boundary file
- LAD / county / region / BUA files
- LDC input CSV
- output paths
- London town centre boundary file, if using the London manual override

Important config fields:

- `rc_lookup.rc_path`
- `rc_id_lookup.new_rc_path`
- `rc_classification_ldc_numbers_comparison.rc_path`
- `rc_classification.split_path`
- `rc_classification.retailN_col`
- `rc_classification.london_town_centres_path`

## Run

From the project root:

```bash
python 0_run_all.py
```

This reads `config.yaml` automatically.

## Outputs

The main outputs written by the pipeline are:

- RC lookup table
- RC_ID lookup table
- retail-centre retail counts
- final classified retail-centre GeoPackage

With the current config, the final classification output is controlled by:

- `rc_classification.output_gpkg`

## London Manual Override

The London step does a manual override after the split-level London reranking.

- It matches retail-centre polygons to the London town centre boundary file by polygon overlap and `sitename`.
- Metropolitan London centres can be promoted to `Major Town Centre`.
- Only the largest matched polygon by `tr_retailN` is promoted for each matched metropolitan centre.
- Matched non-metropolitan centres are only downgraded if they were already `Major Town Centre`.
- Retail parks and shopping centres are excluded from this override.
- `RC_ID 898` is manually kept as a London major centre because Brent Cross is not present in the London boundary name list.

## Notes

- The pipeline is config-driven, so path changes should normally be made in [config.yaml](config.yaml), not in the Python files.
- The current workflow uses `tr_retailN` as the default internal metric, but the actual run is still controlled by `rc_classification.retailN_col` in the config.
- The `notebooks/` folder holds exploratory/analysis notebooks. They are not part of the pipeline and are not run by `0_run_all.py`.
