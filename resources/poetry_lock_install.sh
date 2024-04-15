#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

# In each subproject, run 'poetry lock' then 'poetry install --with dev'
for f in $(find "$ROOT_DIR" -name pyproject.toml); do
    (set -x; cd $(dirname $f) && poetry lock && poetry install --with dev)
done
