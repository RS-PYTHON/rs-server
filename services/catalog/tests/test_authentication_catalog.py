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
from authlib.integrations.starlette_client.apps import StarletteOAuth2App
from fastapi.testclient import TestClient
from moto.server import ThreadedMotoServer
from pytest_httpx import HTTPXMock
from rs_server_catalog.main import app, must_be_authenticated
from rs_server_common.authentication.apikey import APIKEY_HEADER, ttl_cache
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.pytest_utils import mock_oauth2
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

from .conftest import (  # pylint: disable=no-name-in-module
    OIDC_ENDPOINT,
    OIDC_REALM,
    RESOURCES_FOLDER,
    RSPY_UAC_CHECK_URL,
    RSPY_UAC_HOMEPAGE,
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

AUTHENT_EXTENSION = "https://stac-extensions.github.io/authentication/v1.1.0/schema.json"
AUTHENT_SCHEME = {
    "auth:schemes": {
        "apikey": {
            "type": "apiKey",
            "description": f"API key generated using {RSPY_UAC_HOMEPAGE}"
            "#/Manage%20API%20keys/get_new_api_key_auth_api_key_new_get",
            "name": "x-api-key",
            "in": "header",
        },
        "openid": {
            "type": "openIdConnect",
            "description": "OpenID Connect",
            "openIdConnectUrl": f"{OIDC_ENDPOINT}/realms/{OIDC_REALM}/.well-known/openid-configuration",
        },
        "oauth2": {
            "type": "oauth2",
            "description": "OAuth2+PKCE Authorization Code Flow",
            "flows": {
                "authorizationCode": {
                    "authorizationUrl": OAUTH2_AUTHORIZATION_ENDPOINT,
                    "tokenUrl": OAUTH2_TOKEN_ENDPOINT,
                    "scopes": {},
                },
            },
        },
    },
}
AUTHENT_REF = {
    "auth:refs": ["apikey", "openid", "oauth2"],
}
COMMON_FIELDS = {
    "extent": {
        "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
        "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
    },
    "license": "public-domain",
    "description": "Some description",
    "stac_version": "1.0.0",
    "stac_extensions": [AUTHENT_EXTENSION],
    **AUTHENT_SCHEME,
}

# pylint: disable=too-many-lines, too-many-arguments


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

    # Mock the OAuth2 server responses that are used for the STAC extensions (not for the authentication)
    mocker.patch.object(
        StarletteOAuth2App,
        "load_server_metadata",
        return_value={"authorization_endpoint": OAUTH2_AUTHORIZATION_ENDPOINT, "token_endpoint": OAUTH2_TOKEN_ENDPOINT},
    )


@pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
async def test_authentication_and_contents(mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
    """
    Test that the http endpoints are protected and return 401 or 403 if not authenticated,
    and test the response contents.
    """
    iam_roles = [
        "rs_catalog_toto:*_read",
        "rs_catalog_titi:S2_L1_read",
        "rs_catalog_darius:*_write",
    ]
    await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles, True)
    header = VALID_APIKEY_HEADER if test_apikey else {}

    valid_links = [
        {
            "rel": "self",
            "type": "application/json",
            "href": "http://testserver/catalog/",
            **AUTHENT_REF,
        },
        {
            "rel": "root",
            "type": "application/json",
            "href": "http://testserver/catalog/",
            **AUTHENT_REF,
        },
        {
            "rel": "data",
            "type": "application/json",
            "href": "http://testserver/catalog/collections",
            **AUTHENT_REF,
        },
        {
            "rel": "conformance",
            "type": "application/json",
            "title": "STAC/OGC conformance classes implemented by this server",
            "href": "http://testserver/catalog/conformance",
            **AUTHENT_REF,
        },
        {
            "rel": "search",
            "type": "application/geo+json",
            "title": "STAC search",
            "href": "http://testserver/catalog/search",
            "method": "GET",
            **AUTHENT_REF,
        },
        {
            "rel": "search",
            "type": "application/geo+json",
            "title": "STAC search",
            "href": "http://testserver/catalog/search",
            "method": "POST",
            **AUTHENT_REF,
        },
        {
            "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
            "type": "application/schema+json",
            "title": "Queryables",
            "href": "http://testserver/catalog/queryables",
            "method": "GET",
            **AUTHENT_REF,
        },
        {
            "rel": "child",
            "type": "application/json",
            "title": "toto_S1_L1",
            "href": "http://testserver/catalog/collections/toto:S1_L1",
            **AUTHENT_REF,
        },
        {
            "rel": "child",
            "type": "application/json",
            "title": "toto_S2_L3",
            "href": "http://testserver/catalog/collections/toto:S2_L3",
            **AUTHENT_REF,
        },
        {
            "rel": "child",
            "type": "application/json",
            "title": "titi_S2_L1",
            "href": "http://testserver/catalog/collections/titi:S2_L1",
            **AUTHENT_REF,
        },
        {
            "rel": "child",
            "type": "application/json",
            "title": "pyteam_S1_L1",
            "href": "http://testserver/catalog/collections/pyteam:S1_L1",
            **AUTHENT_REF,
        },
        {
            "rel": "service-desc",
            "type": "application/vnd.oai.openapi+json;version=3.0",
            "title": "OpenAPI service description",
            "href": "http://testserver/catalog/api",
            **AUTHENT_REF,
        },
        {
            "rel": "service-doc",
            "type": "text/html",
            "title": "OpenAPI service documentation",
            "href": "http://testserver/catalog/api.html",
            **AUTHENT_REF,
        },
    ]
    landing_page_response = client.request("GET", "/catalog/", **header)
    assert landing_page_response.status_code == HTTP_200_OK
    content = json.loads(landing_page_response.content)
    assert content["links"] == valid_links

    pyteam_collection = {
        "id": "S2_L1",
        "type": "Collection",
        "links": [
            {
                "rel": "items",
                "type": "application/geo+json",
                "href": "http://testserver/collections/S2_L1/items",
            },
            {
                "rel": "parent",
                "type": "application/json",
                "href": "http://testserver/",
            },
            {
                "rel": "root",
                "type": "application/json",
                "href": "http://testserver/",
            },
            {
                "rel": "self",
                "type": "application/json",
                "href": "http://testserver/collections/S2_L1",
            },
            {
                "rel": "items",
                "href": "http://localhost:8082/collections/S2_L1/items",
                "type": "application/geo+json",
            },
            {
                "rel": "license",
                "href": "https://creativecommons.org/licenses/publicdomain/",
                "title": "public domain",
            },
        ],
        "owner": "pyteam",
        **COMMON_FIELDS,
    }
    post_response = client.post("/catalog/collections", json=pyteam_collection, **header)
    assert post_response.status_code == HTTP_201_CREATED
    valid_collections = [
        {
            "id": "toto_S1_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/catalog/collections/toto:S1_L1/items",
                    **AUTHENT_REF,
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/catalog/collections/toto:S1_L1",
                    **AUTHENT_REF,
                },
                {
                    "rel": "items",
                    "href": "http://localhost:8082/catalog/collections/toto:S1_L1/items/",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "rel": "license",
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "title": "public domain",
                    **AUTHENT_REF,
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
                    "type": "application/schema+json",
                    "title": "Queryables",
                    "href": "http://testserver/catalog/collections/toto:S1_L1/queryables",
                    **AUTHENT_REF,
                },
            ],
            "owner": "toto",
            **COMMON_FIELDS,
        },
        {
            "id": "toto_S2_L3",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/catalog/collections/toto:S2_L3/items",
                    **AUTHENT_REF,
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/catalog/collections/toto:S2_L3",
                    **AUTHENT_REF,
                },
                {
                    "rel": "items",
                    "href": "http://localhost:8082/catalog/collections/toto:S2_L3/items/",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "rel": "license",
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "title": "public domain",
                    **AUTHENT_REF,
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
                    "type": "application/schema+json",
                    "title": "Queryables",
                    "href": "http://testserver/catalog/collections/toto:S2_L3/queryables",
                    **AUTHENT_REF,
                },
            ],
            "owner": "toto",
            **COMMON_FIELDS,
        },
        {
            "id": "titi_S2_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/catalog/collections/titi:S2_L1/items",
                    **AUTHENT_REF,
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/catalog/collections/titi:S2_L1",
                    **AUTHENT_REF,
                },
                {
                    "rel": "items",
                    "href": "http://localhost:8082/catalog/collections/titi:S2_L1/items/",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "rel": "license",
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "title": "public domain",
                    **AUTHENT_REF,
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
                    "type": "application/schema+json",
                    "title": "Queryables",
                    "href": "http://testserver/catalog/collections/titi:S2_L1/queryables",
                    **AUTHENT_REF,
                },
            ],
            "owner": "titi",
            **COMMON_FIELDS,
        },
        {
            "id": "pyteam_S1_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/catalog/collections/pyteam:S1_L1/items",
                    **AUTHENT_REF,
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/catalog/collections/pyteam:S1_L1",
                    **AUTHENT_REF,
                },
                {
                    "rel": "items",
                    "href": "http://localhost:8082/catalog/collections/pyteam:S1_L1/items/",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "rel": "license",
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "title": "public domain",
                    **AUTHENT_REF,
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
                    "type": "application/schema+json",
                    "title": "Queryables",
                    "href": "http://testserver/catalog/collections/pyteam:S1_L1/queryables",
                    **AUTHENT_REF,
                },
            ],
            "owner": "pyteam",
            **COMMON_FIELDS,
        },
        {
            "id": "pyteam_S2_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/catalog/collections/pyteam:S2_L1/items",
                    **AUTHENT_REF,
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/catalog/collections/pyteam:S2_L1",
                    **AUTHENT_REF,
                },
                {
                    "rel": "items",
                    "href": "http://testserver/catalog/collections/pyteam:S2_L1/items/",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "rel": "items",
                    "href": "http://localhost:8082/catalog/collections/pyteam:S2_L1/items/",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "rel": "license",
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "title": "public domain",
                    **AUTHENT_REF,
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
                    "type": "application/schema+json",
                    "title": "Queryables",
                    "href": "http://testserver/catalog/collections/pyteam:S2_L1/queryables",
                    **AUTHENT_REF,
                },
            ],
            "owner": "pyteam",
            **COMMON_FIELDS,
        },
    ]
    all_collections = client.request("GET", "/catalog/collections", **header)

    assert all_collections.status_code == HTTP_200_OK
    content = json.loads(all_collections.content)
    assert content["collections"] == valid_collections

    # Test a wrong apikey
    if test_apikey:
        wrong_api_key_response = client.request("GET", "/catalog/", **WRONG_APIKEY_HEADER)
        assert wrong_api_key_response.status_code == HTTP_403_FORBIDDEN

    # Delete the created collections so we're back to the initial test state
    assert client.delete("/catalog/collections/pyteam:S2_L1", **header).is_success


class TestAuthenticationGetOneCollection:
    """Contains authentication tests when the user wants to get a single collection."""

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    @pytest.mark.parametrize(
        ("user", "user_str_for_endpoint_call"),
        [
            ("toto", "toto:"),
            ("pyteam", ""),
        ],
    )
    async def test_http200_with_good_authentication(
        self,
        user,
        user_str_for_endpoint_call,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):  # pylint: disable=too-many-arguments
        """Test that the user gets the right collection when he does a good request with right permissions."""
        iam_roles = [f"rs_catalog_{user}:*_read"]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        collection = {
            "id": "S1_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": f"http://testserver/catalog/collections/{user}:S1_L1/items",
                    **AUTHENT_REF,
                },
                {
                    "rel": "parent",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/",
                    **AUTHENT_REF,
                },
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": f"http://testserver/catalog/collections/{user}:S1_L1",
                    **AUTHENT_REF,
                },
                {
                    "rel": "items",
                    "href": f"http://localhost:8082/catalog/collections/{user}:S1_L1/items/",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "rel": "license",
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "title": "public domain",
                    **AUTHENT_REF,
                },
                {
                    "rel": "http://www.opengis.net/def/rel/ogc/1.0/queryables",
                    "type": "application/schema+json",
                    "title": "Queryables",
                    "href": f"http://testserver/catalog/collections/{user}:S1_L1/queryables",
                    **AUTHENT_REF,
                },
            ],
            "owner": user,
            **COMMON_FIELDS,
        }
        response = client.request(
            "GET",
            f"/catalog/collections/{user_str_for_endpoint_call}S1_L1",
            **header,
        )
        assert response.status_code == HTTP_200_OK
        assert collection == json.loads(response.content)

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right authorisations."""

        iam_roles = [
            "rs_catalog_toto:*_write",
            "rs_catalog_toto:S1_L2_read",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1",
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationGetItems:
    """Contains authentication tests when the user wants to get items."""

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    @pytest.mark.parametrize(
        ("user", "user_str_for_endpoint_call"),
        [
            ("toto", "toto:"),
            ("pyteam", ""),
        ],
    )
    async def test_http200_with_good_authentication(
        self,
        user,
        user_str_for_endpoint_call,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):  # pylint: disable=too-many-arguments
        """Test that the user gets a HTTP_200_OK status code response
        when he does a good request with right permissions."""

        iam_roles = [f"rs_catalog_{user}:*_read"]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "GET",
            f"/catalog/collections/{user_str_for_endpoint_call}S1_L1/items/",
            **header,
        )
        assert response.status_code == HTTP_200_OK

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user get a HTTP_401_UNAUTHORIZED status code response
        when he does a good requests without the right authorisations.
        """

        iam_roles = [
            "rs_catalog_toto:*_write",
            "rs_catalog_toto:S1_L2_read",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/items/",
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationGetOneItem:
    """Contains authentication tests when the user wants to one item."""

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    @pytest.mark.parametrize(
        ("user", "user_str_for_endpoint_call", "feature"),
        [
            ("toto", "toto:", "fe916452-ba6f-4631-9154-c249924a122d"),
            ("pyteam", "", "hi916451-ca6f-4631-9154-4249924a133d"),
        ],
    )
    async def test_http200_with_good_authentication(
        self,
        user,
        user_str_for_endpoint_call,
        feature,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):  # pylint: disable=too-many-arguments
        """Test that the user gets the right item when he does a good request with right permissions."""

        iam_roles = [
            "rs_catalog_pyteam:*_read",
            "rs_catalog_toto:*_read",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        feature_s1_l1_0 = {
            "id": feature,
            "bbox": [-94.6334839, 37.0332547, -94.6005249, 37.0595608],
            "type": "Feature",
            "assets": {
                "may24C355000e4102500n.tif": {
                    "href": f"""s3://temp-bucket/{user}_S1_L1/images/may24C355000e4102500n.tif""",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "title": "NOAA STORM COG",
                    **AUTHENT_REF,
                },
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-94.6334839, 37.0595608],
                        [-94.6334839, 37.0332547],
                        [-94.6005249, 37.0332547],
                        [-94.6005249, 37.0595608],
                        [-94.6334839, 37.0595608],
                    ],
                ],
            },
            "collection": "S1_L1",
            "properties": {
                "gsd": 0.5971642834779395,
                "owner": user,
                "width": 2500,
                "height": 2500,
                "datetime": "2000-02-02T00:00:00Z",
                "owner_id": user,
                "proj:epsg": 3857,
                "orientation": "nadir",
                **AUTHENT_SCHEME,
            },
            "stac_version": "1.0.0",
            "stac_extensions": [
                "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
                "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
                AUTHENT_EXTENSION,
            ],
        }

        response = client.request(
            "GET",
            f"/catalog/collections/{user_str_for_endpoint_call}S1_L1/items/{feature}",
            **header,
        )
        assert response.status_code == HTTP_200_OK
        feature_id = json.loads(response.content)["id"]
        assert feature_id == feature_s1_l1_0["id"]

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions.
        """

        iam_roles = [
            "rs_catalog_toto:*_write",
            "rs_catalog_toto:S1_L2_read",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationPostOneCollection:
    """Contains authentication tests when a user wants to post one collection."""

    collection_to_post = {
        "id": "MY_SPECIAL_COLLECTION",
        "type": "Collection",
        "owner": "pyteam",
        "links": [
            {
                "rel": "items",
                "type": "application/geo+json",
                "href": "http://localhost:8082/collections/toto/items",
            },
            {"rel": "parent", "type": "application/json", "href": "http://localhost:8082/"},
            {"rel": "root", "type": "application/json", "href": "http://localhost:8082/"},
            {
                "rel": "self",
                "type": "application/json",
                "href": """http://localhost:8082/collections/toto""",
            },
            {
                "rel": "license",
                "href": "https://creativecommons.org/licenses/publicdomain/",
                "title": "public domain",
            },
        ],
        **COMMON_FIELDS,
    }

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_http201_with_good_authentication(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does a good request with right permissions."""

        iam_roles = [
            "rs_catalog_pyteam:*_read",
            "rs_catalog_pyteam:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "POST",
            "/catalog/collections",
            json=self.collection_to_post,
            **header,
        )
        assert response.status_code == HTTP_201_CREATED

        # Delete the created collections so we're back to the initial test state
        assert client.delete(
            f"/catalog/collections/{self.collection_to_post['owner']}:{self.collection_to_post['id']}",
            **header,
        ).is_success

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions."""

        iam_roles = ["rs_catalog_toto:S1_L2_read"]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}
        self.collection_to_post["owner"] = "toto"
        response = client.request(
            "POST",
            "/catalog/collections",
            json=self.collection_to_post,
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_user_creates_collection_owned_by_another_user(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):
        """Test to verify that creating a collection owned by another user returns HTTP 401 Unauthorized.

        This test checks the scenario where the user 'pyteam' attempts to create a collection that
        is owned by the user 'toto'. It ensures that the appropriate HTTP 401 Unauthorized status
        code is returned. The rs-server-catalog receives the apikey from the HEADER parameter,
        which is created for the user 'pyteam'. It then tries to create a collection with the
        info received in the body, but it sees that the owner is the 'toto' user, which doesn't
        correspond with the apikey owner

        Args:
            self: The test case instance.
            mocker: pytest-mock fixture for mocking objects.
            httpx_mock (HTTPXMock): Fixture for mocking HTTPX requests.
            client: Test client for making HTTP requests to the application.

        Returns:
            None

        Raises:
            AssertionError: If the response status code is not HTTP 401 Unauthorized.

        Notes:
        - The `iam_roles` variable simulates the roles assigned to the user 'pyteam'.
        - The `init_test` function is called to set up the test environment with mocked roles and configurations.
        - The `self.collection_to_post` dictionary is modified to set the 'owner' field to 'toto'.
        - The `client.request` method sends a POST request to create a collection.
        - The test asserts that the response status code is HTTP 401 Unauthorized.
        """

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}
        self.collection_to_post["owner"] = "toto"
        response = client.request(
            "POST",
            "/catalog/collections",
            json=self.collection_to_post,
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationPutOneCollection:
    """Contains authentication tests when a user wants to update one collection."""

    updated_collection = {
        "id": "S1_L1",
        "type": "Collection",
        "links": [
            {
                "rel": "items",
                "type": "application/geo+json",
                "href": "http://testserver/collections/pyteam_S1_L1/items",
            },
            {"rel": "parent", "type": "application/json", "href": "http://testserver/"},
            {"rel": "root", "type": "application/json", "href": "http://testserver/"},
            {"rel": "self", "type": "application/json", "href": "http://testserver/collections/pyteam_S1_L1"},
            {
                "rel": "items",
                "href": "http://localhost:8082/collections/S1_L1/items",
                "type": "application/geo+json",
            },
            {
                "rel": "license",
                "href": "https://creativecommons.org/licenses/publicdomain/",
                "title": "public domain",
            },
        ],
        "owner": "pyteam",
        **COMMON_FIELDS,
    }

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_http200_with_good_authentication(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does good requests (one with the owner_id parameter and the other one
        without the owner_id parameter) with right permissions."""

        iam_roles = [
            "rs_catalog_pyteam:*_read",
            "rs_catalog_pyteam:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        # owner_id is used in the endpoint, format is owner_id:collection
        response = client.request(
            "PUT",
            "/catalog/collections/pyteam:S1_L1",
            json=self.updated_collection,
            **header,
        )
        assert response.status_code == HTTP_200_OK
        # request the endpoint by using just "collection" (the owner_id is
        # loaded by the rs-server-catalog directly from the apikey)
        response = client.request(
            "PUT",
            "/catalog/collections/S1_L1",
            json=self.updated_collection,
            **header,
        )
        assert response.status_code == HTTP_200_OK

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions."""

        iam_roles = ["rs_catalog_pyteam:S1_L2_read"]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "PUT",
            "/catalog/collections/toto:S1_L1",
            json=self.updated_collection,
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_user_updates_collection_owned_by_another_user(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):
        """This test evaluates the scenario where the user 'pyteam' attempts to update his
        own collection by altering the owner field to another user, 'toto'. The primary objective
        is to ensure that an appropriate HTTP 401 Unauthorized status code is returned. The rs-server-catalog
        retrieves the apikey from the HEADER parameter, which is associated with the user 'pyteam'. When
        attempting to update the collection with the information provided in the body, the
        system detects that the owner is specified as 'toto'. Since 'toto' does not match the owner of the apikey,
        the update is correctly rejected, resulting in the expected unauthorized status.

        Args:
            self: The test case instance.
            mocker: pytest-mock fixture for mocking objects.
            httpx_mock (HTTPXMock): Fixture for mocking HTTPX requests.
            client: Test client for making HTTP requests to the application.

        Returns:
            None

        Raises:
            AssertionError: If the response status code is not HTTP 401 Unauthorized.

        Notes:
        - The `iam_roles` variable simulates the roles assigned to the user 'pyteam'.
        - The `init_test` function is called to set up the test environment with mocked roles and configurations.
        - The `self.collection_to_post` dictionary is modified to set the 'owner' field to 'toto'.
        - The `client.request` method sends a PUT request to update a collection.
        - The test asserts that the response status code is HTTP 401 Unauthorized.
        """

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}
        self.updated_collection["owner"] = "toto"
        response = client.request(
            "PUT",
            "/catalog/collections/toto:S1_L1",
            json=self.updated_collection,
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationSearch:
    """Contains authentication tests when a user wants to do a search request."""

    search_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500 AND owner='toto'"}
    test_json = {
        "collections": ["S1_L1"],
        "filter-lang": "cql2-json",
        "filter": {
            "op": "and",
            "args": [
                {"op": "=", "args": [{"property": "owner"}, "toto"]},
                {"op": "=", "args": [{"property": "width"}, 2500]},
            ],
        },
    }

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_http200_with_good_authentication(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does good requests (GET and POST method) with right permissions."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "GET",
            "/catalog/search",
            params=self.search_params,
            **header,
        )
        assert response.status_code == HTTP_200_OK
        response = client.request("POST", "/catalog/search", json=self.test_json, **header)
        assert response.status_code == HTTP_200_OK

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions."""

        iam_roles = ["rs_catalog_toto:S1_L2_read"]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "GET",
            "/catalog/search",
            params=self.search_params,
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED
        response = client.request("POST", "/catalog/search", json=self.test_json, **header)
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationSearchInCollection:
    """Contains authentication tests when a user wants to do a search request inside a specific collection."""

    search_params_ids = {"ids": "fe916452-ba6f-4631-9154-c249924a122d"}
    search_params_filter = {"filter-lang": "cql2-text", "filter": "width=2500"}
    test_json = {
        "filter-lang": "cql2-json",
        "filter": {
            "op": "and",
            "args": [
                {"op": "=", "args": [{"property": "height"}, 2500]},
                {"op": "=", "args": [{"property": "width"}, 2500]},
            ],
        },
    }

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_http200_with_good_authentication(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does good requests (GET and POST method) with right permissions.
        Also test that the user gets the right number of items matching the search request parameters."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/search",
            params=self.search_params_ids,
            **header,
        )
        assert response.status_code == HTTP_200_OK
        content = json.loads(response.content)
        assert content["context"] == {"limit": 10, "returned": 1}

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/search",
            params=self.search_params_filter,
            **header,
        )
        assert response.status_code == HTTP_200_OK
        content = json.loads(response.content)
        assert content["context"] == {"limit": 10, "returned": 2}

        response = client.request(
            "POST",
            "/catalog/collections/toto:S1_L1/search",
            json=self.test_json,
            **header,
        )
        assert response.status_code == HTTP_200_OK
        content = json.loads(response.content)
        assert content["context"] == {"limit": 10, "returned": 2}

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions."""

        iam_roles = ["rs_catalog_toto:S1_L2_read"]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/search",
            params=self.search_params_filter,
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED
        response = client.request(
            "POST",
            "/catalog/collections/toto:S1_L1/search",
            json=self.test_json,
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationDownload:
    """Contains authentication tests when a user wants to do a download."""

    def export_aws_credentials(self):
        """Export AWS credentials as environment variables for testing purposes.

        This function sets the following environment variables with dummy values for AWS credentials:
        - AWS_ACCESS_KEY_ID
        - AWS_SECRET_ACCESS_KEY
        - AWS_SECURITY_TOKEN
        - AWS_SESSION_TOKEN
        - AWS_DEFAULT_REGION

        Note: This function is intended for testing purposes only, and it should not be used in production.

        Returns:
            None

        Raises:
            None
        """
        with open(RESOURCES_FOLDER / "s3" / "s3.yml", "r", encoding="utf-8") as f:
            s3_config = yaml.safe_load(f)
            os.environ.update(s3_config["s3"])
            os.environ.update(s3_config["boto"])

    def clear_aws_credentials(self):
        """Clear AWS credentials from environment variables."""
        with open(RESOURCES_FOLDER / "s3" / "s3.yml", "r", encoding="utf-8") as f:
            s3_config = yaml.safe_load(f)
            for env_var in list(s3_config["s3"].keys()) + list(s3_config["boto"].keys()):
                del os.environ[env_var]

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_http200_with_good_authentication(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):  # pylint: disable=too-many-locals
        """Test used to verify the generation of a presigned url for a download."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
            "rs_catalog_toto:*_download",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        # Start moto server
        moto_endpoint = "http://localhost:8077"
        self.export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )
        server = ThreadedMotoServer(port=8077)
        server.start()
        users_map = {"toto:": "fe916452-ba6f-4631-9154-c249924a122d", "": "hi916451-ca6f-4631-9154-4249924a133d"}
        try:
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            # Upload a file to catalog-bucket
            catalog_bucket = "catalog-bucket"
            s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)
            object_content = "testing\n"
            s3_handler.s3_client.put_object(
                Bucket=catalog_bucket,
                Key="S1_L1/images/may24C355000e4102500n.tif",
                Body=object_content,
            )
            user = ""

            for user, item_id in users_map.items():
                print(f"user = {user}, file = {item_id}")
                response = client.request(
                    "GET",
                    f"/catalog/collections/{user}S1_L1/items/{item_id}/download/may24C355000e4102500n.tif",
                    **header,
                )
                assert response.status_code == HTTP_302_FOUND

                # Check that response is empty
                assert response.content == b""

                # call the redirected url
                product_content = requests.get(response.headers["location"], timeout=10)

                assert product_content.status_code == HTTP_200_OK
                assert product_content.content.decode() == object_content
                # test with a non-existing asset id
                response = client.get(
                    f"/catalog/collections/{user}S1_L1/items/{item_id}/download/UNKNWON",
                    **header,
                )
                assert response.status_code == HTTP_404_NOT_FOUND

                assert (
                    client.get(
                        f"/catalog/collections/{user}S1_L1/items/INCORRECT_ITEM_ID/download/UNKNOWN",
                        **header,
                    ).status_code
                    == HTTP_404_NOT_FOUND
                )

        finally:
            server.stop()
            # Remove bucket credentials form env variables / should create a s3_handler without credentials error
            self.clear_aws_credentials()

        response = client.get(
            "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/"
            "may24C355000e4102500n.tif",
            **header,
        )
        assert response.status_code == HTTP_400_BAD_REQUEST
        assert response.content == b'"Could not find s3 credentials"'

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test used to verify the generation of a presigned url for a download."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        # Start moto server
        moto_endpoint = "http://localhost:8077"
        self.export_aws_credentials()
        secrets = {"s3endpoint": moto_endpoint, "accesskey": None, "secretkey": None, "region": ""}
        s3_handler = S3StorageHandler(
            secrets["accesskey"],
            secrets["secretkey"],
            secrets["s3endpoint"],
            secrets["region"],
        )
        server = ThreadedMotoServer(port=8077)
        server.start()

        try:
            requests.post(moto_endpoint + "/moto-api/reset", timeout=5)
            # Upload a file to catalog-bucket
            catalog_bucket = "catalog-bucket"
            s3_handler.s3_client.create_bucket(Bucket=catalog_bucket)
            object_content = "testing\n"
            s3_handler.s3_client.put_object(
                Bucket=catalog_bucket,
                Key="S1_L1/images/may24C355000e4102500n.tif",
                Body=object_content,
            )

            response = client.request(
                "GET",
                "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/"
                "may24C355000e4102500n.tif",
                **header,
            )
            assert response.status_code == HTTP_401_UNAUTHORIZED

        finally:
            server.stop()
            # Remove bucket credentials form env variables / should create a s3_handler without credentials error
            self.clear_aws_credentials()


class TestAuthenticationDelete:
    """Contains authentication tests when a user wants to delete a collection."""

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_http200_with_good_authentication(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he deletes a collection with right permissions"""

        iam_roles: list[str] = []
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        # create the collections first
        collections = ["pyteam_fixture_collection_1", "pyteam_fixture_collection_2"]
        for collection in collections:
            new_collection = {
                "id": f"{collection}",
                "type": "Collection",
                "description": "test_description",
                "stac_version": "1.0.0",
                "owner": "pyteam",
                "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
                "license": "public-domain",
                "extent": {
                    "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                    "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
                },
            }

            response = client.request(
                "POST",
                "/catalog/collections",
                json=new_collection,
                **header,
            )
            assert response.status_code == HTTP_201_CREATED

        # request the endpoint by using "user:collection"
        response = client.request(
            "DELETE",
            f"/catalog/collections/pyteam:{collections[0]}",
            **header,
        )
        assert response.status_code == HTTP_200_OK
        # request the endpoint by using just "collection" (the user is
        # loaded by the rs-server-catalog directly from the apikey)
        response = client.request(
            "DELETE",
            f"/catalog/collections/{collections[1]}",
            **header,
        )
        assert response.status_code == HTTP_200_OK

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he tries to delete a collection without right permissions."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        # sending a request from user pyteam (loaded from the apikey) to delete
        # the S1_L1 collection owned by the `toto` user.
        # 401 unauthorized reponse should be received
        response = client.request(
            "DELETE",
            "/catalog/collections/toto:S1_L1",
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationPostOneItem:  # pylint: disable=duplicate-code
    """Contains authentication tests when a user wants to post one item."""

    item_id = "S1SIWOCN_20220412T054447_0024_S139"
    feature_to_post = {
        "type": "Feature",
        "stac_version": "1.0.0",
        "stac_extensions": [
            "https://stac-extensions.github.io/eopf/v1.0.0/schema.json",
            "https://stac-extensions.github.io/eo/v1.1.0/schema.json",
            "https://stac-extensions.github.io/sat/v1.0.0/schema.json",
            "https://stac-extensions.github.io/view/v1.0.0/schema.json",
            "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
            "https://stac-extensions.github.io/processing/v1.1.0/schema.json",
        ],
        "id": item_id,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-94.6334839, 37.0595608],
                    [-94.6334839, 37.0332547],
                    [-94.6005249, 37.0332547],
                    [-94.6005249, 37.0595608],
                    [-94.6334839, 37.0595608],
                ],
            ],
        },
        "bbox": [-180.0, -90.0, 0.0, 180.0, 90.0, 10000.0],
        "properties": {
            "gsd": 0.5971642834779395,
            "width": 2500,
            "height": 2500,
            "datetime": "2000-02-02T00:00:00Z",
            "proj:epsg": 3857,
            "orientation": "nadir",
        },
        "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        "assets": {
            "S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
                "roles": ["data"],
            },
            "S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
                "roles": ["data"],
            },
            "S1SIWOCN_20220412T054447_0024_S139_T902.nc": {
                "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T902.nc",
                "roles": ["data"],
            },
        },
        "collection": "S1_L1",
    }

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_http201_with_good_authentication(
        self,
        mocker,
        httpx_mock: HTTPXMock,
        client,
        test_apikey,
        test_oauth2,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does a good request with right permissions."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.post(
            "/catalog/collections/S1_L1/items",
            content=json.dumps(self.feature_to_post),
            **header,
        )
        # check if the item was well added to the collection
        assert response.status_code == HTTP_201_CREATED
        # delete the item, don't change the collection, because it is used
        # by other tests also
        response = client.request(
            "DELETE",
            f"/catalog/collections/S1_L1/items/{self.item_id}",
            json=self.feature_to_post,
            **header,
        )
        # check if the item was deleted from the collection
        assert response.status_code == HTTP_200_OK

    @pytest.mark.parametrize("test_apikey, test_oauth2", [[True, False], [False, True]], ids=["apikey", "oauth2"])
    async def test_fails_without_good_perms(self, mocker, httpx_mock: HTTPXMock, client, test_apikey, test_oauth2):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without right permissions."""

        iam_roles = ["rs_catalog_toto:S1_L1_read"]
        await init_test(mocker, httpx_mock, client, test_apikey, test_oauth2, iam_roles)
        header = VALID_APIKEY_HEADER if test_apikey else {}

        response = client.request(
            "POST",
            "/catalog/collections/toto:S1_L1/items",
            json=self.feature_to_post,
            **header,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


@pytest.mark.httpx_mock(can_send_already_matched_responses=True)
@pytest.mark.parametrize("test_apikey", [True, False], ids=["test_apikey", "no_apikey"])
@pytest.mark.parametrize("test_oauth2", [True, False], ids=["test_oauth2", "no_oauth2"])
async def test_error_when_not_authenticated(mocker, client, httpx_mock: HTTPXMock, test_apikey, test_oauth2):
    """
    Test that all the http endpoints are protected and return 401 or 403 if not authenticated.
    """
    owner_id = "pyteam"
    await init_test(
        mocker,
        httpx_mock,
        client,
        test_apikey,
        test_oauth2,
        [],
        mock_wrong_apikey=True,
        user_login=owner_id,
    )
    header = VALID_APIKEY_HEADER if test_apikey else {}

    # For each route and method from the openapi specification i.e. with the /catalog/ prefixes
    for path, methods in app.openapi()["paths"].items():
        if not must_be_authenticated(path):
            continue
        for method in methods.keys():

            endpoint = path.format(collection_id="collection_id", item_id="item_id", owner_id=owner_id)
            logger.debug(f"Test the {endpoint!r} [{method}] authentication")

            # With a valid apikey or oauth2 authentication, we should have a status code != 401 or 403.
            # We have other errors on many endpoints because we didn't give the right arguments,
            # but it's OK it is not what we are testing here.
            if test_apikey or test_oauth2:
                response = client.request(method, endpoint, **header)
                logger.debug(response)
                assert response.status_code not in (
                    HTTP_401_UNAUTHORIZED,
                    HTTP_403_FORBIDDEN,
                    HTTP_422_UNPROCESSABLE_ENTITY,  # with 422, the authentication is not called and not tested
                )

                # With a wrong apikey, we should have a 403 error
                if test_apikey:
                    assert client.request(method, endpoint, **WRONG_APIKEY_HEADER).status_code == HTTP_403_FORBIDDEN

            # Check that without authentication, the endpoint is protected and we receive a 401
            else:
                assert client.request(method, endpoint).status_code == HTTP_401_UNAUTHORIZED


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
