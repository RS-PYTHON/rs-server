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

"""Module for interacting with PRIP system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the PRIP stations.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""


import os.path as osp
from pathlib import Path

from stac_pydantic import ItemCollection

from fastapi import APIRouter, Request
from typing import Literal
from fastapi.responses import RedirectResponse

from eodag import EODataAccessGateway

from rs_server_prip import prip_tags

from stac_fastapi.api.models import GeoJSONResponse
from stac_pydantic import Item, Collection

from datetime import datetime

from rs_server_common.authentication import authentication

from rs_server_common.stac_api_common import (
    MockPgstac,
    handle_exceptions
)

from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)
router = APIRouter(tags=prip_tags)
ADGS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config"

class MockPgstacPrip(MockPgstac):
    """PRIP implementation of MockPgstac"""

    def __init__(self, request: Request | None = None, readwrite: Literal["r", "w"] | None = None):
        super().__init__(
            request=request,
            readwrite=readwrite,
            service="prip",
            all_collections=lambda: [],                # Empty list or replace with real config
            select_config=lambda _id: None,            # Stub for now
            stac_to_odata=lambda x: x,                 # Identity, update later
            map_mission=lambda p, c: (p, c),           # Identity, update later
            temporal_mapping={
                "start_datetime": "ContentDate/Start",
                "end_datetime": "ContentDate/End",
            },
        )
        self.sortby = "-created"
    
    def process_search(self, station, odata_params, collection_provider, limit, page) -> ItemCollection:
        raise NotImplementedError("PRIP search not implemented yet.")

@router.get("/", include_in_schema=False)
async def home_endpoint():
    """Redirect to the landing page."""
    return RedirectResponse("/prip")

@router.get("/prip")
async def get_root_catalog(request: Request):
    logger.info(f"Starting {request.url.path}")
    authentication.auth_validation("prip", "landing_page", request=request)
    return await request.app.state.pgstac_client.landing_page(request=request)

@router.get("/prip/conformance")
async def get_conformance(request: Request):
    """Return the STAC/OGC conformance classes implemented by this server."""
    authentication.auth_validation("prip", "landing_page", request=request)
    return await request.app.state.pgstac_client.conformance()

@router.get("/prip/collections", response_class=GeoJSONResponse)
@handle_exceptions
async def list_collections(request: Request):
    dag = EODataAccessGateway(user_conf_file_path="config/prip_ws_config.yaml")
    products = dag.search(provider="prip")

    collections = {}
    for p in products:
        pt = p.properties.get("id", "UNKNOWN")
        pub_date = p.properties.get("publicationDate", "2020-01-01T00:00:00Z")
        pub_date = pub_date or "2020-01-01T00:00:00Z"

        if pt not in collections:
            collections[pt] = Collection(
                type="Collection",
                id=pt,
                title=f"{pt} products",
                description=f"Collection of {pt} products",
                license="proprietary",
                extent={
                    "spatial": {"bbox": [[-180.0, -90.0, 180.0, 90.0]]},
                    "temporal": {"interval": [[pub_date, None]]},
                },
                links=[],
                stac_extensions=[],
            )

    return {
        "collections": [c.dict(by_alias=True) for c in collections.values()],
        "type": "Catalog"
    }

@router.get("/prip/collections/{collection_id}")
@handle_exceptions
async def get_adgs_collection(
    request: Request,
    collection_id: str,
) -> list[dict] | dict | Collection:
    """Return a specific ADGS collection."""
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_collection(collection_id, request)

@router.get("/prip/collections/{collection_id}/items", response_class=GeoJSONResponse)
async def get_prip_items(
    request: Request,
    collection_id: str,
    limit: int = 10,
    page: int = 1,
):
    item = Item(
        id="mock-product-001",
        type="Feature",
        geometry=None,
        bbox=[0, 0, 1, 1],
        properties={
            "datetime": "2025-08-01T00:00:00Z",
            "platform": "S1A",
            "instrument": "SAR"
        },
        collection=collection_id,
        assets={
            "product": {
                "href": "http://127.0.0.1:5000/Products(123)/$value",
                "type": "application/zip",
                "roles": ["data", "metadata"]
            }
        },
        links=[]
    )
    return {"type": "FeatureCollection", "features": [item.dict(by_alias=True)]}
