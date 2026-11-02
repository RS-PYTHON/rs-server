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

"""Unit tests for utils module."""

import pytest
from fastapi import HTTPException, status
from rs_server_common.fastapi_app import MockPgstacCrudClient
from rs_server_common.utils.pytest import pytest_common_tests

from tests.test_authentication import CLUSTER_MODE, ROUTER_PREFIX_AUXIP


# Use cluster mode so we check the SessionMiddleware
@pytest.mark.parametrize(
    "fastapi_app",
    [
        {**CLUSTER_MODE, **ROUTER_PREFIX_AUXIP},
    ],
    indirect=["fastapi_app"],
    ids=[""],
)
def test_middleware_order(client):
    """Check that the FastAPI application middlewares were inserted in the right order."""
    pytest_common_tests.test_middleware_order(client, use_auth_middleware=False)


def test_handle_exceptions_middleware(client, mocker):
    """Test that HandleExceptionsMiddleware handles and logs errors as expected."""
    pytest_common_tests.test_handle_exceptions_middleware(client, mocker)


@pytest.mark.unit
@pytest.mark.parametrize(
    "filter_query, filter_lang, expected",
    [
        # Not valid CQL2 (a string instead of a TIMESTAMP), but accepted by the services
        (
            "T_BEFORE(start_datetime, '2025-04-01T00:00:00Z')",
            "cql2-text",
            {"op": "t_before", "args": [{"property": "start_datetime"}, "2025-04-01T00:00:00Z"]},
        ),
        (
            '{"op": "t_after", "args": [{"property": "start_datetime"}, "2025-04-01T00:00:00Z"]}',
            "cql2-json",
            {"op": "t_after", "args": [{"property": "start_datetime"}, "2025-04-01T00:00:00Z"]},
        ),
    ],
    ids=["cql2-text", "cql2-json"],
)
def test_mock_pgstac_clean_search_args(filter_query, filter_lang, expected):
    """The services that mock pgstac parse the filters without validating them with cql2."""
    clean = MockPgstacCrudClient()._clean_search_args(  # pylint: disable=protected-access
        {"collections": ["adgs"]},
        filter_query=filter_query,
        filter_lang=filter_lang,
        sortby=["-created"],
    )
    assert clean == {
        "collections": ["adgs"],
        "sortby": [{"field": "created", "direction": "desc"}],
        "filter": expected,
        "filter_lang": "cql2-json",
    }


@pytest.mark.unit
@pytest.mark.parametrize("filter_query, filter_lang", [("(", "cql2-text"), ("{", "cql2-json")])
def test_mock_pgstac_clean_search_args_invalid(filter_query, filter_lang):
    """A filter that cannot be parsed is refused with HTTP 400."""
    with pytest.raises(HTTPException) as error:
        MockPgstacCrudClient()._clean_search_args(  # pylint: disable=protected-access
            {},
            filter_query=filter_query,
            filter_lang=filter_lang,
        )
    assert error.value.status_code == status.HTTP_400_BAD_REQUEST
    assert error.value.detail.startswith("Invalid filter: ")
