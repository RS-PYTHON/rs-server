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
from openapi_core.contrib.requests import (
    RequestsOpenAPIRequest,
    RequestsOpenAPIResponse,
)
from requests import Response
from requests.models import PreparedRequest

PATH_TO_YAML_OPENAPI = osp.join(
    osp.realpath(osp.dirname(__file__)),
    "../config",
    "staging_templates",
    "yaml",
    "staging_openapi_schema.yaml",
)


class StagingValidationException(Exception):
    """
    Exception raised when an error occurs during the OGC validation
    of the staging endpoints
    """


def validate_and_unmarshal_request(request: PreparedRequest) -> Any:
    """Validate an endpoint request according to the ogc specifications

    Args:
        request (Request): endpoint request

    Returns:
        ResponseUnmarshalResult.data: data validated by the openapi_core
        unmarshal_response method
    """
    if not os.path.isfile(PATH_TO_YAML_OPENAPI):
        raise FileNotFoundError(f"The following file path was not found: {PATH_TO_YAML_OPENAPI}")

    openapi = OpenAPI.from_file_path(PATH_TO_YAML_OPENAPI)
    openapi_request = RequestsOpenAPIRequest(request)

    # validate_request(request, spec=Spec.from_file_path(PATH_TO_YAML_OPENAPI))
    result = openapi.unmarshal_request(openapi_request)

    if result.errors:
        raise StagingValidationException(
            f"Error validating the request of the enpoint "
            f"{openapi_request.path}: {str(result.errors[0])}",  # type: ignore
        )
    if not result.body:
        raise StagingValidationException(
            f"Error validating the request of the enpoint "
            f"{openapi_request.path}: 'data' field of ResponseUnmarshalResult"
            f"object is empty",
        )
    return result.body


def validate_and_unmarshal_response(response: Response) -> Any:
    """
    Validate an endpoint response according to the ogc specifications
    (described as yaml schemas)

    Args:
        response (Response): endpoint response
    Returns:
        ResponseUnmarshalResult.data: data validated by the openapi_core
        unmarshal_response method
    """
    if not os.path.isfile(PATH_TO_YAML_OPENAPI):
        raise FileNotFoundError(f"The following file path was not found: {PATH_TO_YAML_OPENAPI}")

    openapi = OpenAPI.from_file_path(PATH_TO_YAML_OPENAPI)
    openapi_request = RequestsOpenAPIRequest(response.request)
    openapi_response = RequestsOpenAPIResponse(response)

    # Alternative method to validate the response
    # validate_response(response=response, spec= Spec.from_file_path(PATH_TO_YAML_OPENAPI), request=request)
    result = openapi.unmarshal_response(openapi_request, openapi_response)  # type: ignore
    if result.errors:
        raise StagingValidationException(  # type: ignore
            f"Error validating the response of the enpoint "
            f"{openapi_request.path}: {str(result.errors[0])}",  # type: ignore
        )
    if not result.data:
        raise StagingValidationException(
            f"Error validating the response of the enpoint "
            f"{openapi_request.path}: 'data' field of ResponseUnmarshalResult"
            f"object is empty",
        )
    return result.data
