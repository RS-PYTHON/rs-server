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

# Run the rs-server-frontend docker container

set -euo pipefail
set -x

# Parse the STAC browser URLs, separated by ;
sb_urls=(${STAC_BROWSER_URLS//;/ })
STAC_BROWSER_URL_CADIP=${sb_urls[0]}
STAC_BROWSER_URL_CATALOG=${sb_urls[1]}

# Replace environment variables in the openapi.json file
sed -i "s|\${RSPY_UAC_HOMEPAGE}|${RSPY_UAC_HOMEPAGE:-}|g" $RSPY_OPENAPI_FILE
sed -i "s|\${STAC_BROWSER_URL_CADIP}|${STAC_BROWSER_URL_CADIP:-}|g" $RSPY_OPENAPI_FILE
sed -i "s|\${STAC_BROWSER_URL_CATALOG}|${STAC_BROWSER_URL_CATALOG:-}|g" $RSPY_OPENAPI_FILE

# Run the FastAPI application
python -m uvicorn --factory rs_server_frontend.main:start_app --host 0.0.0.0 --port 8000
