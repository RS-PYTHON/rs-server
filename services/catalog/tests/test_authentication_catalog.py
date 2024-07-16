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
from moto.server import ThreadedMotoServer
from pytest_httpx import HTTPXMock
from rs_server_common.authentication import APIKEY_HEADER, ttl_cache
from rs_server_common.s3_storage_handler.s3_storage_handler import S3StorageHandler
from starlette.status import (
    HTTP_200_OK,
    HTTP_302_FOUND,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)

from .conftest import RESOURCES_FOLDER  # pylint: disable=no-name-in-module

# Dummy url for the uac manager check endpoint
RSPY_UAC_CHECK_URL = "http://www.rspy-uac-manager.com"

# Dummy api key values
VALID_APIKEY = "VALID_API_KEY"
WRONG_APIKEY = "WRONG_APIKEY"

# Pass the api key in HTTP header
HEADER = {"headers": {APIKEY_HEADER: VALID_APIKEY}}
WRONG_HEADER = {"headers": {APIKEY_HEADER: WRONG_APIKEY}}

AUTHENT_EXTENSION = "https://stac-extensions.github.io/authentication/v1.1.0/schema.json"
AUTHENT_SCHEME = {
    "auth:schemes": {
        "apikey": {
            "type": "apiKey",
            "description": "API key generated using http://test_apikey_manager/docs"
            "#/Manage%20API%20keys/get_new_api_key_auth_api_key_new_get",
            "name": "x-api-key",
            "in": "header",
        },
    },
}
AUTHENT_REF = {"auth:refs": ["apikey"]}
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

# pylint: disable=too-many-lines


def init_test(mocker, monkeypatch, httpx_mock: HTTPXMock, iam_roles: list[str], mock_wrong_apikey: bool = False):
    """init mocker for tests."""
    # Mock cluster mode to enable authentication. See: https://stackoverflow.com/a/69685866
    mocker.patch("rs_server_common.settings.CLUSTER_MODE", new=True, autospec=False)

    # Mock the uac manager url
    monkeypatch.setenv("RSPY_UAC_CHECK_URL", RSPY_UAC_CHECK_URL)

    # With a valid api key in headers, the uac manager will give access to the endpoint
    ttl_cache.clear()  # clear the cached response
    httpx_mock.add_response(
        url=RSPY_UAC_CHECK_URL,
        match_headers={APIKEY_HEADER: VALID_APIKEY},
        status_code=HTTP_200_OK,
        json={
            "name": "test_apikey",
            "user_login": "pyteam",
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


def test_authentication(mocker, monkeypatch, httpx_mock: HTTPXMock, client):
    """
    Test that the http endpoints are protected and return 403 if not authenticated.
    """

    iam_roles = [
        "rs_catalog_toto:*_read",
        "rs_catalog_titi:S2_L1_read",
        "rs_catalog_darius:*_write",
    ]
    init_test(mocker, monkeypatch, httpx_mock, iam_roles, True)

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
            "title": "STAC/WFS3 conformance classes implemented by this server",
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
        {
            "rel": "child",
            "type": "application/json",
            "href": "http://testserver/catalog/catalogs/toto",
            **AUTHENT_REF,
        },
    ]
    landing_page_response = client.request("GET", "/catalog/", **HEADER)
    assert landing_page_response.status_code == HTTP_200_OK
    content = json.loads(landing_page_response.content)
    assert content["links"] == valid_links

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
            "title": "STAC/WFS3 conformance classes implemented by this server",
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
            "title": "pyteam_S1_L1",
            "type": "application/json",
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

    catalog_owner_id_response = client.request("GET", "/catalog/catalogs/toto", headers={APIKEY_HEADER: VALID_APIKEY})
    content = json.loads(catalog_owner_id_response.content)
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
    post_response = client.post("/catalog/collections", json=pyteam_collection, **HEADER)
    assert post_response.status_code == HTTP_200_OK
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
                    "href": "http://testserver/catalog/catalogs/toto",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/catalogs/toto",
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
                    "href": "http://testserver/catalog/catalogs/toto",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/catalogs/toto",
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
                    "href": "http://testserver/catalog/catalogs/titi",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/catalogs/titi",
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
            ],
            "owner": "titi",
            **COMMON_FIELDS,
        },
        {
            "id": "pyteam_S1_L1",
            "type": "Collection",
            "links": [
                {
                    "href": "http://testserver/catalog/collections/pyteam:S1_L1/items",
                    "rel": "items",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "href": "http://testserver/catalog/catalogs/pyteam",
                    "rel": "parent",
                    "type": "application/json",
                    **AUTHENT_REF,
                },
                {
                    "href": "http://testserver/catalog/catalogs/pyteam",
                    "rel": "root",
                    "type": "application/json",
                    **AUTHENT_REF,
                },
                {
                    "href": "http://testserver/catalog/collections/pyteam:S1_L1",
                    "rel": "self",
                    "type": "application/json",
                    **AUTHENT_REF,
                },
                {
                    "href": "http://localhost:8082/catalog/collections/pyteam:S1_L1/items/",
                    "rel": "items",
                    "type": "application/geo+json",
                    **AUTHENT_REF,
                },
                {
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "rel": "license",
                    "title": "public domain",
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
                    "href": "http://testserver/catalog/catalogs/pyteam",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": "http://testserver/catalog/catalogs/pyteam",
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
            ],
            "owner": "pyteam",
            **COMMON_FIELDS,
        },
    ]
    all_collections = client.request("GET", "/catalog/collections", **HEADER)

    assert all_collections.status_code == HTTP_200_OK
    content = json.loads(all_collections.content)
    assert content["collections"] == valid_collections

    wrong_api_key_response = client.request("GET", "/catalog/", **WRONG_HEADER)
    assert wrong_api_key_response.status_code == HTTP_403_FORBIDDEN


class TestAuthenticationGetOneCollection:
    """Contains authentication tests when the user wants to get a single collection."""

    @pytest.mark.parametrize(
        ("user", "user_str_for_endpoint_call"),
        [
            ("toto", "toto:"),
            ("pyteam", ""),
        ],
    )
    def test_http200_with_good_authentication(
        self,
        user,
        user_str_for_endpoint_call,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=too-many-arguments
        """Test that the user gets the right collection when he does a good request with right permissions."""
        iam_roles = [f"rs_catalog_{user}:*_read"]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

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
                    "href": f"http://testserver/catalog/catalogs/{user}",
                    **AUTHENT_REF,
                },
                {
                    "rel": "root",
                    "type": "application/json",
                    "href": f"http://testserver/catalog/catalogs/{user}",
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
            ],
            "owner": user,
            **COMMON_FIELDS,
        }
        response = client.request(
            "GET",
            f"/catalog/collections/{user_str_for_endpoint_call}S1_L1",
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK
        assert collection == json.loads(response.content)

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right authorisations."""

        iam_roles = [
            "rs_catalog_toto:*_write",
            "rs_catalog_toto:S1_L2_read",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1",
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationGetItems:
    """Contains authentication tests when the user wants to get items."""

    @pytest.mark.parametrize(
        ("user", "user_str_for_endpoint_call"),
        [
            ("toto", "toto:"),
            ("pyteam", ""),
        ],
    )
    def test_http200_with_good_authentication(
        self,
        user,
        user_str_for_endpoint_call,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=too-many-arguments
        """Test that the user gets a HTTP_200_OK status code response
        when he does a good request with right permissions."""

        iam_roles = [f"rs_catalog_{user}:*_read"]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            f"/catalog/collections/{user_str_for_endpoint_call}S1_L1/items/",
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user get a HTTP_401_UNAUTHORIZED status code response
        when he does a good requests without the right authorisations.
        """

        iam_roles = [
            "rs_catalog_toto:*_write",
            "rs_catalog_toto:S1_L2_read",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/items/",
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationGetOneItem:
    """Contains authentication tests when the user wants to one item."""

    @pytest.mark.parametrize(
        ("user", "user_str_for_endpoint_call", "feature"),
        [
            ("toto", "toto:", "fe916452-ba6f-4631-9154-c249924a122d"),
            ("pyteam", "", "hi916451-ca6f-4631-9154-4249924a133d"),
        ],
    )
    def test_http200_with_good_authentication(
        self,
        user,
        user_str_for_endpoint_call,
        feature,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=too-many-arguments
        """Test that the user gets the right item when he does a good request with right permissions."""

        iam_roles = [
            "rs_catalog_pyteam:*_read",
            "rs_catalog_toto:*_read",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        feature_s1_l1_0 = {
            "id": feature,
            "bbox": [-94.6334839, 37.0332547, -94.6005249, 37.0595608],
            "type": "Feature",
            "assets": {
                "COG": {
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
            },
            "stac_version": "1.0.0",
            "stac_extensions": [
                "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
                "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
                AUTHENT_EXTENSION,
            ],
            **AUTHENT_SCHEME,
        }

        response = client.request(
            "GET",
            f"/catalog/collections/{user_str_for_endpoint_call}S1_L1/items/{feature}",
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK
        feature_id = json.loads(response.content)["id"]
        assert feature_id == feature_s1_l1_0["id"]

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions.
        """

        iam_roles = [
            "rs_catalog_toto:*_write",
            "rs_catalog_toto:S1_L2_read",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
            **HEADER,
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

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does a good request with right permissions."""

        iam_roles = [
            "rs_catalog_pyteam:*_read",
            "rs_catalog_pyteam:*_write",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "POST",
            "/catalog/collections",
            json=self.collection_to_post,
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions."""

        iam_roles = ["rs_catalog_toto:S1_L2_read"]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)
        self.collection_to_post["owner"] = "toto"
        response = client.request(
            "POST",
            "/catalog/collections",
            json=self.collection_to_post,
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED

    def test_fails_user_creates_collection_owned_by_another_user(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
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
            monkeypatch: pytest fixture for modifying module or environment attributes.
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
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)
        self.collection_to_post["owner"] = "toto"
        response = client.request(
            "POST",
            "/catalog/collections",
            json=self.collection_to_post,
            **HEADER,
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

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does good requests (one with the owner_id parameter and the other one
        without the owner_id parameter) with right permissions."""

        iam_roles = [
            "rs_catalog_pyteam:*_read",
            "rs_catalog_pyteam:*_write",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        # owner_id is used in the endpoint, format is owner_id:collection
        response = client.request(
            "PUT",
            "/catalog/collections/pyteam:S1_L1",
            json=self.updated_collection,
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK
        # request the endpoint by using just "collection" (the owner_id is
        # loaded by the rs-server-catalog directly from the apikey)
        response = client.request(
            "PUT",
            "/catalog/collections/S1_L1",
            json=self.updated_collection,
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions."""

        iam_roles = ["rs_catalog_pyteam:S1_L2_read"]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "PUT",
            "/catalog/collections/toto:S1_L1",
            json=self.updated_collection,
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED

    def test_fails_user_updates_collection_owned_by_another_user(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
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
            monkeypatch: pytest fixture for modifying module or environment attributes.
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
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)
        self.updated_collection["owner"] = "toto"
        response = client.request(
            "PUT",
            "/catalog/collections",
            json=self.updated_collection,
            **HEADER,
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

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does good requests (GET and POST method) with right permissions."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            "/catalog/search",
            params=self.search_params,
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK
        response = client.request("POST", "/catalog/search", json=self.test_json, **HEADER)
        assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions."""

        iam_roles = ["rs_catalog_toto:S1_L2_read"]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            "/catalog/search",
            params=self.search_params,
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED
        response = client.request("POST", "/catalog/search", json=self.test_json, **HEADER)
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

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does good requests (GET and POST method) with right permissions.
        Also test that the user gets the right number of items matching the search request parameters."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/search",
            params=self.search_params_ids,
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK
        content = json.loads(response.content)
        assert content["context"] == {"limit": 10, "returned": 1}

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/search",
            params=self.search_params_filter,
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK
        content = json.loads(response.content)
        assert content["context"] == {"limit": 10, "returned": 2}

        response = client.request(
            "POST",
            "/catalog/collections/toto:S1_L1/search",
            json=self.test_json,
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK
        content = json.loads(response.content)
        assert content["context"] == {"limit": 10, "returned": 2}

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without the right permissions."""

        iam_roles = ["rs_catalog_toto:S1_L2_read"]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            "/catalog/collections/toto:S1_L1/search",
            params=self.search_params_filter,
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED
        response = client.request(
            "POST",
            "/catalog/collections/toto:S1_L1/search",
            json=self.test_json,
            **HEADER,
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

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=too-many-locals
        """Test used to verify the generation of a presigned url for a download."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
            "rs_catalog_toto:*_download",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

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

            for user, file in users_map.items():
                response = client.request(
                    "GET",
                    f"/catalog/collections/{user}S1_L1/items/{file}/download/COG",
                    **HEADER,
                )
                assert response.status_code == HTTP_302_FOUND

            # Check that response is empty
            assert response.content == b""

            # call the redirected url
            product_content = requests.get(response.headers["location"], timeout=10)

            assert product_content.status_code == HTTP_200_OK
            assert product_content.content.decode() == object_content
            assert (
                client.get(
                    f"/catalog/collections/{user}S1_L1/items/INCORRECT_ITEM_ID/download/COG",
                    headers={APIKEY_HEADER: VALID_APIKEY},
                ).status_code
                == HTTP_404_NOT_FOUND
            )

        finally:
            server.stop()
            # Remove bucket credentials form env variables / should create a s3_handler without credentials error
            self.clear_aws_credentials()

        response = client.get(
            "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/COG",
            headers={APIKEY_HEADER: VALID_APIKEY},
        )
        assert response.status_code == HTTP_400_BAD_REQUEST
        assert response.content == b'"Could not find s3 credentials"'

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test used to verify the generation of a presigned url for a download."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

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
                "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d/download/COG",
                **HEADER,
            )
            assert response.status_code == HTTP_401_UNAUTHORIZED

        finally:
            server.stop()
            # Remove bucket credentials form env variables / should create a s3_handler without credentials error
            self.clear_aws_credentials()


class TestAuthenticationDelete:
    """Contains authentication tests when a user wants to delete a collection."""

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he deletes a collection with right permissions"""

        iam_roles: list[str] = []
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)
        # create the collections first
        collections = ["pyteam_fixture_collection_1", "pyteam_fixture_collection_2"]
        for collection in collections:
            new_collection = {
                "id": f"{collection}",
                "type": "Collection",
                "description": "test_description",
                "stac_version": "1.0.0",
                "owner": "pyteam",
            }

            response = client.request(
                "POST",
                "/catalog/collections",
                json=new_collection,
                headers={APIKEY_HEADER: VALID_APIKEY},
            )
            assert response.status_code == HTTP_200_OK

        # request the endpoint by using "user:collection"
        response = client.request(
            "DELETE",
            f"/catalog/collections/pyteam:{collections[0]}",
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK
        # request the endpoint by using just "collection" (the user is
        # loaded by the rs-server-catalog directly from the apikey)
        response = client.request(
            "DELETE",
            f"/catalog/collections/{collections[1]}",
            **HEADER,
        )
        assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he tries to delete a collection without right permissions."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)
        # sending a request from user pyteam (loaded from the apikey) to delete
        # the S1_L1 collection owned by the `toto` user.
        # 401 unauthorized reponse should be received
        response = client.request(
            "DELETE",
            "/catalog/collections/toto:S1_L1",
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationPostOneItem:
    """Contains authentication tests when a user wants to post one item."""

    item_id = "S1SIWOCN_20220412T054447_0024_S139"
    feature_to_post = {
        "collection": "S1_L1",
        "assets": {
            "zarr": {"href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip", "roles": ["data"]},
            "cog": {"href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip", "roles": ["data"]},
            "ncdf": {"href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T902.nc", "roles": ["data"]},
        },
        "bbox": [0],
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
        "id": item_id,
        "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        "other_metadata": {},
        "properties": {
            "gsd": 0.5971642834779395,
            "width": 2500,
            "height": 2500,
            "datetime": "2000-02-02T00:00:00Z",
            "proj:epsg": 3857,
            "orientation": "nadir",
        },
        "stac_extensions": [
            "https://stac-extensions.github.io/eopf/v1.0.0/schema.json",
            "https://stac-extensions.github.io/eo/v1.1.0/schema.json",
            "https://stac-extensions.github.io/sat/v1.0.0/schema.json",
            "https://stac-extensions.github.io/view/v1.0.0/schema.json",
            "https://stac-extensions.github.io/scientific/v1.0.0/schema.json",
            "https://stac-extensions.github.io/processing/v1.1.0/schema.json",
        ],
        "stac_version": "1.0.0",
        "type": "Feature",
    }

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does a good request with right permissions."""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "POST",
            "/catalog/collections/S1_L1/items",
            json=self.feature_to_post,
            **HEADER,
        )
        # check if the item was well added to the collection
        assert response.status_code == HTTP_200_OK
        # delete the item, don't change the collection, because it is used
        # by other tests also
        response = client.request(
            "DELETE",
            f"/catalog/collections/S1_L1/items/{self.item_id}",
            json=self.feature_to_post,
            **HEADER,
        )
        # check if the item was deleted from the collection
        assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without right permissions."""

        iam_roles = ["rs_catalog_toto:S1_L1_read"]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "POST",
            "/catalog/collections/toto:S1_L1/items",
            json=self.feature_to_post,
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationGetCatalogOwnerId:
    """Contains authentication tests when a user wants to get a specific catalog."""

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_200_OK status code response
        when he does a good request with right permissions"""

        iam_roles = [
            "rs_catalog_toto:*_read",
            "rs_catalog_toto:*_write",
        ]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)
        users_map = {"toto": "toto", "pyteam": ""}
        for _, val in users_map.items():
            response = client.request(
                "GET",
                f"/catalog/catalogs/{val}",
                **HEADER,
            )
            assert response.status_code == HTTP_200_OK

    def test_fails_if_not_authorized(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):
        """Test that the user gets a HTTP_401_UNAUTHORIZED status code response
        when he does a good request without right permissions."""

        iam_roles = ["rs_catalog_toto:*_write"]
        init_test(mocker, monkeypatch, httpx_mock, iam_roles)

        response = client.request(
            "GET",
            "/catalog/catalogs/toto",
            **HEADER,
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED


def test_error_when_not_authenticated(
    mocker,
    client,
):
    """Test that the user gets a HTPP_403_FORBIDDEN status code response
    when he tries to call an endpoint without being authenticated."""
    mocker.patch("rs_server_common.settings.CLUSTER_MODE", new=True, autospec=False)
    response = client.request("GET", "/catalog/")
    assert response.status_code == HTTP_403_FORBIDDEN
