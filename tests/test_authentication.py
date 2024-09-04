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

import httpx
import pytest
import responses
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from keycloak import KeycloakAdmin
from pytest_httpx import HTTPXMock
from rs_server_common.authentication import oauth2
from rs_server_common.authentication.apikey import APIKEY_HEADER, ttl_cache
from rs_server_common.authentication.authentication import authenticate
from rs_server_common.utils.logging import Logging
from starlette.datastructures import State
from starlette.responses import RedirectResponse
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
    await authenticate(dummy_request, VALID_APIKEY)
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
        await authenticate(dummy_request, VALID_APIKEY)
        assert dummy_request.state.auth_roles == initial_response["iam_roles"]
        assert dummy_request.state.auth_config == initial_response["config"]
        assert dummy_request.state.user_login == initial_response["user_login"]

    # We have to clear the cache to obtain the modified response
    ttl_cache.clear()
    await authenticate(dummy_request, VALID_APIKEY)
    assert dummy_request.state.auth_roles == modified_response["iam_roles"]
    assert dummy_request.state.auth_config == modified_response["config"]
    assert dummy_request.state.user_login == modified_response["user_login"]


async def mock_oauth2(
    mocker,
    client: TestClient,
    endpoint: str,
    user_id: str,
    username: str,
    iam_roles: list[str],
    enabled: bool = True,
    headers: dict = {},
) -> httpx.Response:
    """Mock the OAuth2 authorization code flow process."""

    # Clear the cookies, except for the logout endpoint which do it itself
    if endpoint.endswith("/logout"):
        assert "session" in dict(client.cookies)
    else:
        client.cookies = None

    # If we are not loging from the console, we simulate the fact that our request comes from a browser
    login_from_console = endpoint.endswith(oauth2.LOGIN_FROM_CONSOLE)
    headers["user-agent"] = "Mozilla/"

    # The 1st step of the oauth2 authorization code flow returns a redirection to the keycloak login page.
    # After login, it returns a redirection to the original calling endpoint, but this time
    # with a 'code' and 'state' params.
    # Here we do not test the keycloak login page, we only mock the last redirection.
    mocker.patch.object(
        StarletteOAuth2App,
        "authorize_redirect",
        return_value=RedirectResponse(f"{endpoint}?code=my_code&state=my_state", status_code=302),
    )

    # The 2nd step checks the 'code' and 'state' params then returns a dict which contains the user information
    mocker.patch.object(
        StarletteOAuth2App,
        "authorize_access_token",
        return_value={"userinfo": {"sub": user_id, "preferred_username": username}},
    )

    # Then the service will ask for user information in KeyCloak
    mocker.patch.object(KeycloakAdmin, "get_user", return_value={"enabled": enabled})
    mocker.patch.object(
        KeycloakAdmin,
        "get_composite_realm_roles_of_user",
        return_value=[{"name": role} for role in iam_roles],
    )

    # Call the endpoint that will run the oauth2 authentication process
    response = client.get(endpoint, headers=headers)

    # From the console, the redirection after the 1st step must be done manually
    if login_from_console:
        assert response.is_success
        response = client.get(response.json())

    # After this, if successful, we should have a cookie with the authentication information.
    # Except for the logout endpoint which should have removed the cookie.
    if response.is_success:
        has_cookie = not endpoint.endswith("/logout")
        assert ("session" in dict(client.cookies)) == has_cookie

    return response


@responses.activate
@pytest.mark.parametrize("fastapi_app", [CLUSTER_MODE], indirect=["fastapi_app"], ids=["cluster_mode"])
async def test_oauth2(fastapi_app, mocker, client):  # pylint: disable=unused-argument
    """Test all the OAuth2 authentication endpoints."""

    # @router.get("/me")
    # async def show_my_information(auth_info: Annotated[AuthInfo, Depends(get_user_info)]):
    #     """Show user information."""
    #     return {
    #         "user_login": auth_info.user_login,
    #         "iam_roles": sorted(auth_info.iam_roles),
    #     }

    user_id = "user_id"
    username = "username"
    roles = ["role2", "role1", "role3"]

    # If we called the 'login from browser' endpoint, we should be redirected to the swagger homepage
    response = await mock_oauth2(mocker, client, "/auth/login", user_id, username, roles, enabled=False)
    assert response.status_code == HTTP_401_UNAUTHORIZED
    response = await mock_oauth2(mocker, client, "/auth/login", user_id, username, roles)
    assert response.request.url.path == "/docs"

    # If we called the 'login from console' endpoint, we should get a string response
    response = await mock_oauth2(mocker, client, "/auth/login_from_console", user_id, username, roles, enabled=False)
    assert response.status_code == HTTP_401_UNAUTHORIZED
    response = await mock_oauth2(mocker, client, "/auth/login_from_console", user_id, username, roles)
    assert response.content == client.get("/auth/console_logged_message").content

    # responses.get(url=RSPY_UAC_CHECK_URL, status=200, json=initial_response)
    response = await mock_oauth2(mocker, client, "/auth/logout", user_id, username, roles)
    assert response.content.decode() == "You are logged out."

    # response = client.get("/auth/me")
    # assert response.is_success


@pytest.mark.parametrize("fastapi_app", [CLUSTER_MODE], indirect=["fastapi_app"], ids=["cluster_mode"])
async def test_authentication(fastapi_app, client, monkeypatch, httpx_mock: HTTPXMock):
    """
    Test that all the http endpoints are protected and return 401 or 403 if not authenticated.
    """

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    # With a valid api key in headers, the uac manager will give access to the endpoint
    ttl_cache.clear()  # clear the cached response
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": [], "config": {}, "user_login": {}},
    )

    # With a wrong api key, it returns 403
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: WRONG_APIKEY},
        status_code=HTTP_403_FORBIDDEN,
    )

    # For each api endpoint (except the technical and oauth2 endpoints)
    for route in fastapi_app.router.routes:
        if (not isinstance(route, APIRoute)) or (route.path in ("/", "/health")) or route.path.startswith("/auth/"):
            continue

        # For each method (get, post, ...)
        for method in route.methods:
            # For new cadip endpoint, mention a valid-defined collection, either as an argument or in endpoint.
            if route.path in ["/cadip/search", "/cadip/search/items"]:
                route.path += "?collection=cadip_valid_auth"
            endpoint = route.path.replace("/cadip/collections/{collection_id}", "/cadip/collections/cadip_valid_auth")

            logger.debug(f"Test the {route.path!r} [{method}] authentication")

            # Check that without api key in headers, the endpoint is protected and we receive a 401
            assert client.request(method, endpoint).status_code == HTTP_401_UNAUTHORIZED

            # Test a valid and wrong api key values in headers
            assert (
                client.request(method, endpoint, headers={APIKEY_HEADER: VALID_APIKEY}).status_code
                != HTTP_403_FORBIDDEN
            )
            assert (
                client.request(method, endpoint, headers={APIKEY_HEADER: WRONG_APIKEY}).status_code
                == HTTP_403_FORBIDDEN
            )


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
        [CLUSTER_MODE, "/cadip/collections/{station}", "GET", CADIP_STATIONS, DATE_PARAM, "rs_cadip_{station}_read"],
        [
            CLUSTER_MODE,
            "/cadip/collections/{station}/items",
            "GET",
            CADIP_STATIONS,
            DATE_PARAM,
            "rs_cadip_{station}_read",
        ],
        [
            CLUSTER_MODE,
            "/cadip/collections/{station}/items/specific_sid",
            "GET",
            CADIP_STATIONS,
            DATE_PARAM,
            "rs_cadip_{station}_read",
        ],
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
        "/cadip/collections/{station}/items",
        "/cadip/collections/{station}/items/specific_sid",
    ],
)
async def test_authentication_roles(  # pylint: disable=too-many-arguments,too-many-locals
    auth,
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

    def client_request(station_endpoint: str):
        """Request endpoint."""
        return client.request(method, station_endpoint, params=query_params, headers={APIKEY_HEADER: VALID_APIKEY})

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
