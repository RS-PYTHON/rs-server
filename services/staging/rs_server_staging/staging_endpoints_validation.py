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

"""OpenAPI-core helpers for OGC validation of staging endpoints."""

import json
import os
import os.path as osp
from typing import Any

# openapi_core libraries used for endpoints validation
from openapi_core import OpenAPI  # Spec, validate_request, validate_response
from openapi_core.contrib.starlette.requests import StarletteOpenAPIRequest
from openapi_core.contrib.starlette.responses import StarletteOpenAPIResponse
from rs_server_common.utils.logging import Logging
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_200_OK, HTTP_400_BAD_REQUEST

PATH_TO_YAML_OPENAPI = osp.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)),
    "config",
    "staging_templates",
    "yaml",
    "staging_openapi_schema.yaml",
)

if not os.path.isfile(PATH_TO_YAML_OPENAPI):
    raise FileNotFoundError(f"The following file path was not found: {PATH_TO_YAML_OPENAPI}")
OPENAPI = OpenAPI.from_file_path(PATH_TO_YAML_OPENAPI)

logger = Logging.default(__name__)


async def validate_request(request: Request) -> dict[Any, Any]:
    """
    Validate an endpoint request according to the OGC API Processes schema.

    The raw body is passed to openapi-core because validation must run against
    the same bytes received by FastAPI. The parsed dict is returned only after
    schema validation succeeds.

    Args:
        request (Request): endpoint request

    Returns:
        (dict) dictionary corresponding to the valid staging body

    """
    if not os.path.isfile(PATH_TO_YAML_OPENAPI):
        raise FileNotFoundError(f"The following file path was not found: {PATH_TO_YAML_OPENAPI}")
    try:
        body = await request.body()
        logger.info("Validating staging request %s %s", request.method, request.url.path)
        logger.debug("Staging request body for validation: %s", body)
        openapi_request = StarletteOpenAPIRequest(request, body)
        OPENAPI.validate_request(openapi_request)
        parsed_body = json.loads(body) if body else None  # type: ignore
        logger.info("Validated staging request %s %s", request.method, request.url.path)
        return parsed_body  # type: ignore
    except Exception as e:
        # Handle exceptions and return an appropriate error message
        logger.exception("Staging request validation failed for %s %s: %s", request.method, request.url.path, e)
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"Request body validation failed: {e}") from e


def validate_response(request: Request, data: dict, status_code=HTTP_200_OK):
    """
    Validate an endpoint response according to the OGC API Processes schema.

    A Starlette JSONResponse is built only for validation purposes, then wrapped
    as an openapi-core response object. Validation errors are allowed to bubble
    up to the caller so endpoint tests and middleware can report schema issues.

    Args:
        request (Request): input request
        data (dict): data to send in the endpoint response
        status_code (int): HTTP status code for the response. Defaults to HTTP_200_OK.
    """
    json_response = JSONResponse(status_code=status_code, content=data)
    logger.info("Validating staging response for %s %s; status=%s", request.method, request.url.path, status_code)
    logger.debug("Staging response data for validation: %s", data)
    openapi_request = StarletteOpenAPIRequest(request)
    openapi_response = StarletteOpenAPIResponse(json_response)
    OPENAPI.validate_response(openapi_request, openapi_response)
    logger.info("Validated staging response for %s %s", request.method, request.url.path)
