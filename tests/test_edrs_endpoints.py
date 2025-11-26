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
@pytest.mark.parametrize("fastapi_app", [{"router_prefix": "/edrs"}], indirect=True)
def test_edrs_root_catalog(client: TestClient, fastapi_app):  # pylint: disable=unused-argument
    """Landing page should be a STAC Catalog with links."""
    resp = client.get("/edrs")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("type") == "Catalog"
    assert isinstance(body.get("links"), list)
    assert body["links"]  # non-empty
