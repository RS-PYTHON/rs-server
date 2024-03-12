"""Unit tests for the authentication."""

import pytest
from fastapi.routing import APIRoute
from pytest_httpx import HTTPXMock
from rs_server_common.authentication import HEADER_NAME as APIKEY_HEADER
from rs_server_common.utils.logging import Logging
from starlette.status import HTTP_200_OK, HTTP_403_FORBIDDEN

from tests.conftest import RSPY_LOCAL_MODE, Envs

# Dummy url for the uac manager check endpoint
RSPY_UAC_CHECK_URL = "http://www.rspy-uac-manager.com"

# Dummy api key values
VALID_APIKEY = "VALID_API_KEY"
WRONG_APIKEY = "WRONG_APIKEY"

logger = Logging.default(__name__)


@pytest.mark.parametrize("fastapi_app", [Envs({RSPY_LOCAL_MODE: False})], ids=["authentication"], indirect=True)
async def test_authentication(fastapi_app, client, monkeypatch, httpx_mock: HTTPXMock):
    """
    Test that the http endpoints are protected and return 403 if not authenticated.
    Set RSPY_LOCAL_MODE to False before running the fastapi app.
    """

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    # With a valid api key in headers, the uac manager will give access to the endpoint
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": {}, "config": {}},
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
            logger.debug(f"Test the {route.path!r} [{method}] authentication")

            # Check that without api key in headers, the endpoint is protected and we receive a 403
            assert client.request(method, route.path).status_code == HTTP_403_FORBIDDEN

            # Test a valid and wrong api key values in headers
            assert (
                client.request(method, route.path, headers={APIKEY_HEADER: VALID_APIKEY}).status_code
                != HTTP_403_FORBIDDEN
            )
            assert (
                client.request(method, route.path, headers={APIKEY_HEADER: WRONG_APIKEY}).status_code
                == HTTP_403_FORBIDDEN
            )
