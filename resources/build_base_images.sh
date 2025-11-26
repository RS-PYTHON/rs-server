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

# Directory that contains custom requirements for the docker images
CUSTOM_REQ="$(realpath $SCRIPT_DIR/../.github/scripts)"

# We use a different python version in eopf + the dpr processors + rs-dpr-service
PYTHON_VERSION=3.13.9
PYTHON_VERSION_DPR=3.11.7

DASK_TAG=2024.5.2
DASK_GATEWAY_TAG=2024.1.0

PREFECT_TAG=3.2.13

######################
# Python and Jupyter #
######################

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
        --build-arg "BASE=${base}" \
        --progress plain \
        -f "${SCRIPT_DIR}/build_base_images/${dockerfile}" \
        -t "$target" \
        "$CUSTOM_REQ"

    # Push the docker image to the registry, if the --push option is specified.
    if [[ " $@ " == *" --push "* ]]; then
        docker login https://ghcr.io/v2/rs-python
        docker push "$target"
    fi
done

########
# Dask #
########

for python_version in $PYTHON_VERSION $PYTHON_VERSION_DPR; do

    # Checkout the dask-gateway git repository into a local ./tmp folder
    tmp="${SCRIPT_DIR}/build_base_images/tmp/dask/py${python_version}"
    mkdir -p "$tmp"
    cd "$tmp"
    git clone git@github.com:dask/dask-gateway.git || true # don't fail if already cloned
    cd dask-gateway
    git checkout "tags/$DASK_GATEWAY_TAG"
    git reset --hard

    # Refreeze Dockerfile.requirements.txt files based on Dockerfile.requirements.in
    # as in https://github.com/dask/dask-gateway/blob/main/.github/workflows/refreeze-dockerfile-requirements-txt.yaml#L34
    for matrix_image in "dask-gateway" "dask-gateway-server"; do
        (\
            cd "${matrix_image}" && \
            docker run --rm \
                --env=DASK_GATEWAY_SERVER__NO_PROXY=1 \
                --volume=$PWD:/opt/${matrix_image} \
                --workdir=/opt/${matrix_image} \
                --user=root \
                "ghcr.io/rs-python/python:${python_version}-slim-bookworm" \
                sh -c 'pip install pip-tools==7.* && pip-compile --allow-unsafe --strip-extras --upgrade --output-file=Dockerfile.requirements.txt Dockerfile.requirements.in' \
        )
        req=$(realpath "${matrix_image}/Dockerfile.requirements.txt")

        # Force the dask versions (in dask-gateway)
        sed -i "s|dask==.*|dask==${DASK_TAG}|g" "$req"
        sed -i "s|distributed==.*|distributed==${DASK_TAG}|g" "$req"
        sed -i "s|fsspec==.*|fsspec|g" "$req"

        # Comment the line that installs dask-gateway-server from sources (in dask-gateway-server).
        # We install it with pip from our Dockerfile instead.
        sed -i "s|\(^\s*dask-gateway-server\)|# \1|g" "$req"
    done

    # Copy Dockerfile requirements
    cp -t "${tmp}/dask-gateway" "${CUSTOM_REQ}/layer-cleanup.sh" "${CUSTOM_REQ}/restore-apt.sh"

    # Build our custom Dockerfile
    target="ghcr.io/rs-python/dask/dask-gateway:${DASK_GATEWAY_TAG}-py${python_version}"
    docker build \
        --build-arg "PYTHON_VERSION_BASE=${python_version}" \
        -f "${SCRIPT_DIR}/build_base_images/Dockerfile.dask" \
        -t "${target}" \
        --progress=plain \
        "${tmp}/dask-gateway"

    # Push the docker image to the registry, if the --push option is specified.
    if [[ " $@ " == *" --push "* ]]; then
        docker login https://ghcr.io/v2/rs-python
        docker push "$target"
    fi
done

###########
# Prefect #
###########

# Checkout the prefect git repository into a local ./tmp folder
tmp="${SCRIPT_DIR}/build_base_images/tmp/prefect"
mkdir -p "$tmp"
cd "$tmp"
git clone git@github.com:PrefectHQ/prefect.git || true # don't fail if already cloned
cd prefect
git checkout "tags/$PREFECT_TAG"
git reset --hard

# NOTE: build the image as in /prefect/.github/workflows/docker-images.yaml

# For each suffix and extra packages, separated by a ;
for params in \
    "-k8s;--build-arg PREFECT_EXTRAS=[redis,kubernetes]" \
    ""
do
    suffix=$(echo $params | cut -d ";" -f 1)
    prefect_extras=$(echo $params | cut -d ";" -f 2)

    # Add our hosting github organization to the docker image
    target="ghcr.io/rs-python/prefecthq/prefect:${PREFECT_TAG}-py${PYTHON_VERSION}${suffix}"

    # Build the docker image
    prefect_root="${SCRIPT_DIR}/build_base_images/tmp/prefect/prefect"
    docker build \
        --build-arg "PYTHON_VERSION=${PYTHON_VERSION}" \
        --build-arg "NODE_VERSION=$(cat .nvmrc)" \
        $prefect_extras \
        --progress plain \
        -f "${prefect_root}/Dockerfile" \
        -t "$target" \
        "$prefect_root"

    # Push the docker image to the registry, if the --push option is specified.
    if [[ " $@ " == *" --push "* ]]; then
        docker login https://ghcr.io/v2/rs-python
        docker push "$target"
    fi
done
