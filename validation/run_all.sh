#!/usr/bin/env bash
# Validation and sensitivity analyses behind the paper (Sections 3.4 and 4.2-4.3, Tables 4 and 5).
# Run from the repo root:  bash validation/run_all.sh     Outputs go to validation/outputs/<step>/.
#
# Uses what is already on disk; the one-off preparation in validation/prep/ is NOT re-run here:
#   fetch_planning.py, digitise_cardiff.py    planning designations, into validation/data/
#   rerun_quality_filters.py, run_sensitivity.sh, run_postcode_sensitivity.sh
#                                             the Boundaries runs for the sensitivity analysis (hours, ~29 GB peak)
#   build_audit.py, label_server.py           drawing and hand-labelling the audit sample
set -e
PY=.venv/bin/python

$PY validation/planning.py       # 1. planning designations: Table 4, Figure 7
$PY validation/retail_parks.py   # 2. retail parks against OS Points of Interest
$PY validation/audit.py          # 3. audit of random samples
$PY validation/sensitivity.py    # 4. parameter sensitivity and Leiden stability: Table 5
$PY validation/postcode.py       # 5. postcode check by country and urban/rural
