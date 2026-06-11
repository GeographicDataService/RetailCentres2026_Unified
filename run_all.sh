#!/usr/bin/env bash
# Run all stages. Usage: ./run_all.sh <run_name>   (run from the repo root)
set -e
RUN="$1"

# Stage 0: retrieve the UK Foursquare POI input (needs FOURSQUARE_ICEBERG_TOKEN in
# Foursquare_POI_retrieval/.env). Output is copied into Boundaries' inputs.
cd Foursquare_POI_retrieval
./run_foursquare.sh
cp data/processed/uk_foursquare_cc_nov_iceberg.parquet ../Boundaries/data/inputs/poi/uk_foursquare_cc_nov_iceberg.parquet

cd ../Boundaries
python src/main.py --run_name "$RUN"
python scripts/boundary_postprocessing.py --run-dir data/outputs/runs/$RUN --output-dir data/outputs/boundary_postprocessing/$RUN --legacy-ids
cp data/outputs/boundary_postprocessing/$RUN/postworkshopcentres.gpkg ../Classification/geo/postworkshopcentres_wgs84.gpkg

cd ../Classification
python 0_run_all.py
cp output/rc2025_foursquareAnchors_LondonMannual.gpkg ../Naming/data/rc2025_foursquare_LondonMannual.gpkg

cd ../Naming
python naming.py
python generate_names.py
