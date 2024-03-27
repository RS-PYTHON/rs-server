"""Unit tests for the authentication."""

import urllib

import pytest
from fastapi.routing import APIRoute
from pytest_httpx import HTTPXMock
from rs_server_common.authentication import APIKEY_HEADER, STATIONS_AUTH_LUT, ttl_cache
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

    ttl_cache.clear()
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


@pytest.mark.parametrize(
    "fastapi_app",
    [Envs({RSPY_LOCAL_MODE: False})],
    ids=["authorization_adgs"],
    indirect=["fastapi_app"],
)
def test_apikey_validator_adgs(fastapi_app, client, monkeypatch, httpx_mock: HTTPXMock):
    """
    Test that the http endpoints for the adgs station are protected and return 401 if not authorized.
    Set RSPY_LOCAL_MODE to False before running the fastapi app.
    """

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    read_type = "read"
    download_type = "download"
    read_request_params = {"datetime": "2014-01-01T12:00:00Z/2023-02-02T23:59:59Z"}
    download_request_params = {"name": "TEST_FILE.raw"}
    endpoints = []
    # Gather the endpoints
    # For each api endpoint (except the technical endpoints)
    for route in fastapi_app.router.routes:
        if (not isinstance(route, APIRoute)) or (route.path in ("/", "/health")) or "adgs" not in route.path:
            continue

        # For each method (get, post, ...)
        for method in route.methods:
            logger.debug(f"\n\nTest the {route.path} [{method}] authentication")

            if "search" in route.path:
                endpoints.append((read_type, route.path + "?" + urllib.parse.urlencode(read_request_params), method))
                # this means the authorization shall pass
            else:
                endpoints.append(
                    (download_type, route.path + "?" + urllib.parse.urlencode(download_request_params), method),
                )

    # With a valid api key in headers, set the read role
    # Clear the cache
    ttl_cache.clear()
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": ["rs_adgs_read"], "config": {}},
    )

    for endpoint in endpoints:
        if endpoint[0] == download_type:
            expected_response = [HTTP_401_UNAUTHORIZED]
        else:
            # this means the authorization shall pass
            expected_response = [HTTP_503_SERVICE_UNAVAILABLE, HTTP_404_NOT_FOUND]
        assert (
            client.request(endpoint[2], endpoint[1], headers={APIKEY_HEADER: VALID_APIKEY}).status_code
            in expected_response
        )

    # With a valid api key in headers, set the download role
    # Clear the cache
    ttl_cache.clear()
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": ["rs_adgs_download"], "config": {}},
    )

    for endpoint in endpoints:
        if endpoint[0] == read_type:
            expected_response = [HTTP_401_UNAUTHORIZED]
        else:
            # this means the authorization shall pass
            expected_response = [HTTP_503_SERVICE_UNAVAILABLE, HTTP_404_NOT_FOUND]

        assert (
            client.request(endpoint[2], endpoint[1], headers={APIKEY_HEADER: VALID_APIKEY}).status_code
            in expected_response
        )

    # With a valid api key in headers, set both of the download and read roles
    # Clear the cache
    ttl_cache.clear()
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": ["rs_adgs_download", "rs_adgs_read"], "config": {}},
    )

    for endpoint in endpoints:
        # this means the authorization shall pass
        assert client.request(endpoint[2], endpoint[1], headers={APIKEY_HEADER: VALID_APIKEY}).status_code in [
            HTTP_503_SERVICE_UNAVAILABLE,
            HTTP_404_NOT_FOUND,
        ]


adgs_station_identifiers = ["adgs"]
cadip_station_identifiers = ["ins", "mps", "mti", "nsg", "sgs", "cadip"]


@pytest.mark.parametrize(
    "fastapi_app",
    [Envs({RSPY_LOCAL_MODE: False})],
    ids=["authorization_adgs"],
    indirect=["fastapi_app"],
)
def test_apikey_validator_cadip(
    fastapi_app,
    client,
    monkeypatch,
    httpx_mock: HTTPXMock,
):  # pylint: disable=too-many-locals
    """
    Test that the http endpoints for the adgs station are protected and return 401 if not authorized.
    Set RSPY_LOCAL_MODE to False before running the fastapi app.
    """

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    read_type = "read"
    download_type = "download"
    read_request_params = {"datetime": "2014-01-01T12:00:00Z/2023-02-02T23:59:59Z"}
    download_request_params = {"name": "TEST_FILE.raw"}
    set_access_type_read = []
    set_access_type_download = []
    for identifier in cadip_station_identifiers:
        set_access_type_read.append(f"rs_{STATIONS_AUTH_LUT[identifier]}_read")
        set_access_type_download.append(f"rs_{STATIONS_AUTH_LUT[identifier]}_download")
    endpoints = []
    # Gather the endpoints
    # For each api endpoint (except the technical endpoints)
    for route in fastapi_app.router.routes:
        if (not isinstance(route, APIRoute)) or (route.path in ("/", "/health")) or "cadip" not in route.path:
            continue

        # For each method (get, post, ...)
        for method in route.methods:
            logger.debug(f"\n\nTest the {route.path} [{method}] authentication")
            for identifier in cadip_station_identifiers:
                if "search" in route.path:
                    endpoints.append(
                        (
                            read_type,
                            route.path.replace("{station}", identifier.upper())
                            + "?"
                            + urllib.parse.urlencode(read_request_params),
                            method,
                        ),
                    )
                else:
                    endpoints.append(
                        (
                            download_type,
                            route.path.replace("{station}", identifier.upper())
                            + "?"
                            + urllib.parse.urlencode(download_request_params),
                            method,
                        ),
                    )

    # With a valid api key in headers, set the read role
    # Clear the cache
    ttl_cache.clear()
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": set_access_type_read, "config": {}},
    )

    for endpoint in endpoints:
        # this means the authorization shall pass
        expected_response = [HTTP_503_SERVICE_UNAVAILABLE, HTTP_404_NOT_FOUND]
        if endpoint[0] == download_type:
            expected_response = [HTTP_401_UNAUTHORIZED]

        assert (
            client.request(endpoint[2], endpoint[1], headers={APIKEY_HEADER: VALID_APIKEY}).status_code
            in expected_response
        )

    # With a valid api key in headers, set the download role
    # Clear the cache
    ttl_cache.clear()
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": set_access_type_download, "config": {}},
    )

    for endpoint in endpoints:
        # this means the authorization shall pass
        expected_response = [HTTP_503_SERVICE_UNAVAILABLE, HTTP_404_NOT_FOUND]
        if endpoint[0] == read_type:
            expected_response = [HTTP_401_UNAUTHORIZED]
        assert (
            client.request(endpoint[2], endpoint[1], headers={APIKEY_HEADER: VALID_APIKEY}).status_code
            in expected_response
        )

    # With a valid api key in headers, set both of the download and read roles
    # Clear the cache
    ttl_cache.clear()
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": set_access_type_download + set_access_type_read, "config": {}},
    )

    for endpoint in endpoints:
        # this means the authorization shall pass
        assert client.request(endpoint[2], endpoint[1], headers={APIKEY_HEADER: VALID_APIKEY}).status_code in [
            HTTP_503_SERVICE_UNAVAILABLE,
            HTTP_404_NOT_FOUND,
        ]


date = {"datetime": "2014-01-01T12:00:00Z/2023-02-02T23:59:59Z"}
name = {"name": "TEST_FILE.raw"}


@pytest.mark.unit
@pytest.mark.parametrize(
    "fastapi_app, allowed_access_type",
    [
        (
            (
                Envs({RSPY_LOCAL_MODE: False}),
                ["read"],
            )
        ),
        (
            (
                Envs({RSPY_LOCAL_MODE: False}),
                ["download"],
            )
        ),
        (
            (
                Envs({RSPY_LOCAL_MODE: False}),
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
def test_apikey_validator(  # pylint: disable=too-many-arguments
    fastapi_app,
    allowed_access_type,
    client,
    monkeypatch,
    httpx_mock: HTTPXMock,
):
    """
    Test that the http endpoints are protected and return 401 if not authorized.
    Set RSPY_LOCAL_MODE to False before running the fastapi app.
    """
    ttl_cache.clear()

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)
    set_access_type = ["s1_access"]

    for access_type in allowed_access_type:
        for station_name in adgs_station_identifiers + cadip_station_identifiers:
            set_access_type.append(f"rs_{STATIONS_AUTH_LUT[station_name]}_{access_type}")

    # With a valid api key in headers, set the roles
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={"iam_roles": set_access_type, "config": {}},
    )

    # For each api endpoint (except the technical endpoints)
    for route in fastapi_app.router.routes:
        if (not isinstance(route, APIRoute)) or (route.path in ("/", "/health")):
            continue

        # For each method (get, post, ...)
        for method in route.methods:
            route_path_splitted = route.path.split("/")
            if len(route_path_splitted) < 2:
                continue
            # Gather endpoints for all adgs and cadip stations
            endpoints = []
            if route_path_splitted[1] in (adgs_station_identifiers + cadip_station_identifiers):
                if "search" in route.path:
                    endpoint_type = "read"
                    request_params = {"datetime": "2014-01-01T12:00:00Z/2023-02-02T23:59:59Z"}
                else:
                    endpoint_type = "download"
                    request_params = {"name": "TEST_FILE.raw"}

                if route_path_splitted[1] == "cadip":
                    for cadip_station in cadip_station_identifiers:
                        endpoints.append(
                            route.path.replace("{station}", cadip_station.upper())
                            + "?"
                            + urllib.parse.urlencode(request_params),
                        )
                else:
                    endpoints = [route.path + "?" + urllib.parse.urlencode(request_params)]

                for endpoint in endpoints:
                    resp = client.request(method, endpoint, headers={APIKEY_HEADER: VALID_APIKEY})
                    if endpoint_type in allowed_access_type:
                        # this means the auth key passed
                        assert resp.status_code in [HTTP_503_SERVICE_UNAVAILABLE, HTTP_404_NOT_FOUND]
                    else:
                        assert resp.status_code == HTTP_401_UNAUTHORIZED
