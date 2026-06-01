#!/usr/bin/env bash
# Run all stages. Usage: ./run_all.sh <run_name>   (run from the repo root)
set -e
RUN="$1"

cd Boundaries
python src/main.py --run_name "$RUN"
python scripts/boundary_postprocessing.py --run-dir data/outputs/runs/$RUN --output-dir data/outputs/boundary_postprocessing/$RUN
cp data/outputs/boundary_postprocessing/$RUN/postworkshopcentres.gpkg ../Classification/geo/postworkshopcentres_wgs84.gpkg

cd ../Classification
python 0_run_all.py
cp output/rc2025_foursquareAnchors_LondonMannual.gpkg ../Naming/data/rc2025_foursquare_LondonMannual.gpkg

cd ../Naming
python naming.py
python generate_names.py
