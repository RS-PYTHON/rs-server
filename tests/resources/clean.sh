#!/usr/bin/env bash

# Try to kill the existing postgres docker container if it exists
# and prune the docker pytest networks to clean the IPv4 address pool
docker rm -f $(docker ps -aqf name=postgres-rspy-pytest) >/dev/null 2>&1
docker network rm -f $(docker network ls --filter=name="pytest*" -q) >/dev/null 2>&1
