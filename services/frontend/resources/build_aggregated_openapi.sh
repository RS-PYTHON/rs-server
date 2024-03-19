#!/usr/bin/env bash

# Build the aggregated openapi.json file that then will be used to run the aggregated swagger frontend

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

services_file="${SCRIPT_DIR}/services.json" # input file = describe services
to_file="${SCRIPT_DIR}/openapi.json" # output file = aggregated json

(cd "${SCRIPT_DIR}" && poetry run python -m tools.openapi "$services_file" "$to_file")

echo "Aggregated openapi generated under: '$to_file'"
