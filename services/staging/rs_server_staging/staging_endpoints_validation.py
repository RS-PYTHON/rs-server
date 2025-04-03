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

"""Openapi_core methods for OGC validation of the staging endpoints"""

import json
import os
import os.path as osp
from typing import Any

# openapi_core libraries used for endpoints validation
from openapi_core import OpenAPI  # Spec, validate_request, validate_response
from openapi_core.contrib.starlette.requests import StarletteOpenAPIRequest
from openapi_core.contrib.starlette.responses import StarletteOpenAPIResponse
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


async def validate_request(request: Request) -> dict[Any, Any]:
    """Validate an endpoint request according to the ogc specifications

    Args:
        request (Request): endpoint request

    Returns:
        (dict) dictionary corresponding to the valid staging body

    """
    if not os.path.isfile(PATH_TO_YAML_OPENAPI):
        raise FileNotFoundError(f"The following file path was not found: {PATH_TO_YAML_OPENAPI}")
    try:
        body = await request.body()
        openapi_request = StarletteOpenAPIRequest(request, body)
        OPENAPI.validate_request(openapi_request)
        return json.loads(body) if body else None  # type: ignore
    except Exception as e:
        # Handle exceptions and return an appropriate error message
        raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=f"Request body validation failed: {e}") from e


def validate_response(request: Request, data: dict, status_code=HTTP_200_OK):
    """
    Validate an endpoint response according to the ogc specifications
    (described as yaml schemas) - Raises an exception if the response
    has an unvalid format

    Args:
        request (Request): input request
        data (dict): data to send in the endpoint response
    """
    json_response = JSONResponse(status_code=status_code, content=data)
    openapi_request = StarletteOpenAPIRequest(request)
    openapi_response = StarletteOpenAPIResponse(json_response)
    OPENAPI.validate_response(openapi_request, openapi_response)
