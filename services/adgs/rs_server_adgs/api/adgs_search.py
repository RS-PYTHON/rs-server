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

"""Module for interacting with ADGS system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the ADGS stations.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""

import json
import os.path as osp
import traceback
from pathlib import Path
from typing import Annotated, Literal

import requests
import stac_pydantic
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Request, status
from fastapi.responses import RedirectResponse
from rs_server_adgs import adgs_retriever, adgs_tags
from rs_server_adgs.adgs_utils import (
    auxip_map_mission,
    prepare_collection,
    read_conf,
    select_config,
    serialize_adgs_asset,
    stac_to_odata,
)
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
)
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import validate_inputs_format, validate_sort_input
from stac_fastapi.api.models import GeoJSONResponse

# pylint: disable=duplicate-code # with cadip_search

logger = Logging.default(__name__)
router = APIRouter(tags=adgs_tags)
ADGS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config"


def validate(queryables: dict):
    """Function used to verify / update ADGS-specific queryables before being sent to eodag."""
    if "PublicationDate" in queryables:
        queryables["PublicationDate"] = validate_inputs_format(queryables["PublicationDate"])

    return queryables


class MockPgstacAdgs(MockPgstac):
    """Adgs implementation of MockPgstac"""

    def __init__(self, request: Request | None = None, readwrite: Literal["r", "w"] | None = None):
        """Constructor"""
        super().__init__(
            request=request,
            readwrite=readwrite,
            service="adgs",
            all_collections=lambda: read_conf()["collections"],
            select_config=select_config,
            stac_to_odata=stac_to_odata,
            map_mission=auxip_map_mission,
            temporal_mapping={"start_datetime": "ContentDate/Start", "end_datetime": "ContentDate/End"},
        )

        # Default sortby value
        self.sortby = "-created"

    @handle_exceptions
    def process_search(
        self,
        collection: dict,
        odata_params: dict,
        limit: int,
        page: int,
    ) -> stac_pydantic.ItemCollection:
        """Search adgs products for the given collection and OData parameters."""
        # Update odata names that shadow eodag builtins (productype)

        odata_params["Name"] = names[0] if isinstance(names := odata_params.get("Name"), list) else names
        odata_params["attr_ptype"] = odata_params.pop("productType", None)

        return process_product_search(
            collection.get("station", "adgs"),
            odata_params,
            limit,
            self.sortby,
            page,
        )


def auth_validation(request: Request, collection_id: str, access_type: str):
    """
    Check if the user KeyCloak roles contain the right for this specific AUXIP collection and access type.

    Args:
        collection_id (str): Used to find the AUXIP station ("ADGS1, ADGS2")
                            from the RSPY_ADGS_SEARCH_CONFIG config yaml file.
        access_type (str): The type of access, such as "download" or "read".
    """

    # Find the collection which id == the input collection_id
    collection = select_config(collection_id)
    if not collection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown AUXIP collection: {collection_id!r}")
    station = collection["station"]

    # Call the authentication function from the authentication module
    authentication.auth_validation("adgs", access_type, request=request, station=station)


@router.get("/", include_in_schema=False)
async def home_endpoint():
    """Redirect to the landing page."""
    return RedirectResponse("/auxip")


@router.get("/auxip")
async def get_root_catalog(request: Request):
    """
    Retrieve the RSPY ADGS Search catalog landing page.

    This endpoint generates a STAC (SpatioTemporal Asset Catalog) Catalog object that serves as the landing
    page for the RSPY ADGS service. The catalog includes basic metadata about the service and links to
    available collections.

    The resulting catalog contains:
    - `id`: A unique identifier for the catalog, generated as a UUID.
    - `description`: A brief description of the catalog.
    - `title`: The title of the catalog.
    - `stac_version`: The version of the STAC specification to which the catalog conforms.
    - `conformsTo`: A list of STAC and OGC API specifications that the catalog conforms to.
    - `links`: A link to the `/adgs/collections` endpoint where users can find available collections.

    The `stac_version` is set to "1.0.0", and the `conformsTo` field lists the relevant STAC and OGC API
    specifications that the catalog adheres to. A link to the collections endpoint is added to the catalog's
    `links` field, allowing users to discover available collections in the ADGS service.

    Parameters:
    - request: The HTTP request object which includes details about the incoming request.

    Returns:
    - dict: A dictionary representation of the STAC catalog, including metadata and links.
    """
    logger.info(f"Starting {request.url.path}")
    authentication.auth_validation("adgs", "landing_page", request=request)
    return await request.app.state.pgstac_client.landing_page(request=request)


@router.get("/auxip/conformance")
async def get_conformance(request: Request):
    """Return the STAC/OGC conformance classes implemented by this server."""
    authentication.auth_validation("adgs", "landing_page", request=request)
    return await request.app.state.pgstac_client.conformance()


@router.get("/auxip/collections")
@handle_exceptions
async def get_allowed_adgs_collections(request: Request):
    """Return the ADGS collections to which the user has access to."""
    logger.info(f"Starting {request.url.path}")
    authentication.auth_validation("adgs", "landing_page", request=request)
    return await request.app.state.pgstac_client.all_collections(request=request)


@router.get("/auxip/collections/{collection_id}")
@handle_exceptions
async def get_adgs_collection(
    request: Request,
    collection_id: Annotated[str, FPath(title="AUXIP{} collection ID.", description="E.G. ")],
) -> list[dict] | dict | stac_pydantic.Collection:
    """Return a specific ADGS collection."""
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_collection(collection_id, request)


@router.get(path="/auxip/collections/{collection_id}/items", response_class=GeoJSONResponse)
@handle_exceptions
async def get_adgs_collection_items(
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
    Retrieve a list of items from a specified AUXIP collection.

    This endpoint returns a collection of items associated with the given AUXIP
    collection ID. It utilizes the collection ID to validate access and fetches
    the items based on defined query parameters.

    Args:
        collection_id (str): AUXIP collection ID. Must be a valid collection identifier
                             (e.g., 'ins_s1').

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


@router.get(path="/auxip/collections/{collection_id}/items/{item_id}", response_class=GeoJSONResponse)
@handle_exceptions
async def get_adgs_collection_specific_item(
    request: Request,
    collection_id: Annotated[str, FPath(title="AUXIP{} collection ID.", description="E.G. ")],
    item_id: Annotated[
        str,
        FPath(
            title="AUXIP Id",
            description="E.G. S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
        ),
    ],
) -> list[dict] | dict:
    """
    Retrieve a specific item from a specified AUXIP collection.

    This endpoint fetches details of a specific item within the given AUXIP collection
    by its unique item ID. It utilizes the provided collection ID and item ID to
    validate access and return item information.

    Args:
    - collection_id (str): AUXIP collection ID. Must be a valid collection identifier
            (e.g., 'ins_s1').
    - item_id (str): AUXIP item ID. Must be a valid item identifier
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
            detail=f"AUXIP item {item_id!r} not found.",
        ) from exc
    return item


def process_product_search(  # pylint: disable=too-many-locals
    station,
    queryables,
    limit,
    sortby,
    page: int = 1,
    **kwargs,
) -> stac_pydantic.ItemCollection:
    """
    Performs a search for products using the ADGS provider and generates a STAC Feature Collection from the products.

    Args:
        station (str): Auxip station identifier.
        queryables (dict): Query parameters for filtering results.
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
        products = adgs_retriever.init_adgs_provider(station).search(
            **validate(queryables),
            items_per_page=limit,
            sort_by=validate_sort_input(sortby),
            page=page,
            **kwargs,
        )
        feature_template_path = ADGS_CONFIG / "ODataToSTAC_template.json"
        stac_mapper_path = ADGS_CONFIG / "adgs_stac_mapper.json"
        with (
            open(feature_template_path, encoding="utf-8") as template,
            open(stac_mapper_path, encoding="utf-8") as stac_map,
        ):
            feature_template = json.loads(template.read())
            stac_mapper = json.loads(stac_map.read())
            collection = create_stac_collection(products, feature_template, stac_mapper)
            return prepare_collection(serialize_adgs_asset(collection, products))
    # pylint: disable=duplicate-code
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
            detail=f"Station ADGS connection error: {exception}",
        ) from exception

    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(f"General failure! {exception}")
        if isinstance(exception, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"General failure: {exception}",
        ) from exception
