#!/usr/bin/env bash
# Copyright 2023-2025 Airbus, CS Group
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
set -x

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

# Run pytest in each sub-project directory.
# We cannot run it once from the main directory because some sub-projects may have dependency conflicts,
# and because we have a 'ImportError while loading conftest' when several sub-projects implement
# a 'conftest' file.

# Remove the existing coverage reports
(set -x; rm -rf ./.coverage ./cov-report.xml ./junit-xml-report*.xml)

# We must manually append the junit report
pip install --upgrade pip
pip install junitparser
junit=0

# For each pyproject.toml file in the current directory
for toml in $(find "$ROOT_DIR" -name pyproject.toml | sort); do
    echo "Running tests for directory: '$toml'"

    # Go to the parent dir = project dir
    proj_dir=$(dirname "$toml")
    proj_rel_dir=${proj_dir#"$ROOT_DIR/"}

    # Test if the 'tests' directory exists
    tests_dir="$proj_dir/tests"
    if [[ ! -d "$tests_dir" ]]; then
        continue
    fi
    echo "Test '$tests_dir'"

    # Install dependencies
    if [[ " $@ " == *" --install "* ]]; then
        (set -x
            cd "$proj_dir" && poetry install --with dev > /dev/null
            poetry -q run opentelemetry-bootstrap -a install > /dev/null || true
        )
    fi

    # Increment junit reports index
    junit=$((junit+1))

    # Subshell
    (
        # Read the .env file if it exists
        if [[ -f "$tests_dir/.env" ]]; then
            set -x; source "$tests_dir/.env"; set +x
        fi

        # Run pytest from the root directory
        cd "$ROOT_DIR"
        cmd="\
$(cd "$proj_dir" && poetry run which python) -m pytest $tests_dir \
-ra \
--disable-pytest-warnings \
--color=yes \
--durations=0 \
--durations-min=0.05 \
--error-for-skips \
--cov=$proj_rel_dir \
--cov-report=term \
--cov-report=xml:$ROOT_DIR/cov-report.xml \
--junit-xml=$ROOT_DIR/junit-xml-report-${junit}.xml \
--cov-append \
"
        trap "echo FAILED COMMAND: $cmd" EXIT # print the command if it fails
        (set -x; $cmd) # run command
        trap - EXIT # clear trap
    )
    echo "Finished testing '$tests_dir'"
done

# Merge the junit reports
cd "$ROOT_DIR"
if ls "$ROOT_DIR"/junit-xml-report-*.xml >/dev/null 2>&1; then
    junitparser merge "$ROOT_DIR"/junit-xml-report-*.xml "$ROOT_DIR/junit-xml-report.xml"
else
    echo "No JUnit reports found to merge"
    touch "$ROOT_DIR/junit-xml-report.xml" # Create an empty file to avoid SonarCloud error
fi

# Fix absolute paths in coverage report
if [[ -f "$ROOT_DIR/cov-report.xml" ]]; then
    sed -i "s|$ROOT_DIR/||g" "$ROOT_DIR/cov-report.xml"
else
    echo "No coverage report generated"
fi
