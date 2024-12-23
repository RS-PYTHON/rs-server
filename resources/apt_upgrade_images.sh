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

dockerdir="/tmp/dockerfile"
dockerfile="$dockerdir/Dockerfile"
mkdir -p "$dockerdir"
cd "$dockerdir"

# For each docker image
for image in $images; do

    # Save the default user in the image
    user=$(docker run --rm --entrypoint whoami "$image")

    # Create a tmp Dockerfile that pulls and update the image.
    cat << EOF > "$dockerfile"
FROM $image
USER root
RUN apt update && apt upgrade -y
USER $user

# Note: don't remove cache so the child images that use this one as a base will build faster
# RUN rm -rf /var/cache/apt/archives /var/lib/apt/lists/*
EOF

    cat "$dockerfile"

    # Add our hosting github organization to the docker image
    target="ghcr.io/rs-python/$image"

    # Build and publish the image
    docker build -f "$dockerfile" -t "$target" "$dockerdir"
    docker push "$target"
done
