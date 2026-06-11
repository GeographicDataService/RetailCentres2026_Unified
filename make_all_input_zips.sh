#!/usr/bin/env bash
# Build input bundles for every pipeline stage.
#
# Output files:
#   Boundaries/boundaries_inputs.zip
#   Classification/classification_inputs.zip
#   Naming/naming_inputs.zip
set -euo pipefail
cd "$(dirname "$0")"

bash Boundaries/make_inputs_zip.sh
bash Classification/make_inputs_zip.sh
bash Naming/make_inputs_zip.sh

echo
echo "All stage input zips built."
