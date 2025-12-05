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
"""
Basic endpoint tests for the EDRS service.
"""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.unit
@pytest.mark.parametrize(
    "path,is_redirect",
    [
        ("/edrs/", True),
        ("/edrs", False),
    ],
)
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_edrs_home_and_root_catalog(
    client: TestClient,
    path: str,
    is_redirect: bool,
    fastapi_app,
):  # pylint: disable=unused-argument
    """Verify /edrs/ redirects and /edrs returns a STAC Catalog."""
    resp = client.get(path, follow_redirects=False)
    if is_redirect:
        assert resp.status_code in (301, 302, 307, 308)
        location = resp.headers.get("location", "")
        assert location.endswith("/edrs")
    else:
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("type") == "Catalog"
        assert isinstance(body.get("links"), list)
        assert body["links"]  # non-empty


@pytest.mark.unit
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_edrs_collections(client: TestClient, fastapi_app):  # pylint: disable=unused-argument
    """Collections endpoint should return configured collections."""
    resp = client.get("/edrs/collections")
    assert resp.status_code == 200
    body = resp.json()
    collections = body.get("collections") or []
    assert isinstance(collections, list)
    ids = {c.get("id") for c in collections if isinstance(c, dict)}
    assert ids  # non-empty


@pytest.mark.unit
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_edrs_collection_detail(client: TestClient, fastapi_app):  # pylint: disable=unused-argument
    """Single collection should be retrievable by id."""
    resp = client.get("/edrs/collections/s1_pedc")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("id") == "s1_pedc"
    assert body.get("title")


@pytest.mark.unit
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_edrs_collection_items(client: TestClient, fastapi_app):  # pylint: disable=unused-argument
    """Items endpoint should return a FeatureCollection (no filters)."""
    resp = client.get("/edrs/collections/s1_pedc/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("type") == "FeatureCollection"
    assert isinstance(body.get("features"), list)


@pytest.mark.unit
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_edrs_single_item(client: TestClient, fastapi_app):  # pylint: disable=unused-argument
    """Single item should be retrievable by id."""
    resp = client.get("/edrs/collections/s1_pedc/items/DCS_01_202501270945000000112233")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "type": "Feature",
        "geometry": None,
        "properties": {
            "datetime": "2024-01-01T01:00:00Z",
            "start_datetime": "2024-01-01T00:00:00Z",
            "end_datetime": "2024-01-02T01:00:00Z",
            "platform": "sentinel-1a",
            "constellation": "sentinel-1",
            "published": "2024-01-02T01:00:00Z",
        },
        "id": "DCS_01_202501270945000000112233",
        "stac_version": "1.0.0",
        "assets": {
            "DCS_01_202501270945000000112233_dat_ch_1_DSDB_00001.raw": {
                "href": (
                    "ftps://pedc/NOMINAL/S1A/"
                    "DCS_01_202501270945000000112233_dat/ch_1/"
                    "DCS_01_202501270945000000112233_dat_ch_1_DSDB_00001.raw"
                ),
                "title": "DCS_01_202501270945000000112233_dat_ch_1_DSDB_00001.raw",
                "roles": ["cadu"],
                "file:size": 5,
                "channel": 1,
                "created": "2024-01-01T01:00:00Z",
                "updated": "2024-01-01T01:00:00Z",
            },
            "DCS_01_202501270945000000112233_dat_ch_1_DSDB_00002.raw": {
                "href": (
                    "ftps://pedc/NOMINAL/S1A/"
                    "DCS_01_202501270945000000112233_dat/ch_1/"
                    "DCS_01_202501270945000000112233_dat_ch_1_DSDB_00002.raw"
                ),
                "title": "DCS_01_202501270945000000112233_dat_ch_1_DSDB_00002.raw",
                "roles": ["cadu"],
                "file:size": 5,
                "channel": 1,
                "created": "2024-01-01T01:00:00Z",
                "updated": "2024-01-01T01:00:00Z",
            },
            "DCS_01_202501270945000000112233_dat_ch_2_DSDB_00001.raw": {
                "href": (
                    "ftps://pedc/NOMINAL/S1A/"
                    "DCS_01_202501270945000000112233_dat/ch_2/"
                    "DCS_01_202501270945000000112233_dat_ch_2_DSDB_00001.raw"
                ),
                "title": "DCS_01_202501270945000000112233_dat_ch_2_DSDB_00001.raw",
                "roles": ["cadu"],
                "file:size": 5,
                "channel": 2,
                "created": "2024-01-02T01:00:00Z",
                "updated": "2024-01-02T01:00:00Z",
            },
        },
        "links": [
            {
                "href": "http://testserver/edrs/collections/s1_pedc",
                "rel": "collection",
                "type": "application/json",
                "title": "DCS_01_202501270945000000112233",
            },
            {
                "href": "http://testserver/edrs/collections/s1_pedc",
                "rel": "parent",
                "type": "application/json",
                "title": "Parent Catalog",
            },
            {
                "href": "http://testserver/edrs/",
                "rel": "root",
                "type": "application/json",
                "title": "STAC Root Catalog",
            },
            {
                "href": "http://testserver/edrs/collections/s1_pedc/items/DCS_01_202501270945000000112233",
                "rel": "self",
                "type": "application/geo+json",
                "title": "This collection",
            },
        ],
        "stac_extensions": [
            "https://stac-extensions.github.io/file/v2.1.0/schema.json",
            "https://stac-extensions.github.io/timestamps/v1.1.0/schema.json",
        ],
        "collection": "s1_pedc",
    }


@pytest.mark.unit
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
@pytest.mark.parametrize(
    "path,features",
    [
        ("/edrs/collections/s1_pedc/items?sortby=-published", 2),
        ("/edrs/collections/s1_pedc/items?sortby=+published", 2),
        ("/edrs/collections/s1_pedc/items?sortby=+datetime", 2),
        ("/edrs/collections/s1_pedc/items?sortby=-datetime", 2),
        ("/edrs/collections/s1_pedc/items?limit=1&page=1", 1),
        ("/edrs/collections/s1_pedc/items?limit=1&page=2", 1),
        ("/edrs/collections/s1_pedc/items?filter=platform='sentinel-1c'", 1),
        ("/edrs/collections/s1_pedc/items?filter=constellation='sentinel-1'", 2),
        (
            "/edrs/collections/s1_pedc/items"
            "?filter=platform='sentinel-1c' AND constellation='sentinel-1'"
            "&sortby=-published&limit=2&page=1",
            1,
        ),
        ("/edrs/collections/s1_pedc/items?datetime=2025-02-13T11:23:00Z", 0),
        ("/edrs/collections/s1_pedc/items?datetime=../2025-02-13T12:00:00Z", 2),
        ("/edrs/collections/s1_pedc/items?datetime=2026-01-01T00:00:00Z/..", 0),
        ("/edrs/collections/s1_pedc/items?datetime=2024-01-01T00:00:00Z/..", 2),
        ("/edrs/collections/s1_pedc/items?published=2024-01-01T00:00:00Z/..", 2),
        ("/edrs/collections/s1_pedc/items?published=2025-02-13T11:23:00Z/2025-02-13T11:33:00Z", 2),
        ("/edrs/collections/s1_pedc/items?published=../2025-02-13T12:00:00Z", 2),
        ("/edrs/collections/s1_pedc/items?published=2026-01-01T00:00:00Z/..", 2),
        ("/edrs/collections/s1_pedc/items?published=2024-01-02T01:00:00Z", 2),
        ("/edrs/collections/s1_pedc/items?start_datetime=2024-01-01T00:00:00Z/2024-01-15T00:00:00Z", 2),
        ("/edrs/collections/s1_pedc/items?start_datetime=2024-03-01T00:00:00Z/..", 2),
        ("/edrs/collections/s1_pedc/items?end_datetime=../2024-01-15T00:00:00Z", 2),
        ("/edrs/collections/s1_pedc/items?end_datetime=2024-02-15T00:00:00Z/..", 2),
        ("/edrs/collections/s1_pedc/items?filter=start_datetime='2024-01-01T00:00:00Z'", 2),
        ("/edrs/collections/s1_pedc/items?filter=start_datetime='2024-02-01T00:00:00Z'", 0),
        ("/edrs/collections/s1_pedc/items?filter=end_datetime='2024-01-01T01:00:00Z'", 0),
        ("/edrs/collections/s1_pedc/items?filter=end_datetime='2024-02-01T01:00:00Z'", 0),
        ("/edrs/collections/s1_pedc/items?filter=id='DCS_01_202501270945000000112233'", 1),
        ("/edrs/collections/s1_pedc/items?filter=collection='s1_pedc'", 0),
        ("/edrs/collections/s1_pedc/items?filter=platform='sentinel-1a'", 1),
        ("/edrs/collections/s1_pedc/items?filter=platform='sentinel-1a' AND constellation='sentinel-1'", 1),
        (
            "/edrs/collections/s1_pedc/items"
            "?filter-lang=cql2-json"
            "&filter="
            '{"op":"and","args":['
            '{"op":"=","args":[{"property":"platform"},{"literal":"sentinel-1c"}]},'
            '{"op":"=","args":[{"property":"constellation"},{"literal":"sentinel-1"}]}'
            "]}",
            1,
        ),
        (
            "/edrs/collections/s1_pedc/items"
            "?filter-lang=cql2-json"
            '&filter={"op":"and","args":['
            '{"op":"=","args":[{"property":"id"},{"literal":"DCS_01_202501270945000000112233"}]},'
            '{"op":"=","args":[{"property":"platform"},{"literal":"sentinel-1a"}]},'
            '{"op":"=","args":[{"property":"datetime"},{"literal":"2024-01-01T01:00:00Z"}]}'
            "]}",
            1,
        ),
        (
            "/edrs/collections/s1_pedc/items"
            "?filter-lang=cql2-json"
            '&filter={"op":"and","args":['
            '{"op":"=","args":[{"property":"published"},{"literal":"2025-02-13T11:28:42Z"}]},'
            '{"op":"=","args":[{"property":"constellation"},{"literal":"sentinel-2"}]}'
            "]}",
            0,
        ),
    ],
)
def test_edrs_items_with_filters(client: TestClient, fastapi_app, path, features):  # pylint: disable=unused-argument
    """Items endpoint under assorted sort/filter/pagination scenarios returns expected feature count."""
    resp = client.get(path)
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("type") == "FeatureCollection"
    assert isinstance(body.get("features"), list)
    assert len(body.get("features")) == features
