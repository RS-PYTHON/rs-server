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
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Literal

import requests
import stac_pydantic
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Request, status
from fastapi.responses import RedirectResponse
from rs_server_common.authentication import authentication
from rs_server_common.data_retrieval.provider import CreateProviderFailed
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
    check_bbox_input,
    create_stac_collection,
    handle_exceptions,
    split_multiple_values,
)
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    map_auxip_prip_mission,
    validate_inputs_format,
    validate_sort_input,
)
from rs_server_prip import prip_retriever, prip_tags
from rs_server_prip.prip_utils import (
    prepare_collection,
    prip_odata_to_stac_template,
    prip_stac_mapper,
    read_conf,
    select_config,
    serialize_prip_asset,
    stac_to_odata,
)
from stac_fastapi.api.models import GeoJSONResponse

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
            map_mission=map_auxip_prip_mission,
            temporal_mapping={
                "start_datetime": "ContentDate/Start",
                "end_datetime": "ContentDate/End",
            },
        )
        self.sortby = "-published"

    @handle_exceptions
    def process_search(
        self,
        station: str,
        odata_params: dict,
        collection_provider: Callable[[dict], str | None],
        limit: int,
        page: int,
    ) -> stac_pydantic.ItemCollection:
        """Search prip products for the given station and OData parameters."""
        # Update odata names that shadow eodag builtins (productype)

        odata_params["Name"] = names[0] if isinstance(names := odata_params.get("Name"), list) else names
        if product_type := odata_params.pop("productType", None):
            odata_params["attr_ptype"] = split_multiple_values(product_type)

        for key in ("platformSerialIdentifier", "platformShortName"):
            if value := odata_params.pop(key, None):
                odata_params[key] = split_multiple_values(value)

        return process_product_search(station, odata_params, collection_provider, limit, self.sortby, page)


def auth_validation(request: Request, collection_id: str, access_type: str):
    """
    Check if the user KeyCloak roles contain the right for this specific PRIP collection and access type.

    Args:
        collection_id (str): Used to find the PRIP station from the RSPY_PRIP_SEARCH_CONFIG config yaml file.
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
    """Redirect to the landing page."""
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
) -> list[dict] | dict | stac_pydantic.Collection:
    """Return a specific PRIP collection."""
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_collection(collection_id, request)


@router.get("/prip/collections/{collection_id}/items", response_class=GeoJSONResponse)
async def get_prip_collection_items(
    request: Request,
    collection_id: CollectionType,
    # stac search parameters
    bbox: BBoxType = None,
    datetime: DateTimeType = None,
    filter_: FilterType = None,
    filter_lang: FilterLangType = "cql2-text",
    sortby: SortByType = None,
    limit: LimitType = None,
    page: PageType = None,
) -> list[dict] | dict:
    """
    Retrieve a list of items from a specified PRIP collection.

    This endpoint returns a collection of items associated with the given PRIP
    collection ID. It utilizes the collection ID to validate access and fetches
    the items based on defined query parameters.

    Args:
        collection_id (str): PRIP collection ID. Must be a valid collection identifier
                             (e.g., 'ins_s1').
        bbox (BBoxType, optional): Bounding box filter as four or six numbers
            [west, south, east, north] or [west, south, minz, east, north, maxz].
            Defaults to None. If provided, items intersecting the bbox are returned.

        datetime (DateTimeType, optional): Temporal filter. Either a single RFC 3339
            timestamp/interval (e.g., "2024-01-01T00:00:00Z") or a closed/open interval
            (e.g., "2024-01-01T00:00:00Z/2024-01-31T23:59:59Z", "../2024-01-01T00:00:00Z").
            Defaults to None.

        filter_ (FilterType, optional): CQL2 filter expression (text or JSON depending
            on `filter_lang`). Defaults to None.

        filter_lang (FilterLangType, optional): CQL2 language for `filter_`. One of
            "cql2-text" or "cql2-json". Defaults to "cql2-text".

        sortby (SortByType, optional): Sort specification. Single field or list of fields
            with optional direction, e.g., {"field": "published", "direction": "desc"}.
            Defaults to None (implementation default ordering).

        limit (LimitType, optional): Page size (maximum number of items to return).
            Defaults to None (service default / configured max).

        page (PageType, optional): 1-based page index.
            Defaults to None (first page).
    Returns:
        list[dict]: A FeatureCollection of items belonging to the specified collection, or an
                    error message if the collection is not found.

    Raises:
        HTTPException: If the authentication fails, or if there are issues with the
                       collection ID provided.
    """
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.item_collection(
        collection_id,
        request,
        bbox=check_bbox_input(bbox),
        datetime=datetime,
        filter_expr=filter_,
        filter_lang=filter_lang,
        sortby=[sortby] if sortby else None,
        limit=limit,
        page=page,
    )


@router.get(path="/prip/collections/{collection_id}/items/{item_id}", response_class=GeoJSONResponse)
@handle_exceptions
async def get_prip_collection_specific_item(
    request: Request,
    collection_id: Annotated[str, FPath(title="PRIP{} collection ID.", description="E.G. ")],
    item_id: Annotated[
        str,
        FPath(
            title="PRIP Id",
            description="E.G. S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
        ),
    ],
) -> list[dict] | dict:
    """
    Retrieve a specific item from a specified PRIP collection.

    This endpoint fetches details of a specific item within the given PRIP collection
    by its unique item ID. It utilizes the provided collection ID and item ID to
    validate access and return item information.

    Args:
    - collection_id (str): PRIP collection ID. Must be a valid collection identifier
            (e.g., 'ins_s1').
    - item_id (str): PRIP item ID. Must be a valid item identifier
            (e.g., 'S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF').

    Returns:
    - dict: A JSON object containing details of the specified item, or an error
            message if the item is not found.

    Raises:
    - HTTPException: If the authentication fails, or if the specified item is
                    not found in the collection.

    Example:
    A successful response will return: \n
        {
            "id": "S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
            "type": "Feature",
            "properties": {
                ...  # Detailed properties of the item
            },
            "geometry": {
                ...  # Geometry details of the item
            },
            "links": [
                ...  # Links associated with the item
            ]
        }

    """
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")

    # Search all the collection items then search manually for the right one.
    # TODO: allow the search function to take the item ID instead.
    try:
        item = await request.app.state.pgstac_client.get_item(item_id, collection_id, request)
    except HTTPException:  # validation error, just forward it
        raise
    except Exception as exc:  # stac_fastapi.types.errors.NotFoundError
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"PRIP item {item_id!r} not found.",
        ) from exc
    return item


def process_product_search(  # pylint: disable=too-many-locals
    station: str,
    queryables: dict,
    collection_provider: Callable[[dict], str | None],
    limit: int,
    sortby: str,
    page: int = 1,
    **kwargs,
) -> stac_pydantic.ItemCollection:
    """
    Performs a search for products using the PRIP provider and generates a STAC Feature Collection from the products.

    Args:
        station (str): prip station identifier.
        queryables (dict): Query parameters for filtering results.
        collection_provider (Callable[[dict], str | None]): Function that determines STAC collection
                                                            for a given OData entity
        limit (int): Maximum number of products to return.
        sortby (str): Sorting field with +/- prefix for ascending/descending order.
        page (int, optional): Page number for pagination. Defaults to 1.
        **kwargs: Additional search parameters.

    Returns:
        stac_pydantic.ItemCollection: A STAC-compliant Feature Collection containing the search results.

    Raises:
        HTTPException: If the pagination limit is less than 1.
        HTTPException: If an invalid station identifier is provided (`CreateProviderFailed`).
        HTTPException: If there is a connection error with the station (`requests.exceptions.ConnectionError`).
        HTTPException: If there is a general failure during the process.
    """
    try:
        products = prip_retriever.init_prip_provider(station).search(
            **validate(queryables),
            items_per_page=limit,
            sort_by=validate_sort_input(sortby),
            page=page,
            **kwargs,
        )
        collection = create_stac_collection(
            products,
            prip_odata_to_stac_template(),
            prip_stac_mapper(),
            collection_provider,
        )

        # Attach PRIP assets/download links, contentType, rels, etc.
        return prepare_collection(serialize_prip_asset(collection, products))

    except CreateProviderFailed as exception:
        logger.error(f"Failed to create EODAG provider!\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bad station identifier: {exception}",
        ) from exception
    except requests.exceptions.ConnectionError as exception:
        logger.error("Failed to connect to station!")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Station PRIP connection error: {exception}",
        ) from exception
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(f"General failure! {exception}")
        if isinstance(exception, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"General failure: {exception}",
        ) from exception
