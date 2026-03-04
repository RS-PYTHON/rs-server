#!/usr/bin/env bash
# Copyright 2023-2026 Airbus, CS Group
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


# Build the aggregated openapi.json file that then will be used to run the aggregated swagger frontend

set -euo pipefail
set -x

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
FRONT_DIR="$(realpath $SCRIPT_DIR/..)"

# Use this option to run locally all the services (defined in services.yml)
if [[ " $@ " == *" --run-services "* ]]; then

    # NOTE: we need to run the services only so we can load their openapi.json file.
    # We don't use any other of their functions.

    network="rspy-build-frontend"
    docker network create $network

    # On exit, kill the containers and network and send the exit signal to subprocesses
    pg_container="postgres"
    pgstac_container="pgstac"
    dpr_container="rs-dpr-service"

    on_exit="docker rm -f $pg_container $pgstac_container $dpr_container || true; docker network rm $network || true"
    trap 'eval $on_exit' EXIT # use simple quotes so the string is interpreted when we exit

    # Use the same configuration as in the cluster deployment.
    #export RSPY_DOCS_URL= # used to define the /docs swagger page (not used)
    export RSPY_LOCAL_MODE=0 # cluster mode with authentication needed

    # Environment variables for postgres and pgstac databases
    export POSTGRES_DB=rspy_pytest
    export POSTGRES_USER=postgres
    export POSTGRES_PASSWORD=password
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT=5432
    export PGSTAC_PORT=5439

    # Run a postgres database
    db_image="postgres:15-alpine"
    docker pull "$db_image"
    (docker run --rm --network=$network --name=$pg_container \
        -e POSTGRES_DB -e POSTGRES_USER -e POSTGRES_PASSWORD \
        -p $POSTGRES_PORT:5432 \
        --health-cmd="pg_isready -U $POSTGRES_USER" --health-interval=2s --health-timeout=2s --health-retries=10 \
        "$db_image" \
    )&
    i=0
    while [[ $(docker inspect --format='{{.State.Health.Status}}' $pg_container) != healthy ]]; do
        sleep 2
        i=$((i+1)); ((i>=10)) && >&2 echo "Error starting '$pg_container'" && exit 1
    done

    # Idem for pgstac database
    db_image="ghcr.io/stac-utils/pgstac:v0.9.10"
    docker pull "$db_image"
    (docker run --rm --network=$network --name=$pgstac_container \
        -e POSTGRES_DB -e POSTGRES_USER -e POSTGRES_PASSWORD \
        -e PGDATABASE=$POSTGRES_DB -e PGUSER=$POSTGRES_USER -e PGPASSWORD=$POSTGRES_PASSWORD \
        -p $PGSTAC_PORT:5432 \
        --health-cmd="pg_isready -U $POSTGRES_USER" --health-interval=2s --health-timeout=2s --health-retries=10 \
        "$db_image" \
    )&
    i=0
    while [[ $(docker inspect --format='{{.State.Health.Status}}' $pgstac_container) != healthy ]]; do
        sleep 2
        i=$((i+1)); ((i>=10)) && >&2 echo "Error starting '$pgstac_container'" && exit 1
    done

    # DPR service
    dpr_image="ghcr.io/rs-python/rs-dpr-service:latest"

    if ! docker ps --format '{{.Names}}' | grep -q "^$dpr_container\$"; then
        docker pull "$dpr_image"
        docker run --rm --network=$network --name=$dpr_container \
            -e RSPY_LOCAL_MODE=1 \
            -e POSTGRES_HOST=postgres \
            -e POSTGRES_PORT \
            -e POSTGRES_DB \
            -e POSTGRES_USER \
            -e POSTGRES_PASSWORD \
            -p 6003:8000 \
            --health-cmd="python3 -c 'import requests; assert requests.get(\"http://127.0.0.1:8000/_mgmt/ping\").ok'" \
            --health-interval=2s \
            --health-timeout=2s \
            --health-retries=10 \
            "$dpr_image" &
        echo "DPR container started"
    else
        echo "Using already running DPR container: $dpr_container"
    fi

    i=0
    while [[ $(docker inspect --format='{{.State.Health.Status}}' $dpr_container) != healthy ]]; do
        sleep 2
        i=$((i+1))
        ((i>=20)) && >&2 echo "Error: DPR container '$dpr_container' is not healthy after $((i*2))s" && exit 1
    done
    echo "DPR service container is healthy"

    # Run local fastapi services
    run_local_service() {
        path=$(realpath "${FRONT_DIR}/$1")
        app="$2"
        port="$3"
        health="$4"

        # Dummy environment variable values
        export OIDC_ENDPOINT=OIDC_ENDPOINT
        export OIDC_REALM=OIDC_REALM
        export OIDC_CLIENT_ID=OIDC_CLIENT_ID
        export OIDC_CLIENT_SECRET=OIDC_CLIENT_SECRET
        export RSPY_COOKIE_SECRET=RSPY_COOKIE_SECRET

        # Install the poetry environment and run uvicorn with the environment variables set above
        cd "$path"
        poetry install
        poetry run opentelemetry-bootstrap -a install # install otel instrumentation packages for dependencies
        (poetry run uvicorn "$app" --host=127.0.0.1 --port="$port" --workers=1)&
        on_exit="$on_exit; kill -9 $!" # kill the last process = unvicorn on exit
        cd -

        # Call the health endpoint until it returns a status code OK
        local i=0
        while [[ ! $(curl "127.0.0.1:$port/$health" 2>/dev/null) ]]; do
            sleep 2
            i=$((i+1)); ((i>=10)) && >&2 echo "Error starting service '$app'" && exit 1
        done
        echo "Service '$app' is started"
        return 0
    }

    #
    # Use the same values as in services.yml

    # Use postgres database
    run_local_service "../adgs" "rs_server_adgs.fastapi.adgs_app:app" 8001 "health"
    run_local_service "../cadip" "rs_server_cadip.fastapi.cadip_app:app" 8002 "health"
    run_local_service "../staging" "rs_server_staging.main:app" 8004 "_mgmt/ping"
    run_local_service "../prip" "rs_server_prip.fastapi.prip_app:app" 8005 "health"
    run_local_service "../edrs" "rs_server_edrs.fastapi.edrs_app:app" 8006 "health"
    run_local_service "../osam" "rs_server_osam.main:app" 7001 "_mgmt/ping"

    # Use pgstac database
    PGDATABASE=$POSTGRES_DB \
    PGUSER=$POSTGRES_USER \
    PGPASSWORD=$POSTGRES_PASSWORD \
    PGHOST=$POSTGRES_HOST \
    PGPORT=$PGSTAC_PORT \
    ENABLE_TRANSACTIONS_EXTENSIONS=1 \
    PREFIX_PATH=/catalog \
    OPENAPI_URL=/catalog/api \
    DOCS_URL=/catalog/api.html \
        run_local_service "../catalog" "rs_server_catalog.app:app" 8003 "catalog/_mgmt/ping"
fi

services_file="${SCRIPT_DIR}/services.yml" # input file = describe services
to_file="${SCRIPT_DIR}/openapi.json" # output file = aggregated json

# Build the aggregated openapi.json
(
    cd "${SCRIPT_DIR}"
    poetry install

    # Set hard-coded version name from git tags.
    # WARNING: this changes pyproject.toml and __init__.py
    if [[ " $@ " == *" --set-version "* ]]; then
        poetry self add "poetry-dynamic-versioning[plugin]" && poetry dynamic-versioning
    fi

    poetry run python -m tools.openapi "$services_file" "$to_file"
)

echo -e "\nAggregated openapi generated under: '$to_file'\n"
