#!/usr/bin/env bash
# Generate the UK Foursquare POI file that feeds the Boundaries pipeline.
# Usage: ./run_foursquare.sh            (run from this folder; root .venv activated)
#
# Requires a Foursquare ICEBERG token in .env (copy .env.example -> .env and fill in
# FOURSQUARE_ICEBERG_TOKEN). See README.md for where to obtain it.
set -e

FILENAME="uk_foursquare_cc_nov_iceberg"
COUNTRYCODE="GB"   # ISO code for the United Kingdom

# Stage 1: query Foursquare via the ICEBERG catalog -> data/raw/<FILENAME>.gpkg
python src/query_foursquare_bycc_iceberg.py --countrycode "$COUNTRYCODE" --filename "$FILENAME"

# Stage 2: normalise + explode categories -> data/processed/<FILENAME>.parquet
#          This is the file Boundaries consumes (Foursquare-native fields only; the old
#          census-attribution stage was dropped as nothing downstream reads those columns).
python src/clean_foursquare.py --filename "$FILENAME"

echo
echo "Done. Hand off to Boundaries with:"
echo "  cp data/processed/${FILENAME}.parquet ../Boundaries/data/inputs/poi/${FILENAME}.parquet"
