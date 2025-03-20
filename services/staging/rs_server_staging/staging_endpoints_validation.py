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

import json
import os
import os.path as osp
from typing import Any, Dict

# openapi_core libraries used for endpoints validation
import requests
from openapi_core import OpenAPI  # Spec, validate_request, validate_response
from openapi_core import Spec, validate_request
from openapi_core.contrib.requests import (
    RequestsOpenAPIRequest,
    RequestsOpenAPIResponse,
)
from openapi_core.contrib.starlette.requests import StarletteOpenAPIRequest
from openapi_core.contrib.starlette.responses import StarletteOpenAPIResponse
from openapi_core.validation.request.exceptions import RequestValidationError
from requests import Response
from requests.models import PreparedRequest
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.status import HTTP_200_OK

PATH_TO_YAML_OPENAPI = osp.join(
    osp.realpath(osp.dirname(__file__)),
    "../config",
    "staging_templates",
    "yaml",
    "staging_openapi_schema.yaml",
)

if not os.path.isfile(PATH_TO_YAML_OPENAPI):
    raise FileNotFoundError(f"The following file path was not found: {PATH_TO_YAML_OPENAPI}")
OPENAPI = OpenAPI.from_file_path(PATH_TO_YAML_OPENAPI)


class StagingValidationException(Exception):
    """
    Exception raised when an error occurs during the OGC validation
    of the staging endpoints
    """


async def validate_request(request: Request) -> Any:
    """Validate an endpoint request according to the ogc specifications

    Args:
        request (Request): endpoint request

    Returns:
        ResponseUnmarshalResult.data: data validated by the openapi_core
        unmarshal_response method
    """
    if not os.path.isfile(PATH_TO_YAML_OPENAPI):
        raise FileNotFoundError(f"The following file path was not found: {PATH_TO_YAML_OPENAPI}")

    body = await request.body()
    openapi_request = StarletteOpenAPIRequest(request, body)
    OPENAPI.validate_request(openapi_request)
    return body
    # return json.loads(body)

    # #result = openapi.unmarshal_request(openapi_request)
    # if result.errors:
    #     raise StagingValidationException(
    #         f"Error validating the request of the enpoint "
    #         f"{openapi_request.path}: {str(result.errors[0])}",  # type: ignore
    #     )
    # if not result.body:
    #     raise StagingValidationException(
    #         f"Error validating the request of the enpoint "
    #         f"{openapi_request.path}: 'data' field of ResponseUnmarshalResult"
    #         f"object is empty",
    #     )
    # return result.body


def validate_response(request: Request, data: dict, status_code=HTTP_200_OK) -> Any:
    """
    Validate an endpoint response according to the ogc specifications
    (described as yaml schemas)

    Args:
        request (Request): input request
        data (dict): data to send in the endpoint response
    Returns:
        json_response: return the content of the response as a json string
    """
    json_response = JSONResponse(status_code=HTTP_200_OK, content=data)
    openapi_request = StarletteOpenAPIRequest(request)
    openapi_response = StarletteOpenAPIResponse(json_response)
    OPENAPI.validate_response(openapi_request, openapi_response)

    return json_response


# def validate_and_unmarshal_response(response: Response) -> Any:
#     """
#     Validate an endpoint response according to the ogc specifications
#     (described as yaml schemas)

#     Args:
#         response (Response): endpoint response
#     Returns:
#         ResponseUnmarshalResult.data: data validated by the openapi_core
#         unmarshal_response method
#     """
#     if not os.path.isfile(PATH_TO_YAML_OPENAPI):
#         raise FileNotFoundError(f"The following file path was not found: {PATH_TO_YAML_OPENAPI}")

#     openapi = OpenAPI.from_file_path(PATH_TO_YAML_OPENAPI)
#     openapi_request = RequestsOpenAPIRequest(response.request)
#     openapi_response = RequestsOpenAPIResponse(response)

#     # Alternative method to validate the response
#     # validate_response(response=response, spec= Spec.from_file_path(PATH_TO_YAML_OPENAPI), request=request)
#     result = openapi.unmarshal_response(openapi_request, openapi_response)  # type: ignore
#     if result.errors:
#         raise StagingValidationException(  # type: ignore
#             f"Error validating the response of the enpoint "
#             f"{openapi_request.path}: {str(result.errors[0])}",  # type: ignore
#         )
#     if not result.data:
#         raise StagingValidationException(
#             f"Error validating the response of the enpoint "
#             f"{openapi_request.path}: 'data' field of ResponseUnmarshalResult"
#             f"object is empty",
#         )
#     return result.data
