#!/usr/bin/env bash
# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

# Run pytest in each sub-project directory.
# We cannot run it once from the main directory because some sub-project may have dependency conflicts,
# and because we have a 'ImportError while loading conftest' when several sub-projects implement
# a 'conftest' file.

# Remove the existing coverage reports
(set -x; rm -rf ./.coverage ./cov-report.xml ./junit-xml-report.xml)

# For each pyproject.toml file in the current directory
for toml in $(find "$ROOT_DIR" -name pyproject.toml | sort); do

    # Go to the parent dir = project dir
    proj_dir=$(dirname "$toml")

    # Test if the 'tests' directory exists
    tests_dir="$proj_dir/tests"
    if [[ ! -d "$tests_dir" ]]; then
        continue
    fi

    # Install dependencies
    (set -x
        cd "$proj_dir" && poetry install --with dev
        poetry run opentelemetry-bootstrap -a install || true
    )

    # Test if the directory has at least one test (see: https://stackoverflow.com/a/57014262)
    if [[ $(cd "$proj_dir" && poetry run pytest --collect-only -q | head -n -2 | wc -l) == 0 ]]; then
        echo "Skip '$tests_dir' (no tests implemented)"
        continue
    fi
    echo "Test '$tests_dir'"

    # Subshell
    (
        # Read the .env file if it exists
        if [[ -f "$tests_dir/.env" ]]; then
            set -x; source "$tests_dir/.env"; set +x
        fi

        # Run pytest from the root directory. Update the coverage reports.
        cd "$ROOT_DIR"
        relative_path=$(realpath "$proj_dir" --relative-to "$ROOT_DIR")
        cmd="poetry \
--directory $proj_dir run pytest $tests_dir \
-s --disable-pytest-warnings \
--durations=0 \
--error-for-skips \
--cov=$relative_path \
--cov-report=term \
--cov-report=xml:./cov-report.xml \
--junit-xml=./junit-xml-report.xml \
--cov-append \
"
        trap "echo FAILED COMMAND: $cmd" EXIT # print the command if it fails
        (set -x; $cmd) # run command
        trap - EXIT # clear trap
    )
    echo "Finished testing '$tests_dir'"
done
