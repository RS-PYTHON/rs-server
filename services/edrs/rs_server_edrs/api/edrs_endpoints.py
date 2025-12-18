# Copyright 2023-2025 Airbus, CS Group
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
FastAPI endpoints and helpers for the EDRS STAC view.
Implements landing, collections, and /items (no /search for EDRS).
"""

from typing import Annotated, Literal

import pystac
import stac_pydantic
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Request, status
from fastapi.encoders import ENCODERS_BY_TYPE, jsonable_encoder
from fastapi.responses import RedirectResponse
from rs_server_common.authentication import authentication
from rs_server_common.stac_api_common import (
    BBoxType,
    CollectionType,
    DateTimeType,
    FilterLangType,
    FilterType,
    LimitType,
    MockPgstac,
    PageType,
    SortByType,
    get_edrs_queryables,
    handle_exceptions,
)
from rs_server_common.utils.logging import Logging
from rs_server_edrs.edrs_connector import (
    EDRS_STATIONS_CONFIG,
    EDRSConnector,
    load_station_config,
)
from rs_server_edrs.edrs_utils import (
    build_edrs_item_collection,
    edrs_read_conf,
    edrs_select_config,
    filter_and_paginate_features,
    normalize_features,
)
from stac_fastapi.api.models import GeoJSONResponse

logger = Logging.default(__name__)
router = APIRouter()

ENCODERS_BY_TYPE.setdefault(pystac.ItemCollection, lambda obj: obj.to_dict())
ENCODERS_BY_TYPE.setdefault(pystac.Item, lambda obj: obj.to_dict())
ENCODERS_BY_TYPE.setdefault(pystac.Asset, lambda obj: obj.to_dict())
ENCODERS_BY_TYPE.setdefault(pystac.Link, lambda obj: obj.to_dict())


class MockPgstacEdrs(MockPgstac):
    """pgSTAC mock for EDRS (collections from YAML, no search support)."""

    def __init__(self, request: Request | None = None, readwrite: Literal["r", "w"] | None = None):
        super().__init__(
            request=request,
            readwrite=readwrite,
            service="edrs",
            all_collections=lambda: edrs_read_conf().get("collections", []),
            select_config=edrs_select_config,
            stac_to_odata=lambda d: d,
            map_mission=lambda *_: None,
        )
        self.sortby = "id"

    # pylint: disable-next=arguments-differ  # Base class expects more args; EDRS variant only uses request.
    def process_search(
        self,
        request: Request,
    ) -> dict:
        """Signal that the EDRS API has no /search endpoint."""
        raise HTTPException(status_code=404, detail="EDRS does not support /search. Use /edrs/collections/{id}/items.")

    async def get_items(self, collection_id: str, request) -> dict:
        """Return the STAC items synthesized for the requested collection."""
        cfg = edrs_select_config(collection_id)
        if not cfg:
            raise HTTPException(status_code=404, detail="Collection not found")

        center = cfg.get("station")
        satellites = [s.strip() for s in str(cfg.get("satellite", "")).split(",") if s.strip()]
        if not satellites:
            return {"type": "FeatureCollection", "features": []}

        params = load_station_config(EDRS_STATIONS_CONFIG, center)
        client = EDRSConnector(**params)
        client.connect()

        try:
            return build_edrs_item_collection(client, satellites, collection_id, request, center)
        finally:
            try:
                client.close()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Connector shutdown errors must be swallowed to avoid masking responses, so log and continue.
                logger.debug("Failed to close EDRS connector: %s", exc)  # nosec B110


def auth_validation(request: Request, collection_id: str, access_type: str):
    """Ensure the caller has the required EDRS permission for the station/collection."""

    # Find the collection which id == the input collection_id
    collection = edrs_select_config(collection_id)
    if not collection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown EDRS collection: {collection_id!r}")
    station = collection["station"]

    # Call the authentication function from the authentication module
    authentication.auth_validation("edrs", access_type, request=request, station=station)


@router.get("/", include_in_schema=False)
async def home():
    """Redirect the bare root to the /edrs catalog."""
    return RedirectResponse("/edrs")


@router.get("/edrs")
async def get_root_catalog(request: Request):
    """Return the landing-page document for the EDRS API (STAC landing page)."""
    logger.info("Starting %s", request.url.path)
    authentication.auth_validation("edrs", "landing_page", request=request)
    return await request.app.state.pgstac_client.landing_page(request=request)


@router.get("/edrs/collections")
async def get_allowed_edrs_collections(request: Request) -> dict:
    """List every EDRS collection the caller is allowed to view (via MockPgstacEdrs)."""
    logger.info("Starting %s", request.url.path)
    authentication.auth_validation("edrs", "landing_page", request=request)
    return await request.app.state.pgstac_client.all_collections(request=request)


@router.get("/edrs/collections/{collection_id}")
async def get_edrs_collection(
    request: Request,
    collection_id: Annotated[str, FPath(title="EDRS collection ID.", max_length=100, description="E.G. s1_pedc")],
) -> list[dict] | dict | stac_pydantic.Collection:
    """Return the metadata for a single EDRS-backed collection (YAML-defined)."""
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_collection(collection_id, request)


@router.get(
    path="/edrs/collections/{collection_id}/items",
    response_class=GeoJSONResponse,
    response_model=None,
)
@handle_exceptions
async def get_edrs_collection_items(
    request: Request,
    collection_id: CollectionType,
    bbox: BBoxType = None,  # pylint: disable=unused-argument  # Accepted for API parity even if unused here.
    datetime: DateTimeType = None,  # pylint: disable=unused-argument
    filter_: FilterType = None,  # pylint: disable=unused-argument
    filter_lang: FilterLangType = "cql2-text",  # pylint: disable=unused-argument
    sortby: SortByType = None,
    limit: LimitType = None,
    page: PageType = None,
) -> pystac.ItemCollection:
    """
    Filter, sort, and page STAC Items for the requested collection.
    Supports ids/props equality filters, datetime intervals, and pagination.
    """
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")

    item_collection: dict = await request.app.state.pgstac_client.get_items(collection_id, request)

    try:
        features_list = normalize_features(item_collection.get("features", []))
        filtered = filter_and_paginate_features(
            features_list,
            request.query_params,
            get_edrs_queryables(),
            sortby_default=str(sortby or "-datetime"),
            limit_default=int(limit or 1000),
            page_default=int(page or 1),
        )
        filtered_collection = filtered if isinstance(filtered, dict) else {"features": filtered}
        feature_collection = dict(item_collection)
        feature_collection["type"] = (
            filtered_collection.get("type") or feature_collection.get("type") or "FeatureCollection"
        )
        feature_collection["features"] = filtered_collection.get("features", [])
        for key, value in filtered_collection.items():
            if key not in {"type", "features"}:
                feature_collection[key] = value
        feature_collection = jsonable_encoder(feature_collection)
        return pystac.ItemCollection.from_dict(feature_collection, preserve_dict=False)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(path="/edrs/collections/{collection_id}/items/{item_id}", response_class=GeoJSONResponse)
@handle_exceptions
async def get_edrs_item(
    request: Request,
    collection_id: CollectionType,
    item_id: str,
) -> dict:
    """Return a single STAC Item identified by item_id within the collection."""
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")

    # Reuse the existing collection builder to guarantee identical STAC mapping
    item_collection = await request.app.state.pgstac_client.get_items(collection_id, request)
    features = item_collection.get("features", [])

    # Session IDs in items are stored without the "_dat" suffix
    wanted = item_id.removesuffix("_dat")
    feature = next((f for f in features if f.get("id") == wanted), None)

    if not feature:
        raise HTTPException(
            status_code=404,
            detail=f"Session '{item_id}' not found in collection '{collection_id}'",
        )

    # Return the single STAC Item (Feature)
    return feature
