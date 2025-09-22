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

"""Unit tests for the stac pagination."""

import json
import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient
from rs_server_common.middlewares import PaginationLinksMiddleware, HandleExceptionsMiddleware
import httpx
import brotli


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"], ids=["asyncio"])
@pytest.mark.parametrize("use_br", [True, False], ids=["br", "no_br"])
async def test_pagination_links_middleware_catalog_authrefs(use_br):
    """
    Tests for cluster where there must be set the 'br' encoding and authentication references for /catalog
    """
    app = FastAPI()
    app.add_middleware(HandleExceptionsMiddleware)
    app.add_middleware(PaginationLinksMiddleware)

    @app.post("/catalog/search")
    def catalog_search():
        payload = {"links": [{"rel": "previous"}], "features": []}
        raw = json.dumps(payload).encode("utf-8")
        if use_br:
            body = brotli.compress(raw)
            headers = {"content-type": "application/json", "content-encoding": "br"}
            return Response(content=body, status_code=200, headers=headers)
        return Response(content=raw, status_code=200, media_type="application/json")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        if use_br:
            #'encoding == "br"' + if path == "/catalog/search" (sets auth:refs).
            # checks if the headers were kept
            async with client.stream("POST", "/catalog/search", json={"limit": 1}) as resp:
                assert resp.status_code == 200
                assert resp.headers.get("content-type") == "application/json"
                assert resp.headers.get("content-encoding") == "br"
        else:
            resp = await client.post("/catalog/search", json={"limit": 1})
            assert resp.status_code == 200
            assert resp.headers.get("content-type") == "application/json"
            assert resp.headers.get("content-encoding") is None

            # checks if 'first' was added when there is 'previous'
            data = resp.json()
            assert any(l.get("rel") == "first" for l in data.get("links", []))

@pytest.mark.anyio
def test_pagination_links_middleware_handles_malformed_json():
    """
    Test case with a malformed JSON 
    """
    app = FastAPI()
    app.add_middleware(HandleExceptionsMiddleware)
    app.add_middleware(PaginationLinksMiddleware)

    @app.post("/auxip/search")
    def auxip_search():
        headers = {"content-type": "application/json"}
        return Response(content=b"not-json", status_code=200, headers=headers)

    client = TestClient(app)
    resp = client.post("/auxip/search", json={"limit": 1})

    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "application/json"
    assert resp.headers.get("content-encoding") is None
    assert resp.text == "not-json"
