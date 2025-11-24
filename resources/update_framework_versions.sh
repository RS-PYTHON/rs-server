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

# Update the versions of the frameworks used in the project: Python, Dask, Prefect
# These versions appear in the repository scripts, Docker images, ci/cd, ...

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
ROOT_DIR="$(realpath $SCRIPT_DIR/..)"

#
# Hardcode here the versions to use, with the same variable names as in the files below

# We use a different python version in eopf + the dpr processors + rs-dpr-service
PYTHON_VERSION=3.13.9
PYTHON_VERSION_DPR=3.11.7

DASK_TAG=2024.5.2
DASK_GATEWAY_TAG=2024.1.0

PREFECT_TAG=3.2.13
PREFECT_DASK_TAG=0.3.3
PREFECT_AWS_TAG=0.5.9

all_variables=(PYTHON_VERSION PYTHON_VERSION_DPR DASK_TAG DASK_GATEWAY_TAG PREFECT_TAG PREFECT_DASK_TAG PREFECT_AWS_TAG) # var names

#
# Bash scripts, dockerfiles and github action workflows to update,
# with paths relative to the rs-server parent folder.

all_files=()

# Return realpath
_realpath(){
    realpath "${ROOT_DIR}/../$1"
}

# [local mode] [cluster mode] [rs-server]
# [ghcr.io/rs-python/rs-server-adgs]
all_files+=($(_realpath rs-server/services/adgs/.github/Dockerfile)) # + run rs-server ci/cd
# [ghcr.io/rs-python/rs-server-cadip]
all_files+=($(_realpath rs-server/services/cadip/.github/Dockerfile))
# [ghcr.io/rs-python/rs-server-catalog]
all_files+=($(_realpath rs-server/services/catalog/.github/Dockerfile))
# [ghcr.io/rs-python/rs-server-frontend]
all_files+=($(_realpath rs-server/services/frontend/.github/Dockerfile))
# [ghcr.io/rs-python/rs-server-prip]
all_files+=($(_realpath rs-server/services/prip/.github/Dockerfile))
# [ghcr.io/rs-python/rs-server-staging]
all_files+=($(_realpath rs-server/services/staging/.github/Dockerfile))

# [ci/cd] [rs-server]
all_files+=($(_realpath rs-server/.github/workflows/check-code-quality.yml)) # + run rs-server ci/cd
all_files+=($(_realpath rs-server/.github/workflows/publish-binaries.yml))

# [local mode] [cluster mode] [dask base image]
# [ghcr.io/rs-python/dask-gateway-server/base/local] [ghcr.io/rs-python/dask/dask-gateway]
all_files+=($(_realpath rs-demo/local-mode/docker/build.dask-base.sh)) # + re-run with --push
all_files+=($(_realpath rs-demo/local-mode/docker/Dockerfile.dask-base))

# [local mode] [dask eopf] [ghcr.io/rs-python/dask-gateway-server/eopf/local]
# + re-run rs-demo/local-mode/docker/build.dask-eopf-local.py -p all
all_files+=($(_realpath rs-demo/local-mode/docker/Dockerfile.dask-eopf-local))
all_files+=($(_realpath rs-demo/local-mode/docker/Dockerfile.dask-eopf-mockup-local))

# [local mode] [dask staging] [ghcr.io/rs-python/dask-gateway-server/staging/local]
all_files+=($(_realpath rs-server/services/staging/.github/Dockerfile.dask-staging-local)) # + run rs-server ci/cd

# [cluster mode] [dask eopf] [dask staging]
# [ghcr.io/rs-python/rs-infra-core-dask-staging] [ghcr.io/rs-python/rs-infra-core-dask-eopf]
all_files+=($(_realpath rs-infra-core/.github/dask-gateway/Dockerfile)) # + run rs-infra-core ci/cd
all_files+=($(_realpath rs-infra-core/.github/common/resources/requirements-dask-eopf.txt))

# [local mode] [cluster mode] [jupyter base image]
# [ghcr.io/rs-python/jupyter/minimal-notebook] [ghcr.io/rs-python/quay.io/jupyter/base-notebook]
all_files+=($(_realpath rs-server/resources/build_base_images.sh)) # + re-run with --push
all_files+=($(_realpath rs-server/resources/build_base_images/Dockerfile.python)) # + re-run with --push
all_files+=($(_realpath rs-server/resources/build_base_images/Dockerfile.jupyter)) # + re-run with --push

# [local mode] [jupyter with rs-client-libraries] [ghcr.io/rs-python/jupyter/rs-client-libraries/local]
all_files+=($(_realpath rs-client-libraries/.github/dockerfiles/Dockerfile.jupyter)) # + run rs-client-libraries ci/cd

# [local mode] [cluster mode] [prefect with rs-client-libraries]
# [ghcr.io/rs-python/prefect/rs-client-libraries/local] [ghcr.io/rs-python/prefect/rs-client-libraries/k8s]
all_files+=($(_realpath rs-client-libraries/.github/dockerfiles/Dockerfile.prefect)) # + run rs-client-libraries ci/cd

# [cluster mode] [jupyter with rs-client-libraries] [ghcr.io/rs-python/rs-infra-core-jupyter]
all_files+=($(_realpath rs-infra-core/.github/jupyter/Dockerfile)) # + run rs-infra-core ci/cd

#
# Update files

# For each file and variable to update
for file in "${all_files[@]}"; do
  for var_name in "${all_variables[@]}"; do

    # In the file, replace <my_var>=<my_value> or <my_var>:<my_value> by the right value.
    # Only for lines that don't contain a $ to avoid updating e.g. <my_var>=$<other_var>
    # NOTE: ${!var_name} = the var value
    sed -i "/\\$/! s/${var_name}\([=:][[:space:]]*\)[^[:space:]]\+/${var_name}\1${!var_name}/g" "$file"
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
      # Re-run this script because docker compose pull has overriden the images built from this script
      GITLAB_EOPF_TOKEN=*** $0
      docker compose up
      # In another terminal, check the dependency versions
      for c in prefect-server dask-staging dask-eopf jupyter; do
        docker compose exec \$c pip list | grep -i -e dask -e eopf -e l0 -e prefect
      done
      # Run all notebooks
      ./run-notebooks.sh
      # Also open Jupyter and run manually the notebooks that were ignored by the previous command
      docker compose logs jupyter

  - Create a new git branch (from develop) with the same name for the git repositories that were modified:
    + $(_realpath rs-client-libraries)
    + $(_realpath rs-demo)
    + $(_realpath rs-infra-core)
    + $(_realpath rs-server)

  - Commit and push the changes. Create Pull Requests in github. Check that the ci/cd runs are OK \
(warning: may need the next step).

  - Build these local Docker images and push them into the Docker registry.
    WARNING: this may impact other branches in the ci/cd, but this may be necessary for your ci/cd to pass.
    Do this only when you are ready to merge your Pull Requests.
    NOTE: other Docker images are built from the ci/cd.
      export GITLAB_EOPF_TOKEN=***
      $a --push && \\
      $b --push && \\
      $g --push

  - After pushing the Docker images (previous step), run again the ci/cd for all your branches. \
Check that they are OK. Merge your Pull Requests.

  - Run the infra ci/cd to build the cluster Docker images, then redeploy them on the cluster.

  - Run command 'pip list | grep -i -e dask -e eopf -e l0 -e prefect' on the cluster Dask, Prefect and Jupyter pods \
to check the dependency versions.

  - Run all notebooks on the cluster JupyterHub, check that they are OK.
"
