#!/usr/bin/env bash
# Item 3: one-at-a-time perturbation runs + Leiden seed runs of the Boundaries stage.
# Each run is split=1500 only, uses the presaved quality filters regenerated from the published run
# (validation/prep/rerun_quality_filters.py), and writes runs/val2_<name>/.
# Runs that already have a 4_finalcentres_las.parquet are skipped, so this is safe to re-launch.
# Usage (repo root):  validation/prep/run_sensitivity.sh [N_PARALLEL]
# Each run peaks at ~11 GB RAM; on a 31 GB machine N_PARALLEL=3 gets runs OOM-killed, so keep it at 2.
set -uo pipefail
cd "$(dirname "$0")/../Boundaries"
PAR=${1:-2}
PREFIX=val2
IDS=$(realpath ../validation/outputs/quality_rerun/data/intermediate/poi_filtered/quality_filter_ids.parquet)
LOGS=../validation/logs
mkdir -p "$LOGS"

# Minimum POIs per centre is enforced twice (initial network filter and the post-park-split
# MIN_REMAINDER_POIS check), so the network runs move both; lowering only the first sends the extra
# small networks down the no-adjacent-park fallback in integrate_retail_parks.assign_networks_to_parks.
RUNS=(
  "baseline       RANDOM_SEED=505"
  "split_750      PARAM_SWEEP_SPLIT_THRESHOLD=[750]"
  "split_1125     PARAM_SWEEP_SPLIT_THRESHOLD=[1125]"
  "split_1875     PARAM_SWEEP_SPLIT_THRESHOLD=[1875]"
  "split_2250     PARAM_SWEEP_SPLIT_THRESHOLD=[2250]"
  "brand_0.025    RETAIL_PARK_MIN_RATIO=0.025"
  "brand_0.0375   RETAIL_PARK_MIN_RATIO=0.0375"
  "brand_0.0625   RETAIL_PARK_MIN_RATIO=0.0625"
  "brand_0.075    RETAIL_PARK_MIN_RATIO=0.075"
  "area_0.0035    RETAIL_PARK_MIN_AREA_SQKM=0.0035"
  "area_0.00525   RETAIL_PARK_MIN_AREA_SQKM=0.00525"
  "area_0.00875   RETAIL_PARK_MIN_AREA_SQKM=0.00875"
  "area_0.0105    RETAIL_PARK_MIN_AREA_SQKM=0.0105"
  "cell_1         PARAM_SWEEP_MIN_RETAIL_IN_CELL=[1]"
  "cell_3         PARAM_SWEEP_MIN_RETAIL_IN_CELL=[3]"
  "network_5 PARAM_SWEEP_MIN_RETAIL_IN_NETWORK=[5] MIN_REMAINDER_POIS=5"
  "network_8 PARAM_SWEEP_MIN_RETAIL_IN_NETWORK=[8] MIN_REMAINDER_POIS=8"
  "network_13 PARAM_SWEEP_MIN_RETAIL_IN_NETWORK=[13] MIN_REMAINDER_POIS=13"
  "network_15 PARAM_SWEEP_MIN_RETAIL_IN_NETWORK=[15] MIN_REMAINDER_POIS=15"
  "landuse_60     LANDUSE_OVERLAP_THRESHOLD=60.0"
  "landuse_70     LANDUSE_OVERLAP_THRESHOLD=70.0"
  "landuse_80     LANDUSE_OVERLAP_THRESHOLD=80.0"
  "landuse_90     LANDUSE_OVERLAP_THRESHOLD=90.0"
  "exempt_10      LANDUSE_MIN_POIS_EXEMPT=10"
  "exempt_15      LANDUSE_MIN_POIS_EXEMPT=15"
  "exempt_25      LANDUSE_MIN_POIS_EXEMPT=25"
  "exempt_30      LANDUSE_MIN_POIS_EXEMPT=30"
  "res_0.075      LEIDEN_RESOLUTION=0.075"
  "res_0.1125     LEIDEN_RESOLUTION=0.1125"
  "res_0.1875     LEIDEN_RESOLUTION=0.1875"
  "res_0.225      LEIDEN_RESOLUTION=0.225"
  # retail land-use nodes: polygons need >= N POIs (published 1); 0 keeps all polygons, off keeps none
  "lupoly_0       FILTER_RETAIL_LANDUSE=False"
  "lupoly_2       MIN_POIS_PER_LANDUSE_POLYGON=2"
  "lupoly_3       MIN_POIS_PER_LANDUSE_POLYGON=3"
  "lupoly_off     MIN_POIS_PER_LANDUSE_POLYGON=1000000000"
)
for s in $(seq 1 20); do RUNS+=("seed_$s LEIDEN_SEED=$s"); done

run_one() {
  local name=$1; shift
  local sets=(); for o in "$@"; do sets+=(--set "$o"); done
  if ls data/outputs/runs/${PREFIX}_"$name"/*/4_finalcentres_las.parquet >/dev/null 2>&1; then
    echo "skip $name"; return
  fi
  echo "start $name $(date +%T)"
  ../.venv/bin/python src/main.py --run_name "${PREFIX}_$name" --use_presaved_filters \
    --set "FILTER_IDS_PATH='$IDS'" \
    --set "PARAM_SWEEP_SPLIT_THRESHOLD=[1500]" "${sets[@]}" > "$LOGS/${PREFIX}_$name.log" 2>&1
  echo "done $name exit=$? $(date +%T)"
}

for r in "${RUNS[@]}"; do
  read -r name overrides <<< "$r"
  # split runs override the default split, so their override must come last (it does: later --set wins)
  while [ "$(jobs -rp | wc -l)" -ge "$PAR" ]; do wait -n; done
  # shellcheck disable=SC2086  # overrides are space-separated KEY=VALUE tokens
  run_one "$name" $overrides &
done
wait
echo "all done $(date +%T)"
