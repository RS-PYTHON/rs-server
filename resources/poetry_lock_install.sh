#!/usr/bin/env bash
set -euo pipefail

# In each subproject, run 'poetry lock --no-update' then 'poetry install --with dev'
for f in $(find . -name pyproject.toml); do
    (set -x; cd $(dirname $f) && poetry lock --no-update && poetry install --with dev)
done
