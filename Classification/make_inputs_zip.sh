#!/usr/bin/env bash
# Bundle the Classification pipeline's required inputs into classification_inputs.zip.
# Run from the Classification/ directory. Paths are relative so the zip entries are
# geo/... — unzip it from Classification/ to restore everything where config.yaml expects.
set -euo pipefail
cd "$(dirname "$0")"

LAD_DIR="geo/LA/Local_Authority_Districts_May_2024_Boundaries_UK_BFE_-5758551109064458912"

FILES=(
  # Pipeline hand-offs
  "geo/postworkshopcentres_wgs84.gpkg"
  "geo/old_retail_mapmaker/Retail_Boundaries_UK.gpkg"
  "geo/foursquare_quality_retail_filtered.parquet"
  # Boundary downloads (shapefiles include all sidecars)
  "$LAD_DIR/LAD_MAY_2024_UK_BFE.shp"
  "$LAD_DIR/LAD_MAY_2024_UK_BFE.shx"
  "$LAD_DIR/LAD_MAY_2024_UK_BFE.dbf"
  "$LAD_DIR/LAD_MAY_2024_UK_BFE.prj"
  "$LAD_DIR/LAD_MAY_2024_UK_BFE.cpg"
  "$LAD_DIR/LAD_MAY_2024_UK_BFE.shp.xml"
  "geo/Counties/uk_27700.shp"
  "geo/Counties/uk_27700.shx"
  "geo/Counties/uk_27700.dbf"
  "geo/Counties/uk_27700.prj"
  "geo/Counties/uk_27700.cpg"
  "geo/Regions/GB_regions.shp"
  "geo/Regions/GB_regions.shx"
  "geo/Regions/GB_regions.dbf"
  "geo/Regions/GB_regions.prj"
  "geo/Regions/GB_regions.cpg"
  # Derived
  "geo/buildup/merged_BUA_dissolved2025.gpkg"
  # London override
  "geo/london_town_centre/London_Town_Centres_Boundaries.gpkg"
)

# Fail loudly if anything is missing before we start zipping.
missing=0
for f in "${FILES[@]}"; do
  if [[ ! -f "$f" ]]; then echo "MISSING: $f"; missing=1; fi
done
[[ $missing -eq 0 ]] || { echo "Aborting: required inputs missing (see above)."; exit 1; }

rm -f classification_inputs.zip
zip -q -X classification_inputs.zip "${FILES[@]}"
echo
echo "Wrote classification_inputs.zip ($(du -h classification_inputs.zip | cut -f1))"
