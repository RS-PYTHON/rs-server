"""Unit tests for the authentication."""

import urllib

import pytest
import responses
from fastapi.routing import APIRoute
from pytest_httpx import HTTPXMock
from rs_server_common.authentication import APIKEY_HEADER, STATIONS_AUTH_lut
from rs_server_common.utils.logging import Logging
from starlette.status import (
    HTTP_200_OK,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from tests.conftest import RSPY_LOCAL_MODE, Envs  # pylint: disable=no-name-in-module

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
        # NOTE: we could use other roles and config, to be discussed
        json={"iam_roles": ["rs_adgs_read", "s1_access"], "config": {}},
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


cadip_stations = ["ins", "mps", "mti", "nsg", "sgs", "cadip"]


@pytest.mark.parametrize(
    "fastapi_app, stations, allowed_access_type",
    [
        (
            (
                Envs({RSPY_LOCAL_MODE: False}),
                ["adgs", "ins", "mps", "mti", "nsg", "sgs", "cadip"],
                ["read"],
            )
        ),
        (
            (
                Envs({RSPY_LOCAL_MODE: False}),
                ["adgs", "ins", "mps", "mti", "nsg", "sgs", "cadip"],
                ["download"],
            )
        ),
        (
            (
                Envs({RSPY_LOCAL_MODE: False}),
                ["adgs", "ins", "mps", "mti", "nsg", "sgs", "cadip"],
                ["read", "download"],
            )
        ),
    ],
    ids=[
        "authorization_adgs_read",
        "authorization_adgs_dwn",
        "authorization_adgs_both",
    ],
    indirect=["fastapi_app"],
)
# @responses.activate
async def test_apikey_validator(fastapi_app, stations, allowed_access_type, client, monkeypatch, httpx_mock: HTTPXMock):
    """
    Test that the http endpoints are protected and return 401 if not authorized.
    Set RSPY_LOCAL_MODE to False before running the fastapi app.
    """
    logger.debug("\n\n\n\n\nENTERING IN TEST")
    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)
    set_access_type = ["s1_access"]

    for access_type in allowed_access_type:
        for station_name in stations:
            set_access_type.append(f"rs_{STATIONS_AUTH_lut[station_name]}_{access_type}")
    logger.debug(f"set_access_type {set_access_type}")
    # With a valid api key in headers, set the roles for adgs read only
    httpx_mock.reset(True)
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        # NOTE: we could use other roles and config, to be discussed
        json={"iam_roles": set_access_type, "config": {}},
    )
    import pdb

    pdb.set_trace()

    # For each api endpoint (except the technical endpoints)
    for route in fastapi_app.router.routes:
        if (not isinstance(route, APIRoute)) or (route.path in ("/", "/health")):
            continue

        # For each method (get, post, ...)
        for method in route.methods:
            logger.debug(f"\n\nTest the {route.path} [{method}] authentication")
            route_path_splitted = route.path.split("/")
            if len(route_path_splitted) < 2:
                continue
            # import pdb
            # pdb.set_trace()
            if route_path_splitted[1] in stations:
                if "search" in route.path:
                    endpoint_type = "read"
                    request_params = {"datetime": "2014-01-01T12:00:00Z/2023-02-02T23:59:59Z"}
                else:
                    endpoint_type = "download"
                    request_params = {"name": "TEST_FILE.raw"}
                endpoints = []
                if route_path_splitted[1] == "cadip":
                    for cadip_station in cadip_stations:
                        endpoints.append(
                            route.path.replace("{station}", cadip_station.upper())
                            + "?"
                            + urllib.parse.urlencode(request_params),
                        )
                else:
                    endpoints = [route.path + "?" + urllib.parse.urlencode(request_params)]
                # endpoint = route.path + "?" + urllib.parse.urlencode(request_params)
                logger.debug(
                    f"endpoint_type = {endpoint_type} | allowed_access_type = {allowed_access_type} | endpoints  = {endpoints}",
                )
                for endpoint in endpoints:
                    logger.debug(f"endpoint = {endpoint}")
                    resp = client.request(method, endpoint, headers={APIKEY_HEADER: VALID_APIKEY})
                    if endpoint_type in allowed_access_type:
                        # this means the auth key passed
                        logger.debug("SHOULD BE OK !")
                        assert resp.status_code in [HTTP_503_SERVICE_UNAVAILABLE, HTTP_404_NOT_FOUND]
                    else:
                        logger.debug("SHOULD NOT PASS THE AUTH !")
                        assert resp.status_code == HTTP_401_UNAUTHORIZED
