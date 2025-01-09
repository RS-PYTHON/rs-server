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
pip install junitparser
junit=0

# For each pyproject.toml file in the current directory
for toml in $(find "$ROOT_DIR" -name pyproject.toml | sort); do

    # Go to the parent dir = project dir
    proj_dir=$(dirname "$toml")

    # Test if the 'tests' directory exists
    tests_dir="$proj_dir/tests"
    if [[ ! -d "$tests_dir" ]]; then
        continue
    fi
    echo "Test '$tests_dir'"

    # Install dependencies
    (set -x
        cd "$proj_dir" && poetry install --with dev
        poetry run opentelemetry-bootstrap -a install || true
    )

    # Increment junit reports index
    junit=$((junit+1))

    # Subshell
    (
        # Read the .env file if it exists
        if [[ -f "$tests_dir/.env" ]]; then
            set -x; source "$tests_dir/.env"; set +x
        fi

        # Run pytest from the root directory. Update the coverage reports.
        cd "$ROOT_DIR"
        cmd="poetry \
--directory $proj_dir run pytest $tests_dir \
-s --disable-pytest-warnings \
--durations=0 \
--error-for-skips \
--cov=. \
--cov-report=term \
--cov-report=xml:./cov-report.xml \
--junit-xml=./junit-xml-report-${junit}.xml \
--cov-append \
"
        trap "echo FAILED COMMAND: $cmd" EXIT # print the command if it fails
        (set -x; $cmd) # run command
        trap - EXIT # clear trap
    )
    echo "Finished testing '$tests_dir'"
done

# Merge the junit reports
junitparser merge ./junit-xml-report*.xml ./junit-xml-report.xml

# There seems to be a bug in pytest cov with --cov-append.
# The last tested project is malformed in the report file.
# Use this workaround to run pytest on a dummy empty dir. This reformats the report file.
dummy="/tmp/empty-pytest"
mkdir -p $dummy
# Use the last project configuration
cmd="poetry \
--directory $proj_dir run pytest $dummy \
--cov=$dummy \
--cov-report=term \
--cov-report=xml:./cov-report.xml \
--cov-append \
"
(set -x; $cmd || true) # run command, ignore the error message that says no tests exist
