#!/usr/bin/env bash

# Build the aggregated openapi.json file that then will be used to run the aggregated swagger frontend

set -euo pipefail
set -x

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
FRONT_DIR="$(realpath $SCRIPT_DIR/..)"

# Use this option to run locally all the services (defined in services.json)
if [[ " $@ " == *" --run-services "* ]]; then

    # NOTE: we need to run the services only so we can load their openapi.json file.
    # We don't use any other of their functions.

    network="rspy-build-frontend"
    docker network create $network

    # On exit, kill the containers and network and send the exit signal to subprocesses
    db_container="postgres"
    ak_container="apikey-manager"
    trap "docker rm -f $db_container $ak_container; docker network rm $network; kill 0" EXIT

    # First we need to pull the apikey manager docker image.
    # TODO: to be change with the :latest tag
    # TODO: to be changed when the apikey manager will have its own container registry.
    docker login https://ghcr.io/v2/rs-python
    ak_image="ghcr.io/rs-python/apikey-manager:rspy15-uac"
    docker pull "$ak_image"

    # Use the same configuration as in the cluster deployment.
    #export RSPY_DOCS_URL= # used to define the /docs swagger page (not used)
    export APIKEYMAN_URL_PREFIX="/apikeymanager" # used to prefix endpoints on the apikey manager
    export RSPY_LOCAL_MODE=0 # cluster mode with authentication needed

    # Use the env vars defined for the rs-server-catalog pytests.
    # They contain everything needed for the postgres database and the catalog stac-fastapi-pgstac
    envfile=$(realpath "${FRONT_DIR}/../catalog/tests/.env")
    source "$envfile"

    # Copy the env file into a tmp file and remove the "export " strings
    # since they are not supported by the docker --env-file option
    tmpfile=$(mktemp)
    cp "$envfile" "$tmpfile"
    sed -i "s|\s*export\s\+||g" "$tmpfile"
    envfile="$tmpfile"

    # Use the stac-utils/pgstac database for everything, it should be sufficient as we just need the openapi.json.
    db_image="ghcr.io/stac-utils/pgstac:v0.7.10"
    docker pull "$db_image"
    (docker run --rm --network=$network --name=$db_container \
        -p ${POSTGRES_PORT}:5432 --env-file="$envfile" \
        --health-cmd="pg_isready -U $POSTGRES_USER" --health-interval=2s --health-timeout=2s --health-retries=10 \
        "$db_image" \
    )&
    i=0
    while [[ $(docker inspect --format='{{.State.Health.Status}}' $db_container) != healthy ]]; do
        sleep 2
        i=$((i+1)); ((i>=10)) && >&2 echo "Error starting '$ak_container'" && exit 1
    done

    # Run the apikey manager. Use the same port as in services.json.
    (docker run --rm --network=$network --name=$ak_container -p 8004:8000 \
        -e APIKEYMAN_URL_PREFIX \
        -e API_KEYS_DB_URL=postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${db_container}:5432/${POSTGRES_DB} \
        -e VERIFY_AUDIENCE=0 \
        -e OAUTH2_SERVER_URL=https://iam.dev-rspy.esa-copernicus.eu \
        -e OAUTH2_REALM=rspy \
        -e OAUTH2_CLIENT_ID=dummy_client_id \
        -e OAUTH2_CLIENT_SECRET=dummy_client_secret \
        --health-cmd="wget --spider localhost:8000/health/status" --health-interval=2s --health-timeout=2s --health-retries=10 \
	    "$ak_image" \
    )&
    i=0
    while [[ $(docker inspect --format='{{.State.Health.Status}}' $ak_container) != healthy ]]; do
        sleep 2
        i=$((i+1)); ((i>=10)) && >&2 echo "Error starting '$ak_container'" && exit 1
    done

    # Run local fastapi services
    run_local_service() {
        path=$(realpath "${FRONT_DIR}/$1")
        app="$2"
        port="$3"
        health="$4"

        # In a subprocess: install the poetry environment and
        # run uvicorn with the environment variables set above
        (
            cd "$path"
            poetry install --with dev
            poetry run uvicorn "$app" --host=localhost --port="$port" --workers=1 >/dev/null
        )&

        # Call the health endpoint until it returns a status code OK
        local i=0
        while [[ ! $(curl "localhost:$port/$health" 2>/dev/null) ]]; do
            sleep 2
            i=$((i+1)); ((i>=10)) && >&2 echo "Error starting service '$app'" && exit 1
        done
        echo "Service '$app' is started"
    }

    # Use the same values as in services.json
    run_local_service "../adgs" "rs_server_adgs.fastapi.adgs_app:app" 8001 "health"
    run_local_service "../cadip" "rs_server_cadip.fastapi.cadip_app:app" 8002 "health"
    run_local_service "../catalog" "rs_server_catalog.main:app" 8003 "_mgmt/ping"

fi

services_file="${SCRIPT_DIR}/services.json" # input file = describe services
to_file="${SCRIPT_DIR}/openapi.json" # output file = aggregated json

# Build the aggregated openapi.json
(cd "${SCRIPT_DIR}" && poetry run python -m tools.openapi "$services_file" "$to_file")

echo -e "\nAggregated openapi generated under: '$to_file'\n"
