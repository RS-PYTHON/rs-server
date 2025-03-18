# Copyright 2025 CS Group
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

"""Utility authentication functions used by the pytest unit tests."""

import os

from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock
from rs_server_common.authentication.apikey import APIKEY_HEADER, ttl_cache
from starlette.status import HTTP_200_OK, HTTP_403_FORBIDDEN

RSPY_UAC_HOMEPAGE = "http://RSPY_UAC_HOMEPAGE"
RSPY_UAC_CHECK_URL = "http://RSPY_UAC_CHECK_URL"
OIDC_ENDPOINT = "http://OIDC_ENDPOINT"
OIDC_REALM = "OIDC_REALM"

# Dummy api key values
VALID_APIKEY = "VALID_API_KEY"
WRONG_APIKEY = "WRONG_APIKEY"

# Pass the api key in HTTP header
VALID_APIKEY_HEADER = {"headers": {APIKEY_HEADER: VALID_APIKEY}}
WRONG_APIKEY_HEADER = {"headers": {APIKEY_HEADER: WRONG_APIKEY}}

OAUTH2_AUTHORIZATION_ENDPOINT = "http://OAUTH2_AUTHORIZATION_ENDPOINT"
OAUTH2_TOKEN_ENDPOINT = "http://OAUTH2_TOKEN_ENDPOINT"  # nosec


def init_app_cluster_mode():
    """Init the FastAPI application with all the cluster mode features (local mode=0)"""

    os.environ["RSPY_LOCAL_MODE"] = "0"
    os.environ["RSPY_LOCAL_CATALOG_MODE"] = "1"
    os.environ["RSPY_CATALOG_BUCKET"] = "catalog-bucket"
    os.environ["RSPY_UAC_HOMEPAGE"] = RSPY_UAC_HOMEPAGE
    os.environ["RSPY_UAC_CHECK_URL"] = RSPY_UAC_CHECK_URL
    os.environ["OIDC_ENDPOINT"] = OIDC_ENDPOINT
    os.environ["OIDC_REALM"] = OIDC_REALM
    os.environ["OIDC_CLIENT_ID"] = "OIDC_CLIENT_ID"
    os.environ["OIDC_CLIENT_SECRET"] = "OIDC_CLIENT_SECRET"  # nosec
    os.environ["RSPY_COOKIE_SECRET"] = "RSPY_COOKIE_SECRET"  # nosec


async def init_test(
    mocker,
    httpx_mock: HTTPXMock,
    client: TestClient,
    test_apikey: bool,
    test_oauth2: bool,
    iam_roles: list[str],
    mock_wrong_apikey: bool = False,
    user_login="pyteam",
):
    """init mocker for tests."""

    # Needs init_app_cluster_mode()
    from rs_server_common.utils.pytest.pytest_utils import (  # pylint: disable=import-outside-toplevel
        mock_oauth2,
    )

    # Mock cluster mode to enable authentication. See: https://stackoverflow.com/a/69685866
    mocker.patch("rs_server_common.settings.LOCAL_MODE", new=False, autospec=False)
    mocker.patch("rs_server_common.settings.CLUSTER_MODE", new=True, autospec=False)

    # Clear oauth2 cookies
    client.cookies.clear()

    if test_apikey:
        # With a valid api key in headers, the uac manager will give access to the endpoint
        ttl_cache.clear()  # clear the cached response
        httpx_mock.add_response(
            url=RSPY_UAC_CHECK_URL,
            match_headers={APIKEY_HEADER: VALID_APIKEY},
            status_code=HTTP_200_OK,
            json={
                "name": "test_apikey",
                "user_login": user_login,
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": iam_roles,
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        # With a wrong api key, it returns 403
        if mock_wrong_apikey:
            httpx_mock.add_response(
                url=RSPY_UAC_CHECK_URL,
                match_headers={APIKEY_HEADER: WRONG_APIKEY},
                status_code=HTTP_403_FORBIDDEN,
            )

    # If we test the oauth2 authentication, we login the user.
    # His authentication information is saved in the client session cookies.
    # Note: we use the "login from console" because we need the client to follow redirections,
    # and they are disabled in these tests.
    if test_oauth2:
        await mock_oauth2(mocker, client, "/auth/login_from_console", "oauth2_user_id", user_login, iam_roles)

    # Mock the OAuth2 server responses that are used for the STAC extensions (not for the authentication)
    mocker.patch.object(
        StarletteOAuth2App,
        "load_server_metadata",
        return_value={"authorization_endpoint": OAUTH2_AUTHORIZATION_ENDPOINT, "token_endpoint": OAUTH2_TOKEN_ENDPOINT},
    )
