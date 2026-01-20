# Copyright 2023-2025 Airbus, CS Group
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
"""Module with tests for utility functions of staging processors."""

from collections.abc import Callable
from http.client import HTTPResponse

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from httpx import Response
from rs_server_common import middlewares
from rs_server_common.middlewares import HandleExceptionsMiddleware
from rs_server_staging import main
from rs_server_staging.utils.tools import get_minimal_collection_body
from starlette import status


def test_get_minimal_collection_body():
    """Small test of get_minimal_collection_body"""
    expected = {
        "id": "abc",
        "type": "Collection",
        "description": "Collection abc automatically created by staging processor",
        "stac_version": "1.1.0",
        "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        "license": "public-domain",
        "extent": {
            "spatial": {"bbox": [[0.0, 0.0, -0.0, 0.0]]},
            "temporal": {"interval": [["2000-01-01T00:00:00Z", "2050-01-01T00:00:00Z"]]},
        },
    }

    output = get_minimal_collection_body("abc")
    assert output == expected


def test_handle_exceptions_middleware(staging_client, mocker):
    """
    Test that HandleExceptionsMiddleware logs errors as expected.

    NOTE: the HTTPExceptions raised from endpoints body or dependencies are converted into JSONResponses before
    arriving to HandleExceptionsMiddleware. I don't know where this is done.
    """
    client = staging_client

    # Spy calls to logger.error(...)
    spy_log_error = mocker.spy(middlewares.logger, "error")

    # All the endpoints return an ogc_error_response instance in case of error.
    # Check that the error message is logged.
    response = client.get("processes/non_existing")  # will return an error

    expected_status = status.HTTP_404_NOT_FOUND
    expected_content = {
        "type": "https://developer.mozilla.org/en/docs/Web/HTTP/Reference/Status/404",
        "status": expected_status,
        "detail": "Resource non_existing not found",
    }

    # Check the expected http response
    assert response.status_code == expected_status
    assert response.json() == expected_content

    # Check that logger.error was called once
    spy_log_error.assert_called_once()
    logged_content = spy_log_error.call_args[0][0]  # logged message

    # We should have logged the str: '<status>: <message>'
    assert str(expected_status) in logged_content
    assert str(expected_content) in logged_content
