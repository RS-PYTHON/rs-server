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
