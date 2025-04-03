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
"""OGC openapi_core request and response validation functions"""

import copy
import json
from datetime import datetime

import pytest
from rs_server_staging.staging_endpoints_validation import (
    validate_request,
    validate_response,
)
from starlette.requests import Request


async def mock_receive(valid_staging_body):
    """Simulate an ASGI reception canal for Starlette"""
    return {
        "type": "http.request",
        "body": json.dumps(valid_staging_body).encode("utf-8"),
        "more_body": False,
    }


@pytest.mark.asyncio
async def test_validate_request():
    """Test the method to validate that the request body is ogc compliant"""

    # ----- Check that a Starlette request with a body which is compliant with ogc (each endpoint
    # has its own input schema to follow) returns the valid body
    request_scope = {
        "type": "http",
        "method": "POST",
        "path": " http://rs-server-staging:8000/processes/staging/execution",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
    }
    valid_staging_body = {
        "inputs": {
            "collection": "Target collection",
            "href": "http://localhost:8002/cadip/search?ids=S1A_20231120061537234567&collections=cadip_sentinel1",
        },
    }
    # Create a Starlette request to validate
    mock_request = Request(scope=request_scope, receive=lambda: mock_receive(valid_staging_body))
    body = await validate_request(mock_request)
    assert body == valid_staging_body

    # ----- Check that a Starlette request with a body which is not compliant with ogc raises
    # the appropriate validation exception
    wrong_staging_body = {
        "inputs": {
            "collection": "Target collection",
            "href": {"wrong": "format"},
        },
    }
    mock_request = Request(scope=request_scope, receive=lambda: mock_receive(wrong_staging_body))
    with pytest.raises(Exception) as excinfo:
        await validate_request(mock_request)
    assert "Request body validation error" in str(excinfo.value)


async def test_validate_response():
    """Test the method to validate that the response content is ogc compliant"""

    # ----- Check that a Starlette response which is compliant with ogc (each endpoint
    # has its own input schema to follow) returns the valid response
    request_scope = {
        "type": "http",
        "method": "POST",
        "path": " http://rs-server-staging:8000/processes/staging/execution",
        "headers": [(b"content-type", b"application/json")],
        "query_string": b"",
    }
    valid_staging_body = {
        "inputs": {
            "collection": "Target collection",
            "href": "http://localhost:8002/cadip/search?ids=S1A_20231120061537234567&collections=cadip_sentinel1",
        },
    }

    valid_response = {
        "jobID": "job_1",
        "status": "running",
        "type": "process",
        "progress": 0.0,
        "message": "Test detail",
        "created": datetime(2024, 1, 1, 12, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updated": datetime(2024, 1, 1, 13, 0, 0).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "processID": "staging",
    }
    # Create a Starlette request to validate
    mock_request = Request(scope=request_scope, receive=lambda: mock_receive(valid_staging_body))

    # ----- Check that the validation method doesn't raise any error if the respons
    # has a valid format
    validate_response(mock_request, valid_response)

    # ----- Check that a Starlette response which is not compliant with ogc raises
    # the appropriate validation exception
    wrong_response = copy.deepcopy(valid_response)
    wrong_response.pop("jobID")  # Remove a required ogc attribute

    with pytest.raises(Exception) as excinfo:
        validate_response(mock_request, wrong_response)
    assert "'jobID' is a required property" in str(excinfo.value)
