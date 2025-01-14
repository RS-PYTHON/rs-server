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

"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""

# pylint: disable=redefined-builtin
import json
import traceback
from typing import Annotated, List, Literal, Union

import requests
import sqlalchemy
import stac_pydantic
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import WrapValidator, validate_call
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_cadip.cadip_retriever import init_cadip_provider
from rs_server_cadip.cadip_utils import (
    CADIP_CONFIG,
    cadip_map_mission,
    link_assets_to_session,
    prepare_collection,
    read_conf,
    select_config,
    stac_to_odata,
    validate_products,
)
from rs_server_common.authentication import authentication
from rs_server_common.authentication.authentication import auth_validator
from rs_server_common.authentication.authentication_to_external import (
    set_eodag_auth_token,
)
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.stac_api_common import (
    CollectionType,
    DateTimeType,
    FilterLangType,
    FilterType,
    LimitType,
    MockPgstac,
    PageType,
    SortByType,
    create_stac_collection,
    handle_exceptions,
)
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    validate_inputs_format,
    validate_sort_input,
    validate_str_list,
    write_search_products_to_db,
)

# pylint: disable=duplicate-code # with adgs_search

router = APIRouter(tags=cadip_tags)
logger = Logging.default(__name__)

DEFAULT_FILES_LIMIT = 1000


class MockPgstacCadip(MockPgstac):
    """Cadip implementation of MockPgstac"""

    def __init__(self, request: Request | None = None, readwrite: Literal["r", "w"] | None = None):
        """Constructor"""
        super().__init__(
            request=request,
            readwrite=readwrite,
            service="cadip",
            all_collections=lambda: read_conf()["collections"],
            select_config=select_config,
            stac_to_odata=stac_to_odata,
            map_mission=cadip_map_mission,
        )

        # Default sortby value
        self.sortby = "-published"

    @handle_exceptions
    def process_search(
        self,
        collection: dict,
        odata_params: dict,
        limit: int,
        page: int,
    ) -> stac_pydantic.ItemCollection:
        """Do the search for the given collection and OData parameters."""
        session_data = process_session_search(
            self.request,
            collection.get("station", "cadip"),
            odata_params.get("SessionId", []),
            odata_params.get("Satellite", []),
            odata_params.get("PublicationDate"),
            odata_params.get("Retransfer"),
            self.sortby,
            limit,
            page,
        )
        if not session_data.features:
            # If there are no sessions, don't proceed to assets allocation
            return session_data

        # To be updated with proper ('')
        features_ids = ", ".join(feature.id for feature in session_data.features)

        assets: list[dict] = []
        page = 1
        while True:
            chunked_assets = process_files_search(
                collection.get("station", "cadip"),
                features_ids,
                map_to_session=True,
                page=page,
            )
            # Gather results into assets list for later allocation
            assets.extend(chunked_assets)

            if len(chunked_assets) < DEFAULT_FILES_LIMIT:
                # If assets are less than maximum limit, then session is complete.
                break
            # If assets are equal to maximum limit, then send another request for the next page
            page += 1

        with open(CADIP_CONFIG / "cadip_stac_mapper.json", encoding="utf-8") as mapper:
            return link_assets_to_session(session_data, assets, json.loads(mapper.read()))


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


@router.get("/", include_in_schema=False)
async def home():
    """Home endpoint. Redirect to the landing page."""
    return RedirectResponse("/cadip")


@router.get("/cadip")
async def get_root_catalog(request: Request):
    """
    Retrieve the RSPY CADIP Search catalog landing page.

    This endpoint generates a STAC (SpatioTemporal Asset Catalog) Catalog object that serves as the landing
    page for the RSPY CADIP service. The catalog includes basic metadata about the service and links to
    available collections.

    The resulting catalog contains:
    - `id`: A unique identifier for the catalog, generated as a UUID.
    - `description`: A brief description of the catalog.
    - `title`: The title of the catalog.
    - `stac_version`: The version of the STAC specification to which the catalog conforms.
    - `conformsTo`: A list of STAC and OGC API specifications that the catalog conforms to.
    - `links`: A link to the `/cadip/collections` endpoint where users can find available collections.

    The `stac_version` is set to "1.0.0", and the `conformsTo` field lists the relevant STAC and OGC API
    specifications that the catalog adheres to. A link to the collections endpoint is added to the catalog's
    `links` field, allowing users to discover available collections in the CADIP service.

    Parameters:
    - request: The HTTP request object which includes details about the incoming request.

    Returns:
    - dict: A dictionary representation of the STAC catalog, including metadata and links.
    """
    logger.info(f"Starting {request.url.path}")
    authentication.auth_validation("cadip", "landing_page", request=request)
    return await request.app.state.pgstac_client.landing_page(request=request)


@router.get("/cadip/conformance")
async def get_conformance(request: Request):
    """Return the STAC/OGC conformance classes implemented by this server."""
    authentication.auth_validation("cadip", "landing_page", request=request)
    return await request.app.state.pgstac_client.conformance()


@router.get("/cadip/collections")
@handle_exceptions
async def get_allowed_cadip_collections(request: Request):
    """
        Endpoint to retrieve an object containing collections and links that a user is authorized to
        access based on their API key.

    This endpoint reads the API key from the request to determine the roles associated with the user.
    Using these roles, it identifies the stations the user can access and filters the available collections
    accordingly. The endpoint then constructs a JSON, which includes links to the collections that match the allowed
    stations.

    - It begins by extracting roles from the `request.state.auth_roles` and derives the station names
      the user has access to.
    - Then, it filters the collections from the configuration to include only those belonging to the
      allowed stations.
    - For each filtered collection, a corresponding STAC collection is created with links to detailed
      session searches.

    The final response is a dictionary representation of the STAC catalog, which includes details about
    the collections the user is allowed to access.

    Returns:
        dict: Object containing an array of Collection objects in the Catalog, and Link relations.

    Raises:
        HTTPException: If there are issues with reading configurations or processing session searches.
    """
    logger.info(f"Starting {request.url.path}")
    authentication.auth_validation("cadip", "landing_page", request=request)
    return await request.app.state.pgstac_client.all_collections(request=request)


@router.get("/cadip/collections/{collection_id}")
@handle_exceptions
async def get_cadip_collection(
    request: Request,
    collection_id: Annotated[str, FPath(title="CADIP collection ID.", max_length=100, description="E.G. ins_s1")],
) -> list[dict] | dict | stac_pydantic.Collection:
    """
    Retrieve a STAC-Compliant Collection for a Specific CADIP Station.

    This endpoint fetches and returns session data from an external CADIP server, structured as a STAC-compliant
    Collection. By specifying a `collection_id`, the client can retrieve a collection of session metadata related to
    that CADIP station.

    ### Path Parameters:
    - `collection_id` (string): The unique identifier of the CADIP collection to retrieve.

    ### Response:
    The response is a STAC Collection object formatted as a dictionary, which contains links to session details.
    Each session is represented as a link inside the `links` array, following the STAC specification. These links point
     to the detailed metadata for each session.

    ### Key Operations:
    1. **Configuration Lookup**: Reads the relevant configuration from `RSPY_CADIP_SEARCH_CONFIG`.
    2. **CADIP Server Request**: Sends a request to the CADIP server to retrieve session data.
    3. **STAC Formatting**: Transforms the session data into a STAC Collection format.
    4. **Link Creation**: Adds links to session details in the response.

    ### Responses:
    - **200 OK**: Returns the STAC Collection containing links to session metadata. If multiple collections are
    available, returns a list of collections.
    - **422 Unprocessable Entity**: Returns an error if the STAC Collection cannot be created due to missing or invalid
    configuration details.

    ### Raises:
    - **HTTPException**:
      - **422 Unprocessable Entity**: If any configuration data is missing, invalid, or causes an error when creating
      the STAC Collection.

    This endpoint is secured by an API key validator, ensuring that only authorized users can retrieve data from the
    CADIP station.
    """
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.get_collection(collection_id, request)


@router.get("/cadip/collections/{collection_id}/items")
@handle_exceptions
async def get_cadip_collection_items(
    request: Request,
    collection_id: CollectionType,
    # stac search parameters
    datetime: DateTimeType = None,
    filter_: FilterType = None,
    filter_lang: FilterLangType = "cql2-text",
    sortby: SortByType = None,
    limit: LimitType = None,
    page: PageType = None,
):
    """
    Retrieve a List of items for a specific collection.

    This endpoint provides access to a list of sessions for a given collection from the CADIP station.
    By specifying the `collection_id` in the path, clients can retrieve session metadata in the form of a STAC
    (SpatioTemporal Asset Catalog) ItemCollection.

    ### Path Parameters:
    - `collection_id` (string): The unique identifier of the collection from which session data is being requested.

    ### Response:
    Returns a STAC ItemCollection containing metadata for each session in the specified collection.
    Each session is represented as a STAC Item, containing key information such as:
    - **Session metadata**: Information about the session's time, satellite, and session ID.

    ### Responses:
    - **200 OK**: If sessions are found, returns the ItemCollection in JSON format.
    - **404 Not Found**: If no matching sessions or collection is found.

    ### Errors:
    - **500 Internal Server Error**: If an error occurs in reading configurations, creating query parameters, or
    processing the session search.

    This endpoint is protected by an API key validator, ensuring appropriate access to the CADIP station.
    """
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    return await request.app.state.pgstac_client.item_collection(
        collection_id,
        request,
        datetime=datetime,
        filter=filter_,
        filter_lang=filter_lang,
        sortby=sortby,
        limit=limit,
        page=page,
    )


@router.get("/cadip/collections/{collection_id}/items/{session_id}")
@handle_exceptions
async def get_cadip_collection_item_details(
    request: Request,
    collection_id: Annotated[str, FPath(title="CADIP collection ID.", max_length=100, description="E.G. ins_s1")],
    session_id: Annotated[
        str,
        FPath(title="CADIP session ID.", max_length=100, description="E.G. S1A_20231120061537234567"),
    ],
):
    """
    Retrieve Detailed Information for a specific session in a collection.

    This endpoint fetches metadata and asset details for a specific session within a collection from the CADIP station.
    Clients can request session details by providing the `collection_id` and `session_id` as path parameters.
    The session data is retrieved and converted from the original OData format into the STAC format,
    which provides standardized metadata for spatiotemporal datasets.

    ### Path Parameters:
    - `collection_id` (string): The unique identifier of the collection from which the session is being retrieved.
    - `session_id` (string): The identifier of the specific session within the collection for which details are
    requested.

    ### Response:
    Returns a STAC Item containing metadata and asset details about the requested session, including:
    - **Session metadata**: Contains important temporal information (e.g., `datetime`, `start_datetime`, and
    `end_datetime`),
      the platform (`platform`), and session-specific details such as `cadip:id`, `cadip:num_channels`,
      `cadip:station_unit_id`, `cadip:antenna_id`, and more.
    - **Satellite information**: Includes satellite attributes such as `sat:absolute_orbit`, `cadip:acquisition_id`, and
    status fields like `cadip:antenna_status_ok`, `cadip:front_end_status_ok`, and `cadip:downlink_status_ok`.
    - **Assets**: A collection of asset objects associated with the session. Each asset contains:
      - A unique asset `href` (link) pointing to the asset resource.
      - Metadata such as `cadip:id`, `cadip:retransfer`, `cadip:block_number`, `cadip:channel`,
        `created`, `eviction_datetime`, and `file:size`.
      - Asset `roles`, indicating the type of resource (e.g., "cadu").
      - Asset title and name.

    ### Responses:
    - **200 OK**: If the session details are found, returns the STAC Item in JSON format.
    - **404 Not Found**: If the `session_id` is not found within the specified collection.

    The endpoint is protected by an API key validator, which requires appropriate access permissions.
    """
    logger.info(f"Starting {request.url.path}")
    auth_validation(request, collection_id, "read")
    request.state.session_id = session_id  # save for later
    try:
        item = await request.app.state.pgstac_client.get_item(session_id, collection_id, request)
    except HTTPException:  # validation error, just forward it
        raise
    except Exception as exc:  # stac_fastapi.types.errors.NotFoundError
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cadip session {session_id!r} not found.",
        ) from exc
    return item


@validate_call(config={"arbitrary_types_allowed": True})
def process_session_search(  # type: ignore # pylint: disable=too-many-arguments, too-many-locals, unused-argument
    request: Request,
    station: str,
    session_id: Annotated[Union[str, List[str]], WrapValidator(validate_str_list)],
    platform: Annotated[Union[str, List[str]], WrapValidator(validate_str_list)],
    datetime: Annotated[
        Union[str, None],
        WrapValidator(lambda interval, info, handler: validate_inputs_format(interval, raise_errors=True)),
    ],
    retransfer: Union[bool, None],
    sortby: str,
    limit: Annotated[
        Union[int, None],
        Query(gt=0, le=10000, default=1000, description="Pagination Limit"),
    ],
    page: Union[int, None] = 1,
) -> stac_pydantic.ItemCollection:
    """Function to process and to retrieve a list of sessions from any CADIP station.

    A valid session search request must contain at least a value for either *id*, *platform*, or a time interval
    (*start_date* and *stop_date* correctly defined).

    Args:
        request (Request): The request object (unused).
        station (str): CADIP station identifier (e.g., MTI, SGS, MPU, INU).
        session_id (str, optional): Session identifier(s), comma-separated. Defaults to None.
        platform (str, optional): Satellite identifier(s), comma-separated. Defaults to None.
        datetime (str, optional): Datetime in ISO 8601 format. Defaults to None. Can be fixed, closed/open interval.
        limit (int, optional): Maximum number of products to return. Beetween 0 and 10000, defaults to 1000.
        sortby (str): Sort by +/-fieldName (ascending/descending).
        page (int): Page number to be displayed, defaults to first one.
    Returns:
        dict (dict): A STAC Feature Collection of the sessions.

    Raises:
        HTTPException (fastapi.exceptions): If search parameters are missing.
        HTTPException (fastapi.exceptions): If there is a JSON mapping error.
        HTTPException (fastapi.exceptions): If there is a value error during mapping.
    """
    try:
        set_eodag_auth_token(f"{station.lower()}_session", "cadip")
        products = (init_cadip_provider(f"{station}_session")).search(
            datetime,
            id=session_id,  # pylint: disable=redefined-builtin
            platform=platform,
            retransfer=retransfer,
            sessions_search=True,
            items_per_page=limit,
            sort_by=validate_sort_input(sortby),
            page=page,
        )
        products = validate_products(products)
        feature_template_path = CADIP_CONFIG / "cadip_session_ODataToSTAC_template.json"
        stac_mapper_path = CADIP_CONFIG / "cadip_sessions_stac_mapper.json"
        expanded_session_mapper_path = CADIP_CONFIG / "cadip_stac_mapper.json"
        with (
            open(feature_template_path, encoding="utf-8") as template,
            open(stac_mapper_path, encoding="utf-8") as stac_map,
            open(expanded_session_mapper_path, encoding="utf-8") as expanded_session_mapper,
        ):
            feature_template = json.loads(template.read())
            stac_mapper = json.loads(stac_map.read())
            expanded_session_mapper = json.loads(expanded_session_mapper.read())
            collection = create_stac_collection(products, feature_template, stac_mapper)
            return prepare_collection(collection)

    except json.JSONDecodeError as exception:
        logger.error(exception)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"JSON Map Error: {exception}",
        ) from exception
    except ValueError as exception:
        logger.error(exception)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exception),
        ) from exception
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(f"General failure! {exception}")
        if isinstance(exception, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"General failure: {exception}",
        ) from exception


######################################
# DEPRECATED CODE, WILL BE REMOVED !!!
######################################
@router.get("/cadip/{station}/cadu/search", deprecated=True)
@auth_validator(station="cadip", access_type="read")
async def search_products(  # pylint: disable=too-many-locals, too-many-arguments
    request: Request,  # pylint: disable=unused-argument
    datetime: Annotated[str, Query(description='Time interval e.g "2024-01-01T00:00:00Z/2024-01-02T23:59:59Z"')] = "",
    station: str = FPath(description="CADIP station identifier (MTI, SGS, MPU, INU, etc)"),
    session_id: Annotated[str, Query(description="Session from which file belong")] = "",
    limit: Annotated[int, Query(description="Maximum number of products to return")] = 1000,
    sortby: Annotated[str, Query(description="Sort by +/-fieldName (ascending/descending)")] = "-datetime",
):  # -> list[dict] | dict:
    """Endpoint to retrieve a list of products from the CADU system for a specified station.
    This function validates the input 'datetime' format, performs a search for products using the CADIP provider,
    writes the search results to the database, and generates a STAC Feature Collection from the products.
    Args:
        request (Request): The request object (unused).
        datetime (str): Time interval in ISO 8601 format.
        station (str): CADIP station identifier (e.g., MTI, SGS, MPU, INU).
        session_id (str): Session from which file belong.
        limit (int, optional): Maximum number of products to return. Defaults to 1000.
        sortby (str, optional): Sort by +/-fieldName (ascending/descending). Defaults to "-datetime".
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
    return process_files_search(station, session_id, datetime, limit, sortby=sortby, deprecated=True)


def process_files_search(  # pylint: disable=too-many-locals
    station: str,
    session_id: str,
    datetime: Union[str, None] = None,
    limit: Union[int, None] = DEFAULT_FILES_LIMIT,
    **kwargs,
) -> list[dict] | dict:
    """Endpoint to retrieve a list of products from the CADU system for a specified station.
    This function validates the input 'datetime' format, performs a search for products using the CADIP provider,
    writes the search results to the database, and generates a STAC Feature Collection from the products.
    Args:
        request (Request): The request object (unused).
        datetime (str): Time interval in ISO 8601 format.
        station (str): CADIP station identifier (e.g., MTI, SGS, MPU, INU).
        session_id (str): Session from which file belong.
        limit (int, optional): Maximum number of products to return. Defaults to 1000.
        sortby (str, optional): Sort by +/-fieldName (ascending/descending). Defaults to "-datetime".
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
    if not (datetime or session_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing search parameters")
    session: Union[List[str], str, None] = (
        ([sid.strip() for sid in session_id.split(",")] if session_id and "," in session_id else session_id)
        if session_id
        else None
    )
    if limit < 1:  # type: ignore
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pagination cannot be less 0")
    # Init dataretriever / get products / return
    try:
        set_eodag_auth_token(station.lower(), "cadip")
        products = (init_cadip_provider(station)).search(
            validate_inputs_format(datetime),
            id=session,
            items_per_page=limit,
            sort_by=validate_sort_input(sortby) if (sortby := kwargs.get("sortby")) else None,
            page=kwargs.get("page", 1),
        )
        if kwargs.get("deprecated", False):
            write_search_products_to_db(CadipDownloadStatus, products)
        feature_template_path = CADIP_CONFIG / "ODataToSTAC_template.json"
        stac_mapper_path = CADIP_CONFIG / "cadip_stac_mapper.json"
        with (
            open(feature_template_path, encoding="utf-8") as template,
            open(stac_mapper_path, encoding="utf-8") as stac_map,
        ):
            feature_template = json.loads(template.read())
            stac_mapper = json.loads(stac_map.read())
            cadip_item_collection = create_stac_collection(products, feature_template, stac_mapper)
        logger.info("Succesfully listed and processed products from CADIP station")
        if kwargs.get("map_to_session", False):
            return [product.properties for product in products]
        return cadip_item_collection.model_dump()
    # pylint: disable=duplicate-code
    except CreateProviderFailed as exception:
        logger.error(f"Failed to create EODAG provider!\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bad station identifier: {exception}",
        ) from exception
    # pylint: disable=duplicate-code
    except sqlalchemy.exc.OperationalError as exception:
        logger.error("Failed to connect to database!")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection error: {exception}",
        ) from exception
    except requests.exceptions.ConnectionError as exception:
        logger.error("Failed to connect to station!")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Station {station} connection error: {exception}",
        ) from exception
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error("General failure!")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"General failure: {exception}",
        ) from exception
