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
import os

import pytest
import requests
import yaml
from fastapi.testclient import TestClient
from pytest_httpx import HTTPXMock
from rs_server_common.authentication.apikey import APIKEY_HEADER, ttl_cache
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.pytest_utils import mock_oauth2
from rs_server_staging.main import app, must_be_authenticated
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_302_FOUND,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

logger = Logging.default(__name__)

# Dummy api key values
VALID_APIKEY = "VALID_API_KEY"
WRONG_APIKEY = "WRONG_APIKEY"

# Pass the api key in HTTP header
VALID_APIKEY_HEADER = {"headers": {APIKEY_HEADER: VALID_APIKEY}}
WRONG_APIKEY_HEADER = {"headers": {APIKEY_HEADER: WRONG_APIKEY}}

OAUTH2_AUTHORIZATION_ENDPOINT = "http://OAUTH2_AUTHORIZATION_ENDPOINT"
OAUTH2_TOKEN_ENDPOINT = "http://OAUTH2_TOKEN_ENDPOINT"  # nosec

RSPY_UAC_CHECK_URL = "http://RSPY_UAC_CHECK_URL"
# os.environ["RSPY_UAC_CHECK_URL"] = RSPY_UAC_CHECK_URL


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

    # Mock cluster mode to enable authentication. See: https://stackoverflow.com/a/69685866
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


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
@pytest.mark.parametrize("test_apikey", [True, False], ids=["test_apikey", "no_apikey"])
@pytest.mark.parametrize("test_oauth2", [True, False], ids=["test_oauth2", "no_oauth2"])
async def test_error_when_not_authenticated(mocker, staging_client, httpx_mock: HTTPXMock, test_apikey, test_oauth2):
    """
    Test that all the http endpoints are protected and return 401 or 403 if not authenticated.
    """
    owner_id = "pyteam"
    await init_test(
        mocker,
        httpx_mock,
        staging_client,
        test_apikey,
        test_oauth2,
        [],
        mock_wrong_apikey=True,
        user_login=owner_id,
    )
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # For each route and method from the openapi specification i.e. with the /processes/ and /jobs/ prefixes
    for path, methods in app.openapi()["paths"].items():
        if not must_be_authenticated(path):
            continue
        for method in methods.keys():

            endpoint = path.format(resource="staging", job_id="job_id")
            logger.debug(f"Test the {endpoint!r} [{method}] authentication")

            from rs_server_staging.rspy_models import ProcessMetadataModel

            bp = 0

            # With a valid apikey or oauth2 authentication, we should have a status code != 401 or 403.
            # We have other errors on many endpoints because we didn't give the right arguments,
            # but it's OK it is not what we are testing here.
            if test_apikey or test_oauth2:
                response = staging_client.request(method, endpoint, json={1: 2}, **header)
                logger.debug(response)
                assert response.status_code not in (
                    HTTP_401_UNAUTHORIZED,
                    HTTP_403_FORBIDDEN,
                    HTTP_422_UNPROCESSABLE_ENTITY,  # with 422, the authentication is not called and not tested
                )

                # With a wrong apikey, we should have a 403 error
                if test_apikey:
                    assert (
                        staging_client.request(method, endpoint, **WRONG_APIKEY_HEADER).status_code
                        == HTTP_403_FORBIDDEN
                    )

            # Check that without authentication, the endpoint is protected and we receive a 401
            else:
                assert staging_client.request(method, endpoint).status_code == HTTP_401_UNAUTHORIZED


def test_authenticated_endpoints():
    """Test that the catalog endpoints need authentication."""
    for route_path in ["/_mgmt/ping", "/catalog/api", "/catalog/api.html", "/auth/", "/health"]:
        assert not must_be_authenticated(route_path)
    for route_path in [
        "/catalog",
        "/catalog/",
        "/catalog/conformance",
        "/catalog/collections",
        "/catalog/search",
        "/catalog/queryables",
    ]:
        assert must_be_authenticated(route_path)
