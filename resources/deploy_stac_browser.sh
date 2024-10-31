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

# The docker entrypoint will run the script 'docker/docker-entrypoint.sh'
# and create the config.js file that will contain: window.STAC_BROWSER_CONFIG = {...}
# We add a sed command to the .sh script that will modify the .js file to add
# the oauth2 configuration based on environment variables: OIDC_ENDPOINT, OIDC_REALM, PUBLIC_CLIENT_ID
#
# Note: we substitute env vars in ThisIsUsedBySed, not in "ThisGoesToEntrypointSh"
cat <<- "ThisGoesToEntrypointSh" >> docker/docker-entrypoint.sh

# This was added by https://github.com/RS-PYTHON/rs-server/tree/develop/resources/deploy_stac_browser.sh
authConfig=$(cat <<- ThisIsUsedBySed
  authConfig: { \n\
    "type": "openIdConnect", \n\
    "openIdConnectUrl": "${OIDC_ENDPOINT}/realms/${OIDC_REALM}/.well-known/openid-configuration", \n\
    "oidcConfig": { \n\
      "client_id": "${PUBLIC_CLIENT_ID}" \n\
    } \n\
  },
ThisIsUsedBySed
)
sed -i "s@\(window.STAC_BROWSER_CONFIG = {\)@\1\n$authConfig@g" /usr/share/nginx/html/config.js
ThisGoesToEntrypointSh

# Docker image tag = 'last commit hash'.'last commit date'
tag="$(git rev-parse --short HEAD).$(git log -1 --format="%at" | xargs -I{} date -d @{} +%Y-%m-%d)"

# Build Docker image with tag + latest. It will be pushed to the rs-server registry.
registry="ghcr.io/rs-python/stac-browser"
docker build -t "${registry}:latest" -t "${registry}:${tag}" .

# Push the images
docker login https://ghcr.io/v2/rs-python
docker push "${registry}:latest"
docker push "${registry}:${tag}"
