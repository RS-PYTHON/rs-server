#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

# In each subproject, install dependencies with poetry
for f in $(find "$ROOT_DIR" -name pyproject.toml); do
    (set -x
        cd $(dirname $f) && poetry lock && poetry install --with dev
        poetry run opentelemetry-bootstrap -a install || true # install otel instrumentation packages for dependencies
    )
done
