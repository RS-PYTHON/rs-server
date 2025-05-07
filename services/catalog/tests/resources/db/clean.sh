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


# Try to kill the existing postgres docker container if it exists
# and prune the docker pytest networks to clean the IPv4 address pool
docker rm -f $(docker ps -aqf name=postgres-rspy_pytest) >/dev/null 2>&1
docker network rm -f $(docker network ls --filter=name="pytest*" -q) >/dev/null 2>&1
