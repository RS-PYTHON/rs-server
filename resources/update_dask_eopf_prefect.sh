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

# Update the versions of Dask, EOPF and Prefect from the Docker images used by
# the docker compose (for local mode) and Kubernetes cluster (for cluster mode).

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

# Hardcode here the versions to use, with the same variable names as in the files below
DASK_TAG=2024.5.2
DASK_GATEWAY_TAG=2024.1.0
PREFECT_TAG=3.2.13
PREFECT_DASK_TAG=0.3.3
eopf=2.4.4
l0=0.9.0
all_variables=(DASK_TAG DASK_GATEWAY_TAG PREFECT_TAG PREFECT_DASK_TAG eopf l0) # var names

#
# Bash scripts, dockerfiles and github action workflows to update,
# with paths relative to the rs-server parent folder.

all_files=()

# Return realpath
_realpath(){
    realpath "${ROOT_DIR}/../$1"
}

# [local mode] [dask base image] [ghcr.io/rs-python/dask-gateway-server/base/local]
a=$(_realpath rs-demo/local-mode/docker/build.dask-base-local.sh) # + re-run with --push
all_files+=($a)

# [local mode] [dask eopf] [ghcr.io/rs-python/dask-gateway-server/eopf/local]
b=$(_realpath rs-demo/local-mode/docker/build.dask-eopf-local.sh) # + re-run with --push
c=$(_realpath rs-demo/local-mode/docker/requirements.dask-eopf-local.txt)
all_files+=($b $c)

# [local mode] [dask staging] [ghcr.io/rs-python/dask-gateway-server/staging/local]
d=$(_realpath rs-server/services/staging/.github/Dockerfile.dask-staging-local) # + run rs-server ci/cd
all_files+=($d)

# [cluster mode] [dask eopf] [dask staging]
# [ghcr.io/rs-python/rs-infra-core-dask-staging] [ghcr.io/rs-python/rs-infra-core-dask-eopf]
e=$(_realpath rs-infra-core/.github/dask-gateway/Dockerfile) # + run rs-infra-core ci/cd
f=$(_realpath rs-infra-core/.github/common/resources/requirements-dask-eopf.txt)
all_files+=($e $f)

# [local mode] [cluster mode] [jupyter base image]
# [ghcr.io/rs-python/jupyter/minimal-notebook] [ghcr.io/rs-python/quay.io/jupyter/base-notebook]
g=$(_realpath rs-server/resources/apt_upgrade_images.sh) # + re-run with --push
all_files+=($g)

# [local mode] [jupyter with rs-client-libraries] [ghcr.io/rs-python/jupyter/rs-client-libraries/local]
h=$(_realpath rs-client-libraries/.github/dockerfiles/Dockerfile.jupyter) # + run rs-client-libraries ci/cd
all_files+=($h)

# [local mode] [cluster mode] [prefect with rs-client-libraries]
# [ghcr.io/rs-python/prefect/rs-client-libraries/local] [ghcr.io/rs-python/prefect/rs-client-libraries/k8s]
i=$(_realpath rs-client-libraries/.github/dockerfiles/Dockerfile.prefect) # + run rs-client-libraries ci/cd
all_files+=($i)

# [cluster mode] [jupyter with rs-client-libraries] [ghcr.io/rs-python/rs-infra-core-jupyter]
j=$(_realpath rs-infra-core/.github/jupyter/Dockerfile) # + run rs-infra-core ci/cd
all_files+=($j)

#
# Update files

# For each file and variable to update
for file in "${all_files[@]}"; do
  for var_name in "${all_variables[@]}"; do

    # In the file, replace <my_var>=<my_value> by the right value.
    # Only for lines that don't contain a $ to avoid updating e.g. <my_var>=$<other_var>
    # NOTE: ${!var_name} = the var value
    sed -i "/\\$/! s/${var_name}\(=\+\)[^[:space:]]\+/${var_name}\1${!var_name}/g" "$file"
  done
done

#
# Build everything locally to test the local mode

if [[ -z "${GITLAB_EOPF_TOKEN:-}" ]]; then
    >&2 echo -e "usage: GITLAB_EOPF_TOKEN=*** $0\n(see: https://gitlab.eopf.copernicus.eu/help/user/profile/personal_access_tokens)"
    exit 1
fi
export GITLAB_EOPF_TOKEN

# Wheel packages must be downloaded manually into the local ./whl dir
whl_dir=$(realpath ${SCRIPT_DIR}/whl)

if [[ \
  ($(ls ${whl_dir}/rs_server_staging-*.whl | wc -l) != 1) || \
  ($(ls ${whl_dir}/rs_client_libraries-*.whl | wc -l) != 1) \
]]; then

  echo -e "
Instructions:
#############

  - Go to the latest ci/cd runs for the 'develop' branch:
    + https://github.com/RS-PYTHON/rs-server/actions/workflows/publish-binaries.yml?query=branch%3Adevelop
    + https://github.com/RS-PYTHON/rs-client-libraries/actions/workflows/publish-binaries.yml?query=branch%3Adevelop

  - From the 'Artifacts' section at the bottom of the page, download AND UNZIP into '$whl_dir' the wheel packages:
    + rs_server_staging-<version>.whl
    + rs_client_libraries-<version>.whl

  - Re-run this script.
  "
  exit 2
fi

set -x

# Run bash scripts
$a
$b
$g

# Build docker images
docker build -f $d --progress=plain \
  -t ghcr.io/rs-python/dask-gateway-server/staging/local:latest $whl_dir
docker build -f $h --progress=plain \
  -t ghcr.io/rs-python/jupyter/rs-client-libraries/local:latest $whl_dir
docker build -f $i --progress=plain \
  -t ghcr.io/rs-python/prefect/rs-client-libraries/local:latest --build-arg K8S_IMAGE= $whl_dir
set +x

echo -e "
Instructions:
#############

  - Run all rs-demo notebooks, check that they are OK:
      cd $(_realpath rs-demo/local-mode)
      docker compose pull
      ./$0 # re-run this script because docker compose pull has overriden the images built from this script
      docker compose up
      # In another terminal, check the dependency versions
      for c in prefect-server dask-staging dask-eopf jupyter; do
        docker compose exec $c pip list | grep -i -e dask -e eopf -e l0 -e prefect
      done
      # Run all notebooks
      ./run-notebooks.sh


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
