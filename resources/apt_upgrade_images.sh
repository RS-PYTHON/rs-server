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

# Run "apt update && apt upgrade -y" in docker images that are used in our ci/cd

set -euo pipefail
set -x

images=\
"python:3.11.7-slim-bookworm "\
"jupyter/minimal-notebook:latest "\
"quay.io/jupyter/base-notebook:hub-4.1.5"\

# Target images will be:
# ghcr.io/rs-python/python:3.11.7-slim-bookworm
# ghcr.io/rs-python/jupyter/minimal-notebook:latest
# ghcr.io/rs-python/quay.io/jupyter/base-notebook:hub-4.1.5

dockerdir="/tmp/dockerfile"
dockerfile="$dockerdir/Dockerfile"
mkdir -p "$dockerdir"
cd "$dockerdir"

# For each docker image
for image in $images; do

    # Save the default user in the image
    user=$(docker run --rm --entrypoint whoami "$image")

    # Add our hosting github organization to the docker image
    target="ghcr.io/rs-python/$image"

    # Create a tmp Dockerfile that pulls and update the image.
    cat << EOF > "$dockerfile"
FROM $image
USER root
RUN apt update && apt upgrade -y
USER $user

# Upgrade pip version
RUN pip install -U pip

# Set labels based on the Open Containers Initiative (OCI):
# https://github.com/opencontainers/image-spec/blob/main/annotations.md#pre-defined-annotation-keys
#
LABEL org.opencontainers.image.source="https://github.com/RS-PYTHON/rs-server"
LABEL org.opencontainers.image.ref.name="$target"
LABEL dockerfile.url="https://github.com/RS-PYTHON/rs-server/blob/develop/resources/apt_upgrade_images.sh"

# Note: don't remove cache so the child images that use this one as a base will build faster
# RUN rm -rf /var/cache/apt/archives /var/lib/apt/lists/*
EOF

    # For the jupyter images
    if [[ $image == *"jupyter"* ]]; then

        DASK_TAG=2024.5.2
        DASK_GATEWAY_TAG=2024.1.0
        PREFECT_TAG=3.1.4
        PREFECT_DASK_TAG=0.3.3

        cat << EOF >> "$dockerfile"

# Install python 3.11.7 using conda then prefect and dask and other packages.
# The versions must be the same than the cluster images.
RUN conda install --yes conda-forge::python="3.11.7"

# Note: put s3fs before boto3 to have a recent version
RUN pip install \
        dask[complete]=="${DASK_TAG}" \
        distributed=="${DASK_TAG}" \
        dask-gateway=="${DASK_GATEWAY_TAG}" \
        prefect[aws]=="${PREFECT_TAG}" \
        prefect-dask=="${PREFECT_DASK_TAG}" \
        ipywidgets \
        s3fs \
        boto3

# Install dot and clean conda
USER root
RUN apt install -y python3-pydot graphviz
RUN conda clean --all --yes
USER jovyan
EOF
    fi

    cat "$dockerfile"

    # Build and publish the image
    docker build --progress plain -f "$dockerfile" -t "$target" "$dockerdir"
    docker push "$target"
done
