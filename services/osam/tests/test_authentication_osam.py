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

"""Unit tests for the authentication."""

# pylint: disable = duplicate-code
from typing import cast

import pytest
from pytest_httpx import HTTPXMock
from rs_server_common.authentication import apikey, authentication
from rs_server_common.authentication.apikey import APIKEY_HEADER
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.pytest.pytest_utils import mock_oauth2
from rs_server_common.utils.utils2 import AuthInfo
from rs_server_osam import main
from starlette import status
from starlette.routing import Route

# Dummy url for the uac manager check endpoint
RSPY_UAC_CHECK_URL = "http://www.rspy-uac-manager.com"

# Dummy api key values
VALID_APIKEY = "VALID_API_KEY"
WRONG_APIKEY = "WRONG_APIKEY"

# Parametrize the fastapi_app fixture from conftest to enable authentication
CLUSTER_MODE = {"RSPY_LOCAL_MODE": False}

logger = Logging.default(__name__)


@pytest.fixture(autouse=True)
def mock_endpoint_functions(
    mocker,
    osam_client,  # run this fixture after osam_client # pylint: disable=unused-argument
):
    """Mock all functions called by the endpoints"""
    mocker.patch("rs_server_osam.main.__get_user_rights", return_value={"user": {}})
    mocker.patch("rs_server_osam.main.apply_user_access_policy", return_value=[True, "msg"])
    mocker.patch("rs_server_osam.main.get_user_s3_credentials", return_value={})
    mocker.patch("rs_server_osam.main.load_configmap_data", return_value=[])


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
@pytest.mark.parametrize("test_apikey", [True, False], ids=["test_apikey", "no_apikey"])
@pytest.mark.parametrize("test_oauth2", [True, False], ids=["test_oauth2", "no_oauth2"])
@pytest.mark.parametrize("osam_client", [CLUSTER_MODE], indirect=["osam_client"], ids=["cluster_mode"])
async def test_endpoints_security(  # pylint: disable=too-many-locals
    osam_client,
    mocker,
    monkeypatch,
    httpx_mock: HTTPXMock,
    test_apikey: bool,
    test_oauth2: bool,
):
    """
    Test that all the http endpoints are protected and return 401 or 403 if not authenticated.
    """
    # This code is copy/pasted from rs-server. Use the same variable names.
    client = osam_client
    fastapi_app = main.app

    # Patch the global variables. See: https://stackoverflow.com/a/69685866
    mocker.patch("rs_server_common.authentication.authentication.FROM_PYTEST", new=True, autospec=False)

    # Spy on the authenticate function call
    spy_authenticate = mocker.spy(authentication, "authenticate_from_pytest")

    # Dummy endpoint arguments
    endpoint_params: dict = {}

    # The user, authenticated with oauth2, can also use an apikey created by another user.
    # In this case, the apikey authentication has higher priority and should be used.
    roles = ["rs_osam_update"]
    apikey_username = "APIKEY_USERNAME"
    apikey_roles = ["apikey_role1", "apikey_role2", *roles]
    apikey_config = {"apikey": "config"}
    oauth2_user_id = "OAUTH2_USER_ID"
    oauth2_username = "OAUTH2_USERNAME"
    oauth2_roles = ["oauth2_role1", "oauth2_role2", *roles]
    oauth2_attributes = {"attr1": "value1", "attr2": "value2"}
    monkeypatch.setenv("RSPY_OAUTH2_ATTRIBUTES", ",".join(oauth2_attributes.keys()))

    # Clear oauth2 cookies
    client.cookies.clear()

    if test_apikey:
        # Mock the uac manager url
        monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

        # With a valid api key in headers, the uac manager will give access to the endpoint
        apikey.ttl_cache.clear()  # clear the cached response
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
        await mock_oauth2(
            mocker,
            client,
            "/auth/login",
            oauth2_user_id,
            oauth2_username,
            oauth2_roles,
            oauth2_attributes,
        )

    # For each application endpoint
    for base_route in fastapi_app.router.routes:
        route = cast(Route, base_route)
        if not route.path.startswith("/storage/") or not route.methods:
            logger.debug(f"Skipping {route.path}")
            continue

        # For each method (get, post, ...)
        for method in route.methods:
            endpoint = route.path.format(user="any_user")
            logger.debug(f"Test the {endpoint!r} [{method}] authentication")

            # With a valid apikey or oauth2 authentication, we should have a 200 status code.
            if test_apikey or test_oauth2:
                spy_authenticate.reset_mock()
                response = client.request(
                    method,
                    endpoint,
                    headers={APIKEY_HEADER: VALID_APIKEY} if test_apikey else None,
                )
                logger.debug(response)
                assert response.status_code == status.HTTP_200_OK

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
                        oauth2_attributes,
                    )

            # Check that without authentication, the endpoint is protected and we receive a 401
            else:
                assert (
                    client.request(method, endpoint, params=endpoint_params).status_code == status.HTTP_401_UNAUTHORIZED
                )


@pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
@pytest.mark.parametrize("osam_client", [CLUSTER_MODE], indirect=["osam_client"], ids=["cluster_mode"])
@pytest.mark.parametrize(
    "endpoint, method, query_params, expected_role",
    [
        ["/storage/accounts/update", "POST", {}, "rs_osam_update"],
        ["/storage/account/any_user/update", "POST", {}, "rs_osam_update"],
        ["/storage/account/any_user/rights", "GET", {}, "rs_osam_update"],
        # No role needed
        ["/storage/account/credentials", "GET", {}, ""],
    ],
    ids=[
        "/storage/accounts/update",
        "/storage/account/{user}/update",
        "/storage/account/{user}/rights",
        "/storage/account/credentials",
    ],
)
async def test_endpoint_roles(  # pylint: disable=too-many-arguments,too-many-locals
    osam_client,
    mocker,
    monkeypatch,
    httpx_mock: HTTPXMock,
    test_apikey,
    test_oauth2,
    endpoint,
    method,
    query_params,
    expected_role,
):
    """
    Test that the api key has the right roles for the http endpoints.
    """
    # This code is copy/pasted from rs-server. Use the same variable names.
    client = osam_client

    # Mock the uac manager url
    if test_apikey:
        monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    async def mock_response(user_info: dict):
        """Mock the apikey or oauth2 authentication."""

        # Clear oauth2 cookies
        client.cookies.clear()

        # Mock the UAC response. Clear the cached response everytime.
        if test_apikey:
            apikey.ttl_cache.clear()
            httpx_mock.add_response(
                url=RSPY_UAC_CHECK_URL,
                match_headers={APIKEY_HEADER: VALID_APIKEY},
                status_code=status.HTTP_200_OK,
                json=user_info | {"config": {}},
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
                {},
            )

    def client_request(station_endpoint: str):
        """Request endpoint."""
        return client.request(
            method,
            station_endpoint,
            params=query_params,
            headers={APIKEY_HEADER: VALID_APIKEY} if test_apikey else None,
        )

    logger.debug(f"Test the {endpoint!r} [{method}] authentication roles")

    # If a role is expected but we provide none ...
    if expected_role:
        await mock_response({"iam_roles": [], "user_login": {}})
        response = client_request(endpoint)

        # ...we should receive an unauthorized response
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

        # Idem with non-relevant roles
        await mock_response({"iam_roles": ["any", "non-relevant", "roles"], "user_login": {}})
        assert client_request(endpoint).status_code == status.HTTP_401_UNAUTHORIZED

    # With the right expected role, we should be authorized
    await mock_response({"iam_roles": [expected_role], "user_login": {}})
    assert client_request(endpoint).status_code == status.HTTP_200_OK

    # It should also work if other random roles are present
    await mock_response({"iam_roles": [expected_role, "any", "other", "role"], "user_login": {}})
    assert client_request(endpoint).status_code == status.HTTP_200_OK
