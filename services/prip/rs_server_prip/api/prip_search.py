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
from datetime import datetime
from pathlib import Path
from typing import Literal

from eodag import EODataAccessGateway
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from rs_server_common.authentication import authentication
from rs_server_common.stac_api_common import MockPgstac, handle_exceptions
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import validate_inputs_format, validate_sort_input
from rs_server_prip import prip_tags
from rs_server_prip.prip_utils import (
    prip_map_mission,
    read_conf,
    select_config,
    stac_to_odata,
)
from stac_fastapi.api.models import GeoJSONResponse
from stac_pydantic import Collection, Item, ItemCollection

logger = Logging.default(__name__)
router = APIRouter(tags=prip_tags)
PRIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config"


def validate(queryables: dict):
    """Function used to verify / update PRIP-specific queryables before being sent to eodag."""
    if "PublicationDate" in queryables:
        queryables["PublicationDate"] = validate_inputs_format(queryables["PublicationDate"])

    return queryables


class MockPgstacPrip(MockPgstac):
    """PRIP implementation of MockPgstac"""

    def __init__(self, request: Request | None = None, readwrite: Literal["r", "w"] | None = None):
        super().__init__(
            request=request,
            readwrite=readwrite,
            service="prip",
            all_collections=lambda: read_conf()["collections"],
            select_config=select_config,
            stac_to_odata=stac_to_odata,
            map_mission=prip_map_mission,
            temporal_mapping={
                "start_datetime": "ContentDate/Start",
                "end_datetime": "ContentDate/End",
            },
        )
        self.sortby = "-created"

    def process_search(self, station, odata_params, collection_provider, limit, page) -> ItemCollection:
        raise NotImplementedError("PRIP search not implemented yet.")


def auth_validation(request: Request, collection_id: str, access_type: str):
    """
    Check if the user KeyCloak roles contain the right for this specific PRIP collection and access type.

    Args:
        collection_id (str): Used to find the PRIP station ("ADGS1, ADGS2")
                            from the RSPY_PRIP_SEARCH_CONFIG config yaml file.
        access_type (str): The type of access, such as "download" or "read".
    """

    # Find the collection which id == the input collection_id
    collection = select_config(collection_id)
    if not collection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown PRIP collection: {collection_id!r}")
    station = collection["station"]

    # Call the authentication function from the authentication module
    authentication.auth_validation("prip", access_type, request=request, station=station)


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


@router.get("/prip/collections")
@handle_exceptions
async def get_allowed_prip_collections(request: Request):
    """Return the PRIP collections to which the user has access to."""
    logger.info(f"Starting {request.url.path}")
    authentication.auth_validation("prip", "landing_page", request=request)
    return await request.app.state.pgstac_client.all_collections(request=request)


@router.get("/prip/collections/{collection_id}")
@handle_exceptions
async def get_prip_collection(
    request: Request,
    collection_id: str,
) -> list[dict] | dict | Collection:
    """Return a specific PRIP collection."""
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
        properties={"datetime": "2025-08-01T00:00:00Z", "platform": "S1A", "instrument": "SAR"},
        collection=collection_id,
        assets={
            "product": {
                "href": "http://127.0.0.1:5000/Products(123)/$value",
                "type": "application/zip",
                "roles": ["data", "metadata"],
            },
        },
        links=[],
    )
    return {"type": "FeatureCollection", "features": [item.dict(by_alias=True)]}
