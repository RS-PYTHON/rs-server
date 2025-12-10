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
from fastapi import HTTPException
from fastapi.testclient import TestClient
from rs_server_edrs.api.edrs_endpoints import MockPgstacEdrs
from starlette.requests import Request


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
        "stac_version": "1.1.0",
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
def test_edrs_single_item_not_found(client: TestClient, fastapi_app):  # pylint: disable=unused-argument
    """Requesting an unknown item should return a 404."""
    missing_item_id = "UNKNOWN_SESSION"
    resp = client.get(f"/edrs/collections/s1_pedc/items/{missing_item_id}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "NotFound"
    assert body["description"] == f"Session '{missing_item_id}' not found in collection 's1_pedc'"


@pytest.mark.unit
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_edrs_items_preserves_extra_fields(
    client: TestClient,
    fastapi_app,
    monkeypatch,
):  # pylint: disable=unused-argument
    """Extra keys from filtering (e.g. paging metadata) are merged into the response."""

    def fake_filter_and_paginate(features_list, *_args, **_kwargs):  # pylint: disable=unused-argument
        return {"type": "FeatureCollection", "features": features_list, "extra": {"returned": len(features_list)}}

    monkeypatch.setattr("rs_server_edrs.api.edrs_endpoints.filter_and_paginate_features", fake_filter_and_paginate)

    resp = client.get("/edrs/collections/s1_pedc/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body["extra"] == {"returned": len(body.get("features", []))}


@pytest.mark.unit
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_edrs_items_invalid_filter_returns_422(
    client: TestClient,
    fastapi_app,
    monkeypatch,
):  # pylint: disable=unused-argument
    """ValueError during filtering should surface as a 422 error."""

    def fake_filter_and_paginate(_features_list, *_args, **_kwargs):  # pylint: disable=unused-argument
        raise ValueError("bad filter")

    monkeypatch.setattr("rs_server_edrs.api.edrs_endpoints.filter_and_paginate_features", fake_filter_and_paginate)

    resp = client.get("/edrs/collections/s1_pedc/items?filter=platform='sentinel-1a'")
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "UnprocessableContent"
    assert body["description"] == "bad filter"


@pytest.mark.unit
def test_mock_pgstac_edrs_process_search_not_supported():
    """MockPgstacEdrs.process_search should raise the documented 404."""
    request = Request({"type": "http", "path": "/edrs/search"})
    pgstac = MockPgstacEdrs(request=request)
    with pytest.raises(HTTPException) as exc:
        pgstac.process_search(request)
    assert exc.value.status_code == 404  # /search is not available for EDRS
    assert exc.value.detail == "EDRS does not support /search. Use /edrs/collections/{id}/items."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_items_missing_collection_returns_404(monkeypatch):
    """When the collection is unknown, get_items should raise the 404 with expected detail."""
    monkeypatch.setattr("rs_server_edrs.api.edrs_endpoints.edrs_select_config", lambda _cid: None)
    pgstac = MockPgstacEdrs()
    with pytest.raises(HTTPException) as exc:
        await pgstac.get_items("unknown", Request({"type": "http"}))  # pylint: disable=not-callable
    assert exc.value.status_code == 404  # no configuration found for the collection
    assert exc.value.detail == "Collection not found"  # expected error detail from the guard


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_items_returns_empty_when_no_satellites(monkeypatch):
    """Collections without satellite entries should yield an empty FeatureCollection."""
    monkeypatch.setattr(
        "rs_server_edrs.api.edrs_endpoints.edrs_select_config",
        lambda _cid: {"station": "pedc", "satellite": ""},
    )
    pgstac = MockPgstacEdrs()
    resp = await pgstac.get_items("s1_pedc", Request({"type": "http"}))  # pylint: disable=not-callable
    assert resp["type"] == "FeatureCollection"  # still returns a collection wrapper
    assert resp.get("features") == []  # no satellites => no features


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_items_closes_connector_even_on_close_error(monkeypatch):
    """Connector.close exceptions must be swallowed while still returning the built collection."""
    close_called = {"called": False}

    class FakeConnector:
        """Connector stub to trigger a close error path."""

        def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
            """No-op init."""

        def connect(self):
            """No-op connect."""
            return None

        def close(self):
            """Raise to exercise close error handling."""
            close_called["called"] = True
            raise RuntimeError("close failed")

    monkeypatch.setattr("rs_server_edrs.api.edrs_endpoints.EDRSConnector", FakeConnector)
    monkeypatch.setattr("rs_server_edrs.api.edrs_endpoints.load_station_config", lambda *_a, **_k: {})
    monkeypatch.setattr(
        "rs_server_edrs.api.edrs_endpoints.build_edrs_item_collection",
        lambda *_a, **_k: {"type": "FeatureCollection", "features": [{"id": "X"}]},
    )
    monkeypatch.setattr(
        "rs_server_edrs.api.edrs_endpoints.edrs_select_config",
        lambda _cid: {"station": "pedc", "satellite": "S1A"},
    )

    pgstac = MockPgstacEdrs()
    resp = await pgstac.get_items("s1_pedc", Request({"type": "http"}))  # pylint: disable=not-callable
    assert close_called["called"] is True  # close attempted even when it fails
    assert resp["type"] == "FeatureCollection"  # still returns the built collection
    assert resp["features"][0]["id"] == "X"  # content from stubbed builder is preserved


@pytest.mark.unit
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_get_items_ignores_non_nominal_directories(
    client: TestClient,
    fastapi_app,
    monkeypatch,
):  # pylint: disable=unused-argument
    """Non-NOMINAL folder entries should be skipped by is_session_dir, yielding no items."""

    class FakeConnector:
        """Connector stub that returns only non-matching session directories."""

        def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
            """No-op init."""

        def connect(self):
            """No-op connect."""
            return None

        def close(self):
            """No-op close."""
            return None

        def walk(self, path):
            # Return a directory path that does not match /NOMINAL/<sat>/DCS_..._dat
            """Yield a fake dir entry outside /NOMINAL to be ignored."""
            return [{"path": "/WRONGPATH/DCS_99_99_dat", "type": "dir"}]

    monkeypatch.setattr("rs_server_edrs.api.edrs_endpoints.EDRSConnector", FakeConnector)
    monkeypatch.setattr("rs_server_edrs.api.edrs_endpoints.load_station_config", lambda *_a, **_k: {})
    monkeypatch.setattr(
        "rs_server_edrs.api.edrs_endpoints.edrs_select_config",
        lambda _cid: {"station": "pedc", "satellite": "S1A"},
    )

    resp = client.get("/edrs/collections/s1_pedc/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert body.get("features") == []  # no matching session dirs -> empty collection


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
