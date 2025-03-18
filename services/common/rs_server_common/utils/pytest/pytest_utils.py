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

"""Utility functions used by the pytest unit tests."""

import httpx
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi.testclient import TestClient
from keycloak import KeycloakAdmin
from rs_server_common.authentication import oauth2
from starlette.responses import RedirectResponse


async def mock_oauth2(  # pylint: disable=too-many-arguments
    mocker,
    client: TestClient,
    endpoint: str,
    user_id: str,
    username: str,
    iam_roles: list[str],
    enabled: bool = True,
    assert_success: bool = True,
) -> httpx.Response:
    """
    Only for unit tests: mock the OAuth2 authorization code flow process.

    Args:
        mocker: pytest mocker
        client: pytest client
        endpoint: endpoint to test
        user_id: user id in keycloak
        username: username in keycloak
        iam_roles: user iam roles in keycloak
        enabled: is the user enabled in keycloak ?
        assert_success: is the login process expected to success ?
    """

    # Clear the cookies, except for the logout endpoint which do it itself
    logout = endpoint.endswith("/logout")
    if logout:
        assert "session" in dict(client.cookies)  # nosec
    else:
        client.cookies.clear()

    # If we are not loging from the console, we simulate the fact that our request comes from a browser
    login_from_console = endpoint.endswith(oauth2.LOGIN_FROM_CONSOLE)
    headers = {"user-agent": "Mozilla/"}

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

    # We need the client to follow redirections.
    # Note: even with this, the "login from browser" fails with a 400, I don't know why.
    # Use the "login from console instead".
    old_follow_redirects = client.follow_redirects
    try:
        client.follow_redirects = True

        # Call the endpoint that will run the oauth2 authentication process
        response = client.get(endpoint, headers=headers)

        # From the console, the redirection after the 1st step must be done manually
        if login_from_console:
            assert response.is_success  # nosec
            response = client.get(response.json())

    # Restore the redirections
    finally:
        client.follow_redirects = old_follow_redirects

    if assert_success:
        assert response.is_success  # nosec

    # After this, if successful, we should have a cookie with the authentication information.
    # Except for the logout endpoint which should have removed the cookie.
    has_cookie = response.is_success and not logout
    assert ("session" in dict(client.cookies)) == has_cookie  # nosec

    return response
