#!/usr/bin/env bash
# Copyright 2025 CS Group
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

# Build the base Docker images that are used in the cluster and in the ci/cd.

set -euo pipefail
set -x

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
BUILD_DIR="$(realpath $SCRIPT_DIR/../.github/scripts)"

PYTHON_VERSION=3.13.9

# For each dockerfile and associated docker image name, separated by a ;
for params in \
    "Dockerfile.python;python:${PYTHON_VERSION}-slim-bookworm" \
    "Dockerfile.jupyter;quay.io/jupyter/base-notebook:hub-5.4.2;-py${PYTHON_VERSION}" # see: https://quay.io/repository/jupyter/base-notebook?tab=tags
do
    dockerfile=$(echo $params | cut -d ";" -f 1)
    base=$(echo $params | cut -d ";" -f 2)
    suffix=$(echo $params | cut -d ";" -f 3)

    # Add our hosting github organization to the docker image
    target="ghcr.io/rs-python/${base}${suffix}"

    # Build the docker image
    docker build \
        --build-arg BASE=${base} \
        --progress plain \
        -f "${SCRIPT_DIR}/build_base_images/${dockerfile}" \
        -t "$target" \
        "${BUILD_DIR}"

    # Push the docker image to the registry, if the --push option is specified.
    if [[ " $@ " == *" --push "* ]]; then
        docker login https://ghcr.io/v2/rs-python
        docker push "$target"
    fi
done
