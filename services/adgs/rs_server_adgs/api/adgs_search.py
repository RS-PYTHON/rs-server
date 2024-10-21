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
import uuid
from pathlib import Path
from typing import Annotated, Any, List, Union

import requests
import stac_pydantic
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Request, status
from fastapi.responses import RedirectResponse
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_retriever import init_adgs_provider
from rs_server_adgs.adgs_utils import (
    auxip_map_mission,
    generate_adgs_queryables,
    get_adgs_queryables,
    read_conf,
    select_config,
    serialize_adgs_asset,
)
from rs_server_common.authentication import authentication
from rs_server_common.authentication.authentication import auth_validator
from rs_server_common.authentication.authentication_to_external import (
    set_eodag_auth_token,
)
from rs_server_common.data_retrieval.provider import CreateProviderFailed, TimeRange
from rs_server_common.stac_api_common import (
    Queryables,
    create_collection,
    create_links,
    create_stac_collection,
    filter_allowed_collections,
    handle_exceptions,
)
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import validate_inputs_format

logger = Logging.default(__name__)
router = APIRouter(tags=adgs_tags)
ADGS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config"


def create_auxip_product_search_params(
    selected_config: Union[dict[Any, Any], None],
) -> dict[Any, Any]:
    """Used to create and map query values with default values."""
    required_keys: List[str] = [
        "productType",
        "PublicationDate",
        "platformShortName",
        "top",
        "orderby",
    ]
    default_values: List[Union[str | None]] = [None, None, None, None, "-datetime"]
    if not selected_config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cannot find a valid configuration",
        )
    return {key: selected_config["query"].get(key, default) for key, default in zip(required_keys, default_values)}


## To be updated
def auth_validation(request: Request, collection_id: str, access_type: str):
    """
    Check if the user KeyCloak roles contain the right for this specific CADIP collection and access type.

    Args:
        collection_id (str): used to find the CADIP station ("CADIP", "INS", "MPS", "MTI", "NSG", "SGS")
        from the RSPY_CADIP_SEARCH_CONFIG config yaml file.
        access_type (str): The type of access, such as "download" or "read".
    """

    # Find the collection which id == the input collection_id
    collection = select_config(collection_id)
    if not collection:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown CADIP collection: {collection_id!r}")
    station = collection["station"]

    # Call the authentication function from the authentication module
    authentication.auth_validation("cadip", access_type, request=request, station=station)


###


@router.get("/", include_in_schema=False)
async def home_endpoint():
    """Redirect to the landing page."""
    return RedirectResponse("/auxip")


@router.get("/auxip")
@auth_validator(station="adgs", access_type="landing_page")
def get_root_catalog(request: Request):
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

    # Read landing page contents from json file
    with open(ADGS_CONFIG / "adgs_stac_landing_page.json", encoding="utf-8") as f:
        contents = json.load(f)

    # Override some fields
    links = contents["links"]
    domain = f"{request.url.scheme}://{request.url.netloc}"
    contents["id"] = str(uuid.uuid4())
    contents.update(**get_conformance())  # conformsTo
    for link in links:
        link["href"] = link["href"].format(domain=domain)

    # Add collections as child links
    all_collections = get_allowed_adgs_collections(request=request)  # warning: use kwargs here
    for collection in all_collections.get("collections", []):
        collection_id = collection["id"]
        links.append(
            {
                "rel": "child",
                "type": "application/json",
                "title": collection_id,
                "href": f"{domain}/auxip/collections/{collection_id}",
            },
        )

    # Convert to dict and build a Catalog object so we can validate the contents
    landing_page = stac_pydantic.Catalog.model_validate(contents)

    # Once validated, convert back to dict and return value
    return landing_page.model_dump()


@router.get("/auxip/conformance")
def get_conformance():
    """Return the STAC/OGC conformance classes implemented by this server."""
    with open(ADGS_CONFIG / "adgs_stac_conforms_to.json", encoding="utf-8") as f:
        return json.load(f)


@router.get("/auxip/collections")
@auth_validator(station="adgs", access_type="landing_page")
@handle_exceptions
def get_allowed_adgs_collections(request: Request):
    # Based on api key, get all station a user can access.
    logger.info(f"Starting {request.url.path}")

    configuration = read_conf()
    all_collections = configuration["collections"]

    return filter_allowed_collections(all_collections, "adgs", request)


@router.get("/auxip/queryables")
@auth_validator(station="adgs", access_type="landing_page")
def get_all_queryables(request: Request):
    logger.info(f"Starting {request.url.path}")
    return Queryables(
        type="object",
        title="Queryables for ADGS Search API",
        description="Queryable names for the ADGS Search API Item Search filter.",
        properties=get_adgs_queryables(),
    ).model_dump(by_alias=True)


@router.get("/auxip/search")
@auth_validator(station="adgs", access_type="landing_page")
@handle_exceptions
def search_auxip_endpoint(request: Request) -> dict:
    logger.info(f"Starting {request.url.path}")
    request_params = dict(request.query_params)
    if not set(request_params.keys()).issubset(set(get_adgs_queryables().keys())):
        raise HTTPException(status_code=422, detail="Given parameters are not queryables.")
    request_params["platformShortName"], request_params["platformSerialIdentifier"] = auxip_map_mission(
        request_params.pop("platform", None),
        request_params.pop("constellation", None),
    )
    return process_product_search(
        request,
        request_params.get("productType", None),
        request_params.get("PublicationDate", None),
        "items",
        request_params.get("top", None),
        attr_platform_short_name=request_params.get("platformShortName", None),
        attr_serial_identif=request_params.get("platformSerialIdentifier", None),
    )


@router.get("/auxip/collections/{collection_id}")
@handle_exceptions
def get_adgs_collection(
    request: Request,
    collection_id: Annotated[str, FPath(title="AUXIP{} collection ID.", max_length=100, description="E.G. ")],
) -> list[dict] | dict:
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    selected_config: Union[dict, None] = select_config(collection_id)

    logger.debug(f"User selected collection: {collection_id}")
    query_params: dict = create_auxip_product_search_params(selected_config)
    logger.debug(f"Collection search params: {query_params}")
    stac_collection: stac_pydantic.Collection = create_collection(selected_config)
    if links := process_product_search(
        request,
        query_params["productType"],
        query_params["PublicationDate"],
        "collection",
        query_params["top"],
    ):
        for link in links:
            stac_collection.links.append(link)
    return stac_collection.model_dump()


@router.get("/auxip/collections/{collection_id}/items")
@handle_exceptions
def get_adgs_collection_items(
    request: Request,
    collection_id: Annotated[str, FPath(title="AUXIP{} collection ID.", max_length=100, description="E.G. ")],
) -> list[dict] | dict:
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    selected_config: Union[dict, None] = select_config(collection_id)

    logger.debug(f"User selected collection: {collection_id}")
    query_params: dict = create_auxip_product_search_params(selected_config)
    logger.debug(f"Collection search params: {query_params}")
    return process_product_search(
        request,
        query_params["productType"],
        query_params["PublicationDate"],
        "items",
        query_params["top"],
    )


@router.get("/auxip/collections/{collection_id}/items/{item_id}")
@handle_exceptions
def get_adgs_collection_specific_item(
    request: Request,
    collection_id: Annotated[str, FPath(title="AUXIP{} collection ID.", max_length=100, description="E.G. ")],
    item_id: Annotated[
        str,
        FPath(
            title="AUXIP Id",
            max_length=100,
            description="E.G. S1A_OPER_MPL_ORBPRE_20210214T021411_20210221T021411_0001.EOF",
        ),
    ],
) -> list[dict] | dict:
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    selected_config: Union[dict, None] = select_config(collection_id)

    logger.debug(f"User selected collection: {collection_id}")
    query_params: dict = create_auxip_product_search_params(selected_config)
    logger.debug(f"Collection search params: {query_params}")
    item_collection = stac_pydantic.ItemCollection.model_validate(
        process_product_search(
            request,
            query_params["productType"],
            query_params["PublicationDate"],
            "items",
            query_params["top"],
            attr_platform_short_name=query_params.get("platformShortName", None),
            attr_serial_identif=query_params.get("platformSerialIdentifier", None),
        ),
    )
    return next(
        (item.to_dict() for item in item_collection.features if item.id == item_id),
        HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"AUXIP {item_id} not found."),  # type: ignore
    )


@router.get("/auxip/collections/{collection_id}/queryables")
def get_collection_queryables(
    request: Request,
    collection_id: Annotated[str, FPath(title="AUXIP collection ID.", max_length=100, description="E.G. ins_s1")],
):
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return Queryables(
        schema="https://json-schema.org/draft/2019-09/schema",
        id="https://stac-api.example.com/queryables",
        type="object",
        title="Queryables for CADIP Search API",
        description="Queryable names for the CADIP Search API Item Search filter.",
        properties=generate_adgs_queryables(collection_id),
    ).model_dump(by_alias=True)


def process_product_search(
    request,
    product_type,
    publication_date,
    selector,
    limit,
    **kwargs,
):  # pylint: disable=too-many-arguments, too-many-locals
    """
    This function validates the input 'datetime' format, performs a search for products using the ADGS provider,
    writes the search results to the database, and generates a STAC Feature Collection from the products.

    Args:
        request (Request): The request object (unused).
        datetime (str): Time interval in ISO 8601 format.
        limit (int, optional): Maximum number of products to return. Defaults to 1000.

    Returns:
        list[dict] | dict: A list of STAC Feature Collections or an error message.
                           If no products are found in the specified time range, returns an empty list.

    Raises:
        HTTPException (fastapi.exceptions): If the pagination limit is less than 1.
        HTTPException (fastapi.exceptions): If there is a bad station identifier (CreateProviderFailed).
        HTTPException (fastapi.exceptions): If there is a database connection error (sqlalchemy.exc.OperationalError).
        HTTPException (fastapi.exceptions): If there is a connection error to the station.
        HTTPException (fastapi.exceptions): If there is a general failure during the process.
    """
    set_eodag_auth_token("adgs", "auxip")
    limit = limit if limit else 1000
    if not (product_type or publication_date or kwargs):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing search parameters")
    (start_date, stop_date) = validate_inputs_format(publication_date) if publication_date else (None, None)
    try:
        products = init_adgs_provider("adgs").search(
            TimeRange(start_date, stop_date),
            attr_ptype=product_type,
            items_per_page=limit,
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
            match selector:
                case "collection":
                    return create_links(products, "ADGS")
                case "items":
                    collection = create_stac_collection(products, feature_template, stac_mapper)
                    return serialize_adgs_asset(collection, request).model_dump()
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
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"General failure: {exception}",
        ) from exception
