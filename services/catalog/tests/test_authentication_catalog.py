"""Unit tests for the authentication."""

import json

from pytest_httpx import HTTPXMock
from rs_server_common.authentication import APIKEY_HEADER, ttl_cache
from starlette.status import HTTP_200_OK, HTTP_401_UNAUTHORIZED

# Dummy url for the uac manager check endpoint
RSPY_UAC_CHECK_URL = "http://www.rspy-uac-manager.com"

# Dummy api key values
VALID_APIKEY = "VALID_API_KEY"
WRONG_APIKEY = "WRONG_APIKEY"

# Test two ways of passing the api key: in HTTP header and in url query parameter (disabled for now)
PASS_THE_APIKEY = [
    {"headers": {APIKEY_HEADER: VALID_APIKEY}},
    # {"params": {APIKEY_QUERY: VALID_APIKEY}}
]

# pylint: skip-file # ignore pylint issues for this file, TODO remove this


def test_authentication(mocker, monkeypatch, httpx_mock: HTTPXMock, client):
    """
    Test that the http endpoints are protected and return 403 if not authenticated.
    """

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
            "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
            "name": "toto",
            "user_login": "pyteam",
            "is_active": True,
            "never_expire": True,
            "expiration_date": "2024-04-10T13:57:28.475052",
            "total_queries": 0,
            "latest_sync_date": "2024-03-26T13:57:28.475058",
            "iam_roles": [
                "rs_cadip_SGS_download",
                "rs_cadip_MTI_read",
                "rs_adgs_read",
                "rs_cadip_cadip_read",
                "rs_adgs_download",
                "default-roles-rspy",
                "rs_catalog_toto:*_read",
                "rs_catalog_titi:S2_L1_read",
                "rs_catalog_darius:*_write",
                "rs_cadip_cadip_download",
                "rs_catalog_toto:sentinel1-grd_read",
            ],
            "config": {},
            "allowed_referers": ["toto"],
        },
    )

    valid_links = [
        {"rel": "self", "type": "application/json", "href": "http://testserver/"},
        {"rel": "root", "type": "application/json", "href": "http://testserver/"},
        {"rel": "data", "type": "application/json", "href": "http://testserver/collections"},
        {
            "rel": "conformance",
            "type": "application/json",
            "title": "STAC/WFS3 conformance classes implemented by this server",
            "href": "http://testserver/conformance",
        },
        {
            "rel": "search",
            "type": "application/geo+json",
            "title": "STAC search",
            "href": "http://testserver/search",
            "method": "GET",
        },
        {
            "rel": "search",
            "type": "application/geo+json",
            "title": "STAC search",
            "href": "http://testserver/search",
            "method": "POST",
        },
        {
            "rel": "child",
            "type": "application/json",
            "title": "toto_S1_L1",
            "href": "http://testserver/collections/toto_S1_L1",
        },
        {
            "rel": "child",
            "type": "application/json",
            "title": "toto_S2_L3",
            "href": "http://testserver/collections/toto_S2_L3",
        },
        {
            "rel": "child",
            "type": "application/json",
            "title": "titi_S2_L1",
            "href": "http://testserver/collections/titi_S2_L1",
        },
        {
            "rel": "service-desc",
            "type": "application/vnd.oai.openapi+json;version=3.0",
            "title": "OpenAPI service description",
            "href": "http://testserver/api",
        },
        {
            "rel": "service-doc",
            "type": "text/html",
            "title": "OpenAPI service documentation",
            "href": "http://testserver/api.html",
        },
        {"rel": "child", "type": "application/json", "href": "http://testserver/catalog/toto"},
    ]
    # Pass the api key in HTTP headers then in url query parameter
    for pass_the_apikey in PASS_THE_APIKEY:
        landing_page_response = client.request("GET", "/catalog/", **pass_the_apikey)
        assert landing_page_response.status_code == HTTP_200_OK
        content = json.loads(landing_page_response.content)
        assert content["links"] == valid_links

    # assert client.request("GET", "/catalog/collections").status_code == HTTP_403_FORBIDDEN

    pyteam_collection = {
        "id": "S2_L1",
        "type": "Collection",
        "links": [
            {
                "rel": "items",
                "type": "application/geo+json",
                "href": "http://testserver/collections/S2_L1/items",
            },
            {"rel": "parent", "type": "application/json", "href": "http://testserver/"},
            {"rel": "root", "type": "application/json", "href": "http://testserver/"},
            {"rel": "self", "type": "application/json", "href": "http://testserver/collections/S2_L1"},
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
        "extent": {
            "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
            "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
        },
        "license": "public-domain",
        "description": "Some description",
        "stac_version": "1.0.0",
    }
    post_response = client.post("/catalog/collections", json=pyteam_collection, **pass_the_apikey)
    assert post_response.status_code == HTTP_200_OK
    valid_collections = [
        {
            "id": "toto_S1_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/collections/toto_S1_L1/items",
                },
                {"rel": "parent", "type": "application/json", "href": "http://testserver/"},
                {"rel": "root", "type": "application/json", "href": "http://testserver/"},
                {"rel": "self", "type": "application/json", "href": "http://testserver/collections/toto_S1_L1"},
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
            "owner": "toto",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
            "license": "public-domain",
            "description": "Some description",
            "stac_version": "1.0.0",
        },
        {
            "id": "toto_S2_L3",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/collections/toto_S2_L3/items",
                },
                {"rel": "parent", "type": "application/json", "href": "http://testserver/"},
                {"rel": "root", "type": "application/json", "href": "http://testserver/"},
                {"rel": "self", "type": "application/json", "href": "http://testserver/collections/toto_S2_L3"},
                {
                    "rel": "items",
                    "href": "http://localhost:8082/collections/S2_L3/items",
                    "type": "application/geo+json",
                },
                {
                    "rel": "license",
                    "href": "https://creativecommons.org/licenses/publicdomain/",
                    "title": "public domain",
                },
            ],
            "owner": "toto",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
            "license": "public-domain",
            "description": "Some description",
            "stac_version": "1.0.0",
        },
        {
            "id": "titi_S2_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/collections/titi_S2_L1/items",
                },
                {"rel": "parent", "type": "application/json", "href": "http://testserver/"},
                {"rel": "root", "type": "application/json", "href": "http://testserver/"},
                {"rel": "self", "type": "application/json", "href": "http://testserver/collections/titi_S2_L1"},
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
            "owner": "titi",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
            "license": "public-domain",
            "description": "Some description",
            "stac_version": "1.0.0",
        },
        {
            "id": "pyteam_S2_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/collections/pyteam_S2_L1/items",
                },
                {"rel": "parent", "type": "application/json", "href": "http://testserver/"},
                {"rel": "root", "type": "application/json", "href": "http://testserver/"},
                {"rel": "self", "type": "application/json", "href": "http://testserver/collections/pyteam_S2_L1"},
                {"rel": "items", "href": "http://testserver/collections/S2_L1/items", "type": "application/geo+json"},
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
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
            "license": "public-domain",
            "description": "Some description",
            "stac_version": "1.0.0",
        },
    ]
    # Pass the api key in HTTP headers then in url query parameter
    for pass_the_apikey in PASS_THE_APIKEY:
        all_collections = client.request("GET", "/catalog/collections", **pass_the_apikey)

        assert all_collections.status_code == HTTP_200_OK
        content = json.loads(all_collections.content)
        assert content["collections"] == valid_collections


class TestAuthenticationGetOneCollection:
    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

        ttl_cache.clear()  # clear the cached response

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_read",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        toto_collection = {
            "id": "S1_L1",
            "type": "Collection",
            "links": [
                {
                    "rel": "items",
                    "type": "application/geo+json",
                    "href": "http://testserver/catalog/toto/collections/S1_L1/items",
                },
                {"rel": "parent", "type": "application/json", "href": "http://testserver/catalog/toto"},
                {"rel": "root", "type": "application/json", "href": "http://testserver/catalog/toto"},
                {
                    "rel": "self",
                    "type": "application/json",
                    "href": "http://testserver/catalog/toto/collections/S1_L1",
                },
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
            "owner": "toto",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
            "license": "public-domain",
            "description": "Some description",
            "stac_version": "1.0.0",
        }
        # Pass the api key in HTTP headers then in url query parameter
        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "GET",
                "/catalog/collections/toto:S1_L1",
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_200_OK
            assert toto_collection == json.loads(response.content)

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_write",
                    "rs_catalog_toto:S1_L2_read",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )
        # Pass the api key in HTTP headers then in url query parameter
        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "GET",
                "/catalog/collections/toto:S1_L1",
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationGetItems:
    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

        ttl_cache.clear()  # clear the cached response

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_read",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "GET",
                "/catalog/collections/toto:S1_L1/items/",
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_write",
                    "rs_catalog_toto:S1_L2_read",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "GET",
                "/catalog/collections/toto:S1_L1/items/",
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationGetOneItem:
    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

        ttl_cache.clear()  # clear the cached response

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_read",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        feature_toto_s1_l1_0 = {
            "id": "fe916452-ba6f-4631-9154-c249924a122d",
            "bbox": [-94.6334839, 37.0332547, -94.6005249, 37.0595608],
            "type": "Feature",
            "assets": {
                "COG": {
                    "href": """s3://temp-bucket/toto_S1_L1/images/may24C355000e4102500n.tif""",
                    "type": "image/tiff; application=geotiff; profile=cloud-optimized",
                    "title": "NOAA STORM COG",
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
                "owner": "toto",
                "width": 2500,
                "height": 2500,
                "datetime": "2000-02-02T00:00:00Z",
                "owner_id": "toto",
                "proj:epsg": 3857,
                "orientation": "nadir",
            },
            "stac_version": "1.0.0",
            "stac_extensions": [
                "https://stac-extensions.github.io/eo/v1.0.0/schema.json",
                "https://stac-extensions.github.io/projection/v1.0.0/schema.json",
            ],
        }

        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "GET",
                "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_200_OK
            id = json.loads(response.content)["id"]
            assert id == feature_toto_s1_l1_0["id"]

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_write",
                    "rs_catalog_toto:S1_L2_read",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "GET",
                "/catalog/collections/toto:S1_L1/items/fe916452-ba6f-4631-9154-c249924a122d",
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationPostOneCollection:
    collection_to_post = {
        "id": "MY_SPECIAL_COLLECTION",
        "type": "Collection",
        "owner": "toto",
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
        "extent": {
            "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
            "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
        },
        "license": "public-domain",
        "description": "Some description",
        "stac_version": "1.0.0",
    }

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

        ttl_cache.clear()  # clear the cached response

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_read",
                    "rs_catalog_toto:*_write",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "POST",
                "/catalog/collections",
                json=self.collection_to_post,
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:S1_L2_read",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "POST",
                "/catalog/collections",
                json=self.collection_to_post,
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthicationPutOneCollection:

    updated_collection = {
        "id": "S1_L1",
        "type": "Collection",
        "links": [
            {
                "rel": "items",
                "type": "application/geo+json",
                "href": "http://testserver/collections/toto_S1_L1/items",
            },
            {"rel": "parent", "type": "application/json", "href": "http://testserver/"},
            {"rel": "root", "type": "application/json", "href": "http://testserver/"},
            {"rel": "self", "type": "application/json", "href": "http://testserver/collections/toto_S1_L1"},
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
        "owner": "toto",
        "extent": {
            "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
            "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
        },
        "license": "public-domain",
        "description": "This is the description from the updated S1_L1 collection.",
        "stac_version": "1.0.0",
    }

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

        ttl_cache.clear()  # clear the cached response

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_read",
                    "rs_catalog_toto:*_write",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "PUT",
                "/catalog/collections/toto:S1_L1",
                json=self.updated_collection,
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_200_OK

    def test_fails_without_good_perms(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:S1_L2_read",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "PUT",
                "/catalog/collections/toto:S1_L1",
                json=self.updated_collection,
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_401_UNAUTHORIZED


class TestAuthenticationSearch:

    def test_http200_with_good_authentication(
        self,
        mocker,
        monkeypatch,
        httpx_mock: HTTPXMock,
        client,
    ):  # pylint: disable=missing-function-docstring

        ttl_cache.clear()  # clear the cached response

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
                "api_key": "530e8b63-6551-414d-bb45-fc881f314cbd",
                "name": "toto",
                "user_login": "pyteam",
                "is_active": True,
                "never_expire": True,
                "expiration_date": "2024-04-10T13:57:28.475052",
                "total_queries": 0,
                "latest_sync_date": "2024-03-26T13:57:28.475058",
                "iam_roles": [
                    "rs_catalog_toto:*_read",
                    "rs_catalog_toto:*_write",
                ],
                "config": {},
                "allowed_referers": ["toto"],
            },
        )

        search_params = {"collections": "S1_L1", "filter-lang": "cql2-text", "filter": "width=2500 AND owner_id='toto'"}
        for pass_the_apikey in PASS_THE_APIKEY:
            response = client.request(
                "GET",
                "/catalog/search",
                params=search_params,
                **pass_the_apikey,
            )
            assert response.status_code == HTTP_200_OK
