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

# Build, customize and deploy the latest STAC browser version

set -euo pipefail
#set -x

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

# Git clone the project under /tmp, or 'git reset --hard' it if already exists
cd /tmp
if [[ -d "stac-browser" ]]; then
    cd "stac-browser"
    read -p "Reset --hard the '$(pwd)' directory [y/n]? " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Exiting..."
        exit 1
    fi
    git reset --hard
    git pull
else
    git clone "git@github.com:radiantearth/stac-browser.git"
    cd "stac-browser"
fi

registry="ghcr.io/rs-python/stac-browser"

# Set labels based on the Open Containers Initiative (OCI):
# https://github.com/opencontainers/image-spec/blob/main/annotations.md#pre-defined-annotation-keys
cat << EOF >> "Dockerfile"
LABEL org.opencontainers.image.source="https://github.com/RS-PYTHON/rs-server"
LABEL org.opencontainers.image.ref.name="$registry"
LABEL dockerfile.url="https://github.com/RS-PYTHON/rs-server/blob/develop/resources/deploy_stac_browser.sh"
EOF

# Docker image tag = 'last commit hash'.'last commit date'
tag="$(git rev-parse --short HEAD).$(git log -1 --format="%at" | xargs -I{} date -d @{} +%Y-%m-%d)"

# Build Docker image with tag + latest. It will be pushed to the rs-server registry.
docker build -t "${registry}:latest" -t "${registry}:${tag}" .

# Push the images
docker login https://ghcr.io/v2/rs-python
docker push "${registry}:latest"
docker push "${registry}:${tag}"
