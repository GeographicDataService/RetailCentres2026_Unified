#!/usr/bin/env bash
# Bundle the Boundaries pipeline's required inputs into boundaries_inputs.zip.
# Run from anywhere. Zip entries are data/inputs/... so unzip from Boundaries/
# to restore the paths expected by src/config.py and the quality filters.
set -euo pipefail
cd "$(dirname "$0")"

FILES=(
  # Pipeline hand-off from Foursquare
  "data/inputs/poi/uk_foursquare_cc_nov_iceberg.parquet"
  # OSM land-use inputs
  "data/inputs/landuse/retail_landuse.parquet"
  "data/inputs/landuse/commercial_landuse.parquet"
  "data/inputs/landuse/industrial_landuse.parquet"
  # Administrative boundaries used by filtering/postprocessing
  "data/inputs/boundaries/Countries_December_2022_UK_BGC_1943732719298389253.gpkg"
  "data/inputs/boundaries/Local_Authority_Districts_December_2022_UK_BGC_V2_5759908710055972638.gpkg"
  # Optional for --legacy-ids postprocessing, used by root run_all.sh
  "data/inputs/legacy_rc_bounds.parquet"
)

DIRS=(
  # ONSPD is read as a directory of postcode CSV chunks.
  "data/inputs/onspd"
)

missing=0
for f in "${FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "MISSING: $f"
    missing=1
  fi
done
for d in "${DIRS[@]}"; do
  if [[ ! -d "$d" ]]; then
    echo "MISSING: $d"
    missing=1
  elif ! find "$d" -type f -name '*.csv' -print -quit | grep -q .; then
    echo "MISSING CSV FILES IN: $d"
    missing=1
  fi
done
[[ $missing -eq 0 ]] || { echo "Aborting: required inputs missing (see above)."; exit 1; }

rm -f boundaries_inputs.zip
zip -q -X -r boundaries_inputs.zip "${FILES[@]}" "${DIRS[@]}"

echo
echo "Wrote boundaries_inputs.zip ($(du -h boundaries_inputs.zip | cut -f1))"
