#!/usr/bin/env bash
# Bundle the Naming pipeline's required inputs into naming_inputs.zip.
# Run from anywhere. Zip entries are data/... so unzip from Naming/ to restore
# the paths expected by naming.py and generate_names.py.
set -euo pipefail
cd "$(dirname "$0")"

FILES=(
  # Pipeline hand-offs
  "data/rc2025_foursquare_LondonMannual.gpkg"
  "data/foursquare_quality_retail_filtered.parquet"
  "data/retail_landuse.parquet"
  # Downloaded/generated reference data
  "data/MSOA_Dec2021_EW.gpkg"
  "data/osm_neighbourhoods.parquet"
  "data/osm_ni_places.parquet"
)

DIRS=(
  # Manual / extracted reference datasets
  "data/os_open_names"
  "data/northern_ireland"
  "data/scotland/SG_IntermediateZone_2011"
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
  fi
done
if [[ -d "data/os_open_names" && ! -f "data/os_open_names/Data/opname_gb.gpkg" ]]; then
  echo "MISSING: data/os_open_names/Data/opname_gb.gpkg"
  missing=1
fi
if [[ -d "data/northern_ireland" ]] && ! find data/northern_ireland -type f \( -iname '*SDZ*.shp' -o -iname '*SDZ*.gpkg' \) -print -quit | grep -q .; then
  echo "MISSING SDZ SHP/GPKG IN: data/northern_ireland"
  missing=1
fi
if [[ -d "data/scotland/SG_IntermediateZone_2011" ]] && ! find data/scotland/SG_IntermediateZone_2011 -type f -iname '*IntermediateZone*.shp' -print -quit | grep -q .; then
  echo "MISSING IntermediateZone SHP IN: data/scotland/SG_IntermediateZone_2011"
  missing=1
fi
[[ $missing -eq 0 ]] || { echo "Aborting: required inputs missing (see above)."; exit 1; }

rm -f naming_inputs.zip
zip -q -X -r naming_inputs.zip "${FILES[@]}" "${DIRS[@]}"

echo
echo "Wrote naming_inputs.zip ($(du -h naming_inputs.zip | cut -f1))"
