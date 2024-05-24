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

"""Unit tests for the authentication."""

import json

import pytest
from fastapi.routing import APIRoute
from pytest_httpx import HTTPXMock
from rs_server_common.authentication import APIKEY_HEADER, apikey_security, ttl_cache
from rs_server_common.utils.logging import Logging
from starlette.datastructures import State
from starlette.status import (
    HTTP_200_OK,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
)

# Dummy url for the uac manager check endpoint
RSPY_UAC_CHECK_URL = "http://www.rspy-uac-manager.com"

# Dummy api key values
VALID_APIKEY = "VALID_API_KEY"
WRONG_APIKEY = "WRONG_APIKEY"

# Parametrize the fastapi_app fixture from conftest to enable authentication
CLUSTER_MODE = {"RSPY_LOCAL_MODE": False}

logger = Logging.default(__name__)


async def test_cached_apikey_security(monkeypatch, httpx_mock: HTTPXMock):
    """
    Test that we are caching the call results to the apikey_security function, that calls the
    apikey manager service and keycloak to check the apikey validity and information.
    """

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    # The function is updating request.state. We don't have a request object here,
    # so just create a dummy one of type State = an object that can be used to store arbitrary state.
    dummy_request = State()
    dummy_request.state = State()

    # Initial response expected from the function
    initial_response = {
        "iam_roles": ["initial", "roles"],
        "config": {"initial": "config"},
        "user_login": "initial_login",
    }

    # Clear the cached response and mock the uac manager response
    ttl_cache.clear()
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json=initial_response,
    )

    # Check the apikey_security result
    await apikey_security(dummy_request, VALID_APIKEY)  # , "")
    assert dummy_request.state.auth_roles == initial_response["iam_roles"]
    assert dummy_request.state.auth_config == initial_response["config"]
    assert dummy_request.state.user_login == initial_response["user_login"]

    # If the UAC manager response changes, we won't see it because the previous result was cached
    modified_response = {
        "iam_roles": ["modified", "roles"],
        "config": {"modified": "config"},
        "user_login": "modified_login",
    }
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json=modified_response,
    )

    # Still the initial response !
    for _ in range(100):
        await apikey_security(dummy_request, VALID_APIKEY)  # , "")
        assert dummy_request.state.auth_roles == initial_response["iam_roles"]
        assert dummy_request.state.auth_config == initial_response["config"]
        assert dummy_request.state.user_login == initial_response["user_login"]

    # We have to clear the cache to obtain the modified response
    ttl_cache.clear()
    await apikey_security(dummy_request, VALID_APIKEY)  # , "")
    assert dummy_request.state.auth_roles == modified_response["iam_roles"]
    assert dummy_request.state.auth_config == modified_response["config"]
    assert dummy_request.state.user_login == modified_response["user_login"]


@pytest.mark.parametrize("fastapi_app", [CLUSTER_MODE], indirect=["fastapi_app"], ids=["cluster_mode"])
async def test_authentication(fastapi_app, client, monkeypatch, httpx_mock: HTTPXMock):
    """
    Test that all the http endpoints are protected and return 403 if not authenticated.
    """

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    # With a valid api key in headers, the uac manager will give access to the endpoint
    ttl_cache.clear()  # clear the cached response
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        # NOTE: we could use other roles and config, to be discussed
        json={"iam_roles": [], "config": {}, "user_login": {}},
    )

    # With a wrong api key, it returns 403
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: WRONG_APIKEY},
        status_code=HTTP_403_FORBIDDEN,
    )

    # For each api endpoint (except the technical endpoints)
    for route in fastapi_app.router.routes:
        if (not isinstance(route, APIRoute)) or (route.path in ("/", "/health")):
            continue

        # For each method (get, post, ...)
        for method in route.methods:
            endpoint = route.path.replace("/cadip/{station}", "/cadip/cadip")
            logger.debug(f"Test the {route.path!r} [{method}] authentication")

            # Check that without api key in headers, the endpoint is protected and we receive a 403
            assert client.request(method, endpoint).status_code == HTTP_403_FORBIDDEN

            # Test a valid and wrong api key values in headers
            assert (
                client.request(method, endpoint, headers={APIKEY_HEADER: VALID_APIKEY}).status_code
                != HTTP_403_FORBIDDEN
            )
            assert (
                client.request(method, endpoint, headers={APIKEY_HEADER: WRONG_APIKEY}).status_code
                == HTTP_403_FORBIDDEN
            )

            # Idem by passing the api key by url query parameter (disabled for now)
            # assert (
            #     client.request(method, endpoint, params={APIKEY_QUERY: VALID_APIKEY}).status_code \
            #     != HTTP_403_FORBIDDEN
            # )
            # assert (
            #     client.request(method, endpoint, params={APIKEY_QUERY: WRONG_APIKEY}).status_code \
            #     == HTTP_403_FORBIDDEN
            # )


UNKNOWN_CADIP_STATION = "unknown-cadip-station"

ADGS_STATIONS = ["adgs"]
CADIP_STATIONS = ["ins", "mps", "mti", "nsg", "sgs", "cadip", UNKNOWN_CADIP_STATION]

DATE_PARAM = {"datetime": "2014-01-01T12:00:00Z/2023-02-02T23:59:59Z"}
NAME_PARAM = {"name": "TEST_FILE.raw"}


@pytest.mark.parametrize(
    "fastapi_app, endpoint, method, stations, query_params, expected_role",
    [
        [CLUSTER_MODE, "/adgs/aux/search", "GET", ADGS_STATIONS, DATE_PARAM, "rs_adgs_read"],
        [CLUSTER_MODE, "/adgs/aux", "GET", ADGS_STATIONS, NAME_PARAM, "rs_adgs_download"],
        [CLUSTER_MODE, "/adgs/aux/status", "GET", ADGS_STATIONS, NAME_PARAM, "rs_adgs_download"],
        [CLUSTER_MODE, "/cadip/{station}/cadu/search", "GET", CADIP_STATIONS, DATE_PARAM, "rs_cadip_{station}_read"],
        [CLUSTER_MODE, "/cadip/{station}/cadu", "GET", CADIP_STATIONS, NAME_PARAM, "rs_cadip_{station}_download"],
        [
            CLUSTER_MODE,
            "/cadip/{station}/cadu/status",
            "GET",
            CADIP_STATIONS,
            NAME_PARAM,
            "rs_cadip_{station}_download",
        ],
    ],
    indirect=["fastapi_app"],
    ids=[
        "/adgs/aux/search",
        "/adgs/aux",
        "/adgs/aux/status",
        "/cadip/{station}/cadu/search",
        "/cadip/{station}/cadu",
        "/cadip/{station}/cadu/status",
    ],
)
async def test_authentication_roles(  # pylint: disable=too-many-arguments,too-many-locals
    fastapi_app,  # pylint: disable=unused-argument
    client,
    monkeypatch,
    httpx_mock: HTTPXMock,
    endpoint,
    method,
    stations,
    query_params,
    expected_role,
):
    """
    Test that the api key has the right roles for the http endpoints.
    """

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    def mock_uac_response(_json: dict):
        """Mock the UAC response. Clear the cached response everytime."""
        ttl_cache.clear()
        httpx_mock.add_response(
            url=RSPY_UAC_CHECK_URL,
            match_headers={APIKEY_HEADER: VALID_APIKEY},
            status_code=HTTP_200_OK,
            json=_json,
        )

    def client_request(station_endpoint: str):  # , by_headers: bool):
        """Request endpoint."""
        # if by_headers:
        return client.request(method, station_endpoint, params=query_params, headers={APIKEY_HEADER: VALID_APIKEY})
        # # Else, by query param (disabled for now)
        # return client.request(method, station_endpoint, params={**query_params, APIKEY_QUERY: VALID_APIKEY})

    # Test the api key passed in http header then url query parameter (disabled for now)
    # for by_headers in [True, False]:

    # for each cadip station or just "adgs"
    for station in stations:
        # Replace the station in the endpoint and expected role
        station_endpoint = endpoint.format(station=station)
        station_role = expected_role.format(station=station)

        logger.debug(f"Test the {station_endpoint!r} [{method}] authentication roles")

        # With no roles ...
        mock_uac_response({"iam_roles": [], "config": {}, "user_login": {}})
        response = client_request(station_endpoint)

        # Test the error message with an unknown cadip station
        if station == UNKNOWN_CADIP_STATION:
            assert response.status_code == HTTP_400_BAD_REQUEST
            assert f"Unknown CADIP station: {station!r}" in json.loads(response.content)["detail"]
            break  # no need to test the other endpoints

        # Else, with a valid station, we should receive an unauthorized response
        assert response.status_code == HTTP_401_UNAUTHORIZED

        # Idem with non-relevant roles
        mock_uac_response({"iam_roles": ["any", "non-relevant", "roles"], "config": {}, "user_login": {}})
        assert client_request(station_endpoint).status_code == HTTP_401_UNAUTHORIZED

        # With the right expected role, we should be authorized (no 401 or 403)
        mock_uac_response({"iam_roles": [station_role], "config": {}, "user_login": {}})
        assert client_request(station_endpoint).status_code not in (
            HTTP_401_UNAUTHORIZED,
            HTTP_403_FORBIDDEN,
        )

        # It should also work if other random roles are present
        mock_uac_response({"iam_roles": [station_role, "any", "other", "role"], "config": {}, "user_login": {}})
        assert client_request(station_endpoint).status_code not in (
            HTTP_401_UNAUTHORIZED,
            HTTP_403_FORBIDDEN,
        )
