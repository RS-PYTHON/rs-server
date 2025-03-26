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
#set -x

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
BUILD_DIR="$(realpath $SCRIPT_DIR/build_base_images)"

# For each dockerfile and associated docker image name, separated by a ;
for params in \
    "Dockerfile.python;python:3.11.7-slim-bookworm" \
    "Dockerfile.jupyter;quay.io/jupyter/base-notebook:hub-5.2.1"
do
    dockerfile=$(echo $params | cut -d ";" -f 1)
    base=$(echo $params | cut -d ";" -f 2)

    # Add our hosting github organization to the docker image
    target="ghcr.io/rs-python/$base"

    # Build the docker image
    docker build \
        --build-arg BASE=${base} \
        --build-arg DASK_TAG=2024.5.2 \
        --build-arg DASK_GATEWAY_TAG=2024.1.0 \
        --build-arg PREFECT_TAG=3.2.13 \
        --build-arg PREFECT_DASK_TAG=0.3.3 \
        --progress plain \
        -f "${BUILD_DIR}/${dockerfile}" \
        -t "$target" \
        "${BUILD_DIR}"

    # Push the docker image to the registry, if the --push option is specified.
    if [[ " $@ " == *" --push "* ]]; then
        docker login https://ghcr.io/v2/rs-python
        docker push "$target"
    fi
done
