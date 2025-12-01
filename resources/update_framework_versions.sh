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

PREFECT_TAG=3.6.4
PREFECT_AWS_TAG=0.7.1

all_variables=(PYTHON_VERSION PYTHON_VERSION_DPR DASK_TAG DASK_GATEWAY_TAG PREFECT_TAG PREFECT_AWS_TAG) # var names

#
# Bash scripts, dockerfiles and github action workflows to update,
# with paths relative to the rs-server parent folder.

all_files=()

# Return realpath
_realpath(){
    realpath "${ROOT_DIR}/../$1"
}

# [local mode] [cluster mode]
# [python base image] [jupyter base image] [dask base image] [prefect base image]
# [ghcr.io/rs-python/dask/dask-gateway]
# [ghcr.io/rs-python/quay.io/jupyter/base-notebook]
# [ghcr.io/rs-python/python]
# [ghcr.io/rs-python/prefecthq/prefect]
all_files+=($(_realpath rs-server/resources/build_base_images.sh)) # + re-run with --push
all_files+=($(_realpath rs-server/resources/build_base_images/Dockerfile.dask))
all_files+=($(_realpath rs-server/resources/build_base_images/Dockerfile.jupyter))
all_files+=($(_realpath rs-server/resources/build_base_images/Dockerfile.python))

# [local mode] [cluster mode] [ci/cd]
# + run rs-server ci/cd
all_files+=($(_realpath operational-services/.github/workflows/check-code-quality.yml))
all_files+=($(_realpath operational-services/.github/workflows/publish-binaries.yml))
all_files+=($(_realpath rs-client-libraries/.github/workflows/check-code-quality.yml))
all_files+=($(_realpath rs-client-libraries/.github/workflows/publish-binaries.yml))
all_files+=($(_realpath rs-demo/.github/workflows/run_demos.yml))
all_files+=($(_realpath rs-dpr-service/.github/workflows/check-code-quality.yml))
all_files+=($(_realpath rs-dpr-service/.github/workflows/publish-binaries.yml))
all_files+=($(_realpath rs-infra-core/.github/common/resources/install-requirements.sh))
all_files+=($(_realpath rs-server/.github/workflows/check-code-quality.yml))
all_files+=($(_realpath rs-server/.github/workflows/publish-binaries.yml))

# [local mode] [cluster mode] [docker images]
# + run rs-server ci/cd
# [ghcr.io/rs-python/rs-osam]
all_files+=($(_realpath operational-services/object_storage_access_manager/.github/Dockerfile))
# [ghcr.io/rs-python/rs-dpr-service]
all_files+=($(_realpath rs-dpr-service/.github/Dockerfile))
# [ghcr.io/rs-python/rs-server-adgs]
all_files+=($(_realpath rs-server/services/adgs/.github/Dockerfile))
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
# [ghcr.io/rs-python/rs-testmeans_adgs-station-mock]
all_files+=($(_realpath rs-testmeans/src/ADGS/Dockerfile))
# [ghcr.io/rs-python/rs-testmeans_prip-station-mock]
all_files+=($(_realpath rs-testmeans/src/PRIP/Dockerfile))
# [ghcr.io/rs-python/rs-testmeans_lta-station-mock]
all_files+=($(_realpath rs-testmeans/src/LTA/Dockerfile))
# [ghcr.io/rs-python/rs-testmeans_dpr-station-mock]
all_files+=($(_realpath rs-testmeans/src/DPR/Dockerfile))
# [ghcr.io/rs-python/rs-testmeans_cadip-station-mock]
all_files+=($(_realpath rs-testmeans/src/CADIP/Dockerfile))

# [local mode] [cluster mode] [dask eopf]
# [ghcr.io/rs-python/dask/l0]
# [ghcr.io/rs-python/dask/s1ard]
# [ghcr.io/rs-python/dask/mockup]
# + re-run rs-workflow-env/docker/build.dask-eopf.py -p all
all_files+=($(_realpath rs-workflow-env/docker/Dockerfile.dask-eopf))
all_files+=($(_realpath rs-workflow-env/docker/Dockerfile.dask-eopf-mockup))

# [local mode] [cluster mode] [dask staging] [ghcr.io/rs-python/dask/staging]
all_files+=($(_realpath rs-server/services/staging/.github/Dockerfile.dask-staging)) # + run rs-server ci/cd

# [local mode] [cluster mode] [prefect with rs-client-libraries]
# [ghcr.io/rs-python/prefect/rs-client-libraries/local]
# [ghcr.io/rs-python/prefect/rs-client-libraries/k8s]
all_files+=($(_realpath rs-client-libraries/.github/dockerfiles/Dockerfile.prefect)) # + run rs-client-libraries ci/cd

# [local mode] [jupyter with rs-client-libraries] [ghcr.io/rs-python/jupyter/rs-client-libraries/local]
all_files+=($(_realpath rs-client-libraries/.github/dockerfiles/Dockerfile.jupyter)) # + run rs-client-libraries ci/cd

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

cat << EOF
TODO:
+ Search all Git repositories for old version numbers (e.g. search for '3.1.0' if you changed a component version \
from '3.1.0" to '4.2.0') in case some were missed by this script.
+ Check all files that have changed in all Git repositories and how to rebuild the associated CI/CDs and Dockerfiles.

EOF
