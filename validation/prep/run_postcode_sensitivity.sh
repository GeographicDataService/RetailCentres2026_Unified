#!/usr/bin/env bash
# Postcode-tolerance sensitivity: the quality filters re-run from scratch with a 5 km (Macdonald et al. 2022),
# 500 m and 100 m tolerance and with the postcode filter off, then a Boundaries run on each.
# The filter re-runs peak at ~29 GB, so they go one at a time; the two Boundaries runs (~11 GB each) in parallel.
# Usage (repo root):  validation/prep/run_postcode_sensitivity.sh
set -uo pipefail
cd "$(dirname "$0")/.."
LOGS=validation/logs

for a in "--postcode_m 5000" "--postcode_m 500" "--postcode_m 100" "--no_postcode"; do
  name=$([ "$a" = "--no_postcode" ] && echo postcode_off || echo "postcode_${a#--postcode_m }")
  if [ -f "validation/outputs/quality_rerun_$name/filter_table_rerun.csv" ]; then echo "skip filters $name"; continue; fi
  echo "filters $name $(date +%T)"
  # shellcheck disable=SC2086
  /usr/bin/time -v .venv/bin/python validation/prep/rerun_quality_filters.py $a > "$LOGS/quality_rerun_$name.log" 2>&1
  echo "filters $name exit=$? $(date +%T)"
done

cd Boundaries
for name in postcode_5000 postcode_500 postcode_100 postcode_off; do
  ids=$(realpath "../validation/outputs/quality_rerun_$name/data/intermediate/poi_filtered/quality_filter_ids.parquet")
  if ls data/outputs/runs/val2_"$name"/*/4_finalcentres_las.parquet >/dev/null 2>&1; then echo "skip run $name"; continue; fi
  (echo "start $name $(date +%T)"
   ../.venv/bin/python src/main.py --run_name "val2_$name" --use_presaved_filters \
     --set "FILTER_IDS_PATH='$ids'" --set "PARAM_SWEEP_SPLIT_THRESHOLD=[1500]" > "../$LOGS/val2_$name.log" 2>&1
   echo "done $name exit=$? $(date +%T)") &
done
wait
echo "all done $(date +%T)"
