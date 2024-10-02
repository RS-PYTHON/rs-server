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
import responses
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi.routing import APIRoute
from pytest_httpx import HTTPXMock
from rs_server_common.authentication import authentication
from rs_server_common.authentication.apikey import APIKEY_HEADER, ttl_cache
from rs_server_common.authentication.authentication import authenticate
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.pytest_utils import mock_oauth2
from rs_server_common.utils.utils2 import AuthInfo
from starlette import status
from starlette.datastructures import State

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
        status_code=status.HTTP_200_OK,
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
        status_code=status.HTTP_200_OK,
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


@responses.activate
@pytest.mark.parametrize("fastapi_app", [CLUSTER_MODE], indirect=["fastapi_app"], ids=["cluster_mode"])
async def test_oauth2_security(fastapi_app, mocker, client):  # pylint: disable=unused-argument
    """Test all the OAuth2 authentication endpoints."""

    user_id = "user_id"
    username = "username"
    roles = ["role2", "role1", "role3"]

    # If we call the 'login from browser' endpoint, we should be redirected to the swagger homepage
    response = await mock_oauth2(
        mocker,
        client,
        "/auth/login",
        user_id,
        username,
        roles,
        enabled=False,
        assert_success=False,
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    response = await mock_oauth2(mocker, client, "/auth/login", user_id, username, roles)
    assert response.request.url.path == "/docs"

    # If we call the 'login from console' endpoint, we should get a string response
    response = await mock_oauth2(
        mocker,
        client,
        "/auth/login_from_console",
        user_id,
        username,
        roles,
        enabled=False,
        assert_success=False,
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    response = await mock_oauth2(mocker, client, "/auth/login_from_console", user_id, username, roles)
    assert response.content == client.get("/auth/console_logged_message").content

    # To test the logout endpoint, we must mock other oauth2 and keycloack functions and endpoints
    oauth2_end_session_endpoint = "http://oauth2_end_session_endpoint"
    mocker.patch.object(
        StarletteOAuth2App,
        "load_server_metadata",
        return_value={"end_session_endpoint": oauth2_end_session_endpoint},
    )
    response = await mock_oauth2(mocker, client, "/auth/logout", user_id, username, roles)
    assert response.request.url == oauth2_end_session_endpoint

    # Test endpoints that require the oauth2 authentication
    response = await mock_oauth2(
        mocker,
        client,
        "/auth/me",
        user_id,
        username,
        roles,
        enabled=False,
        assert_success=False,
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    response = await mock_oauth2(mocker, client, "/auth/me", user_id, username, roles)
    assert response.json() == {"user_login": username, "iam_roles": sorted(roles)}


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
@pytest.mark.parametrize("test_apikey", [True, False], ids=["test_apikey", "no_apikey"])
@pytest.mark.parametrize("test_oauth2", [True, False], ids=["test_oauth2", "no_oauth2"])
@pytest.mark.parametrize("fastapi_app", [CLUSTER_MODE], indirect=["fastapi_app"], ids=["cluster_mode"])
async def test_endpoints_security(  # pylint: disable=too-many-arguments, too-many-locals
    fastapi_app,
    client,
    mocker,
    monkeypatch,
    httpx_mock: HTTPXMock,
    test_apikey: bool,
    test_oauth2: bool,
):
    """
    Test that all the http endpoints are protected and return 401 or 403 if not authenticated.
    """
    # Mock the env var RSPY_USE_MODULE_FOR_STATION_TOKEN to True. This will trigger the
    # usage of the internal token module  for getting the token and setting it to the eodag
    mocker.patch("rs_server_common.authentication.authentication_to_external.env_bool", return_value=True)

    # Patch the global variables. See: https://stackoverflow.com/a/69685866
    mocker.patch("rs_server_common.authentication.authentication.FROM_PYTEST", new=True, autospec=False)

    # Spy on the authenticate function call
    spy_authenticate = mocker.spy(authentication, "authenticate_from_pytest")

    # Dummy endpoint arguments
    endpoint_params = {
        "collection": "cadip_valid_auth",
        "datetime": None,
        "name": None,
    }

    # The user, authenticated with oauth2, can also use an apikey created by another user.
    # In this case, the apikey authentication has higher priority and should be used.
    roles = [
        "rs_adgs_read",
        "rs_adgs_download",
        "rs_cadip_cadip_read",
        "rs_cadip_cadip_download",
        "rs_cadip_landing_page",
    ]
    apikey_username = "APIKEY_USERNAME"
    apikey_roles = ["apikey_role1", "apikey_role2", *roles]
    apikey_config = {"apikey": "config"}
    oauth2_user_id = "OAUTH2_USER_ID"
    oauth2_username = "OAUTH2_USERNAME"
    oauth2_roles = ["oauth2_role1", "oauth2_role2", *roles]
    oauth2_config: dict = {}  # not apikey configuration with oauth2 !

    # Clear oauth2 cookies
    client.cookies.clear()

    if test_apikey:
        # Mock the uac manager url
        monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

        # With a valid api key in headers, the uac manager will give access to the endpoint
        ttl_cache.clear()  # clear the cached response
        httpx_mock.add_response(
            url=RSPY_UAC_CHECK_URL,
            match_headers={APIKEY_HEADER: VALID_APIKEY},
            status_code=status.HTTP_200_OK,
            json={"user_login": apikey_username, "iam_roles": apikey_roles, "config": apikey_config},
        )

        # With a wrong api key, it returns 403
        httpx_mock.add_response(
            url=RSPY_UAC_CHECK_URL,
            match_headers={APIKEY_HEADER: WRONG_APIKEY},
            status_code=status.HTTP_403_FORBIDDEN,
        )

    # If we test the oauth2 authentication, we login the user.
    # His authentication information is saved in the client session cookies.
    if test_oauth2:
        await mock_oauth2(mocker, client, "/auth/login", oauth2_user_id, oauth2_username, oauth2_roles)

    # For each api endpoint (except the technical and oauth2 endpoints)
    for route in fastapi_app.router.routes:
        if (not isinstance(route, APIRoute)) or (route.path in ("/", "/health")) or route.path.startswith("/auth/"):
            continue

        # For each method (get, post, ...)
        for method in route.methods:
            # For new cadip endpoint, mention a valid-defined collection, either as an argument or in endpoint.
            endpoint = route.path.replace(
                "/cadip/collections/{collection_id}",
                f"/cadip/collections/{endpoint_params['collection']}",
            ).format(session_id="session_id", station="cadip")

            logger.debug(f"Test the {endpoint!r} [{method}] authentication")

            # With a valid apikey or oauth2 authentication, we should have a status code != 401 or 403.
            # We have other errors on many endpoints because we didn't give the right arguments,
            # but it's OK it is not what we are testing here.
            if test_apikey or test_oauth2:
                spy_authenticate.reset_mock()
                response = client.request(
                    method,
                    endpoint,
                    headers={APIKEY_HEADER: VALID_APIKEY} if test_apikey else None,
                )
                logger.debug(response)
                assert response.status_code not in (
                    status.HTTP_401_UNAUTHORIZED,
                    status.HTTP_403_FORBIDDEN,
                )

                # With a wrong apikey, we should have a 403 error
                if test_apikey:
                    assert (
                        client.request(method, endpoint, headers={APIKEY_HEADER: WRONG_APIKEY}).status_code
                        == status.HTTP_403_FORBIDDEN
                    )

                # Test that the authenticate function was called only once
                # and that the apikey information is set rather thatn oauth2 if both are available.
                spy_authenticate.assert_called_once()
                if test_apikey:
                    assert spy_authenticate.spy_return == AuthInfo(
                        apikey_username,
                        apikey_roles,
                        apikey_config,
                    )
                elif test_oauth2:
                    assert spy_authenticate.spy_return == AuthInfo(
                        oauth2_username,
                        oauth2_roles,
                        oauth2_config,
                    )

            # Check that without authentication, the endpoint is protected and we receive a 401
            else:
                assert (
                    client.request(method, endpoint, params=endpoint_params).status_code == status.HTTP_401_UNAUTHORIZED
                )


UNKNOWN_CADIP_STATION = "unknown-cadip-station"

ADGS_STATIONS = ["adgs"]
CADIP_STATIONS = ["ins", "mps", "mti", "nsg", "sgs", "cadip", UNKNOWN_CADIP_STATION]

DATE_PARAM = {"datetime": "2014-01-01T12:00:00Z/2023-02-02T23:59:59Z"}
NAME_PARAM = {"name": "TEST_FILE.raw"}


@pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
@pytest.mark.parametrize(
    "fastapi_app, endpoint, method, stations, query_params, expected_role",
    [
        [CLUSTER_MODE, "/adgs/aux/search", "GET", ADGS_STATIONS, DATE_PARAM, "rs_adgs_read"],
        [CLUSTER_MODE, "/adgs/aux", "GET", ADGS_STATIONS, NAME_PARAM, "rs_adgs_download"],
        [CLUSTER_MODE, "/adgs/aux/status", "GET", ADGS_STATIONS, NAME_PARAM, "rs_adgs_download"],
        [CLUSTER_MODE, "/cadip", "GET", CADIP_STATIONS, NAME_PARAM, "rs_cadip_landing_page"],
        [CLUSTER_MODE, "/cadip/collections", "GET", CADIP_STATIONS, NAME_PARAM, "rs_cadip_landing_page"],
        [
            CLUSTER_MODE,
            "/cadip/collections/{collection_id}",
            "GET",
            CADIP_STATIONS,
            DATE_PARAM,
            "rs_cadip_{station}_read",
        ],
        [
            CLUSTER_MODE,
            "/cadip/collections/{collection_id}/items",
            "GET",
            CADIP_STATIONS,
            DATE_PARAM,
            "rs_cadip_{station}_read",
        ],
        [
            CLUSTER_MODE,
            "/cadip/collections/{collection_id}/items/specific_sid",
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
        "/cadip",
        "/cadip/collections",
        "/cadip/collections/{collection_id}",
        "/cadip/collections/{collection_id}/items",
        "/cadip/collections/{collection_id}/items/specific_sid",
        "/cadip/{station}/cadu",
        "/cadip/{station}/cadu/status",
    ],
)
async def test_endpoint_roles(  # pylint: disable=too-many-arguments,too-many-locals
    fastapi_app,  # pylint: disable=unused-argument
    client,
    mocker,
    monkeypatch,
    httpx_mock: HTTPXMock,
    test_apikey,
    test_oauth2,
    endpoint,
    method,
    stations,
    query_params,
    expected_role,
):
    """
    Test that the api key has the right roles for the http endpoints.
    """
    # Mock the env var RSPY_USE_MODULE_FOR_STATION_TOKEN to True. This will trigger the
    # usage of the internal token module  for getting the token and setting it to the eodag
    mocker.patch("rs_server_common.authentication.authentication_to_external.env_bool", return_value=True)
    # Mock the uac manager url
    if test_apikey:
        monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    async def mock_response(user_info: dict):
        """Mock the apikey or oauth2 authentication."""

        # Clear oauth2 cookies
        client.cookies.clear()

        # Mock the UAC response. Clear the cached response everytime.
        if test_apikey:
            ttl_cache.clear()
            httpx_mock.add_response(
                url=RSPY_UAC_CHECK_URL,
                match_headers={APIKEY_HEADER: VALID_APIKEY},
                status_code=status.HTTP_200_OK,
                json=user_info,
            )

        # Login the user with oauth2.
        # His authentication information is saved in the client session cookies.
        elif test_oauth2:
            await mock_oauth2(
                mocker,
                client,
                "/auth/login",
                "oauth2_user_id",
                user_info["user_login"],
                user_info["iam_roles"],
            )

    def client_request(station_endpoint: str):
        """Request endpoint."""
        return client.request(
            method,
            station_endpoint,
            params=query_params,
            headers={APIKEY_HEADER: VALID_APIKEY} if test_apikey else None,
        )

    # for each cadip station or just "adgs"
    for station in stations:
        # Replace the station in the endpoint and expected role
        station_endpoint = endpoint.format(collection_id=station, station=station)
        station_role = expected_role.format(station=station)

        logger.debug(f"Test the {station_endpoint!r} [{method}] authentication roles")

        # With no roles ...
        await mock_response({"iam_roles": [], "config": {}, "user_login": {}})
        response = client_request(station_endpoint)

        # Test the error message with an unknown cadip station or collection,
        # skip for landing_pages since no need for stations.
        if station == UNKNOWN_CADIP_STATION and "landing_page" not in station_role:
            message = json.loads(response.content)["detail"]
            assert (
                response.status_code == status.HTTP_401_UNAUTHORIZED
                and f"Authorization does not include the right role to download from the 'cadip_{station}' station"
                in message
            ) or (
                response.status_code == status.HTTP_404_NOT_FOUND
                and f"Unknown CADIP collection: {station!r}" in message
            )
            break  # no need to test the other endpoints

        # Else, with a valid station, we should receive an unauthorized response
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        # Idem with non-relevant roles
        await mock_response({"iam_roles": ["any", "non-relevant", "roles"], "config": {}, "user_login": {}})
        assert client_request(station_endpoint).status_code == status.HTTP_401_UNAUTHORIZED

        # With the right expected role, we should be authorized (no 401 or 403)
        await mock_response({"iam_roles": [station_role], "config": {}, "user_login": {}})
        assert client_request(station_endpoint).status_code not in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )

        # It should also work if other random roles are present
        await mock_response({"iam_roles": [station_role, "any", "other", "role"], "config": {}, "user_login": {}})
        assert client_request(station_endpoint).status_code not in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )
