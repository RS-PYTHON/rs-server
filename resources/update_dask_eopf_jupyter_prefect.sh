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

set -euo pipefail
# set -x

# Update the versions of Dask, EOPF, Jupyter and Prefect from the Docker images used by
# the docker compose (for local mode) and Kubernetes cluster (for cluster mode).

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

#
# Bash scripts, dockerfiles and github action workflows to update,
# with paths relative to the rs-server parent folder.

all_files=()

# Return realpath
_realpath(){
    realpath "${ROOT_DIR}/../$1"
}

# [local mode] [dask base image]
a=$(_realpath rs-demo/local-mode/docker/build.dask-base-local.sh) # + re-run with --push
all_files+=($a)

# [local mode] [dask eopf]
b=$(_realpath rs-demo/local-mode/docker/build.dask-eopf-local.sh) # + re-run with --push
all_files+=($b)

# [local mode] [dask staging]
c=$(_realpath rs-server/.github/workflows/publish-binaries.yml) # + run rs-server ci/cd
all_files+=($c)

# [cluster mode] [dask eopf] [dask staging]
d=$(_realpath rs-infra-core/.github/dask-gateway/Dockerfile) # + run rs-infra-core ci/cd
all_files+=($d)

# [local mode] [cluster mode] [jupyter base image]
e=$(_realpath rs-server/resources/apt_upgrade_images.sh) # + re-run with --push
all_files+=($e)

# [local mode] [jupyter with rs-client-libraries]
# [local mode] [cluster mode] [prefect with rs-client-libraries]
f=$(_realpath rs-client-libraries/.github/workflows/publish-binaries.yml) # + run rs-client-libraries ci/cd
all_files+=($f)

# [cluster mode] [jupyter with rs-client-libraries]
g=$(_realpath rs-infra-core/.github/jupyter/Dockerfile) # + run rs-infra-core ci/cd
all_files+=($g)

echo -e "
Instructions:
#############

  - Create a new git branch (from develop) with the same name for:
    + $(_realpath rs-client-libraries)
    + $(_realpath rs-demo)
    + $(_realpath rs-infra-core)
    + $(_realpath rs-server)

  - Commit and push the changes made by this script.

  - Create Pull Requests in github.

  - Check in the github ci/cd actions that the new docker images were built for:
    + rs-client-libraries
    + rs-infra-core
    + rs-server

  - Run the scripts locally:
      $a
      $b
      $e

  - After the docker images are built from the ci/cd and local scripts, test them locally with:
      cd $(_realpath rs-demo)/local-mode
      # test your branch name, without special characters
      ./test-docker-tag.sh $(git rev-parse --abbrev-ref HEAD | sed "s/[^a-zA-Z0-9]/-/g")
      #
"



echo "${all_files[@]}"
