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
from typing import Annotated, Any, List, Union

import requests
import sqlalchemy
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Query, Request, status
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_cadip.cadip_retriever import init_cadip_provider
from rs_server_cadip.cadip_utils import (
    CADIP_CONFIG,
    from_session_expand_to_assets_serializer,
    from_session_expand_to_dag_serializer,
    select_config,
    validate_products,
)
from rs_server_common.authentication import apikey_validator
from rs_server_common.data_retrieval.provider import CreateProviderFailed, TimeRange
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    create_collection,
    create_stac_collection,
    sort_feature_collection,
    validate_inputs_format,
    write_search_products_to_db,
)

router = APIRouter(tags=cadip_tags)
logger = Logging.default(__name__)


def create_session_search_params(selected_config: Union[dict[Any, Any], None]) -> dict[Any, Any]:
    """Used to create and map query values with default values."""
    required_keys = ["station", "SessionId", "Satellite", "PublicationDate", "top", "orderby"]
    default_values = ["cadip", None, None, None, None, None, "-datetime"]
    if not selected_config:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cannot find a valid configuration")
    return {key: selected_config["query"].get(key, default) for key, default in zip(required_keys, default_values)}


@router.get("/cadip/search")
@apikey_validator(station="cadip", access_type="read")
def search_cadip_endpoint(request: Request):
    """Endpoint used to search cadip collections."""
    query_params = dict(request.query_params)
    collection = query_params.pop("collection", None)
    selected_config = select_config(collection)
    if selected_config:
        # Update selected_config query values with the ones coming in request.query_params
        for query_config_key in query_params:
            selected_config["query"][query_config_key] = query_params[query_config_key]

    query_params = create_session_search_params(selected_config)

    return process_session_search(
        request,
        query_params["station"],
        query_params["SessionId"],
        query_params["Satellite"],
        query_params["PublicationDate"],
        query_params["top"],
        "collection"
    )


@router.get("/cadip/collections/{collection_id}")
@apikey_validator(station="cadip", access_type="read")
def get_cadip_collection(request: Request, collection_id: str) -> list[dict] | dict:
    """
    Endpoint that retrieves session data from an external CADIP server and formats it into a STAC-compliant Collection.

    This endpoint begins by reading configuration details from file described using RSPY_CADIP_SEARCH_CONFIG.
    Using this configuration, it sends a request to an external CADIP server to fetch information about available
    sessions. Upon receiving the session data, the endpoint processes and transforms the data into the STAC format.

    In the formatted STAC Collection response, each sessions name is included as a link within the `links` list.
    These links point to the session details and are structured according to the STAC specification.
    """
    selected_config = select_config(collection_id)

    query_params = create_session_search_params(selected_config)
    return process_session_search(
        request,
        query_params["station"],
        query_params["SessionId"],
        query_params["Satellite"],
        query_params["PublicationDate"],
        query_params["top"],
        "collection",
    )


@router.get("/cadip/collections/{collection_id}/items")
@apikey_validator(station="cadip", access_type="read")
def get_cadip_collection_items(request: Request, collection_id):
    """
     Endpoint that retrieves a list of sessions from any CADIP station and returns them as an ItemCollection.

    This endpoint begins by reading configuration details from file described using RSPY_CADIP_SEARCH_CONFIG,
    it sends a request to the specified CADIP station to retrieve session data. The response from the CADIP station is
    then mapped from the original OData format to the STAC (SpatioTemporal Asset Catalog) format,
    ensuring the data is structured according to industry standards.

     The final response is an ItemCollection, which contains detailed information about each requested session.
     However, the assets associated with each session are intentionally excluded from the response,
     focusing solely on the session metadata.
    """
    selected_config = select_config(collection_id)
    query_params = create_session_search_params(selected_config)

    return process_session_search(
        request,
        query_params["station"],
        query_params["SessionId"],
        query_params["Satellite"],
        query_params["PublicationDate"],
        query_params["top"],
        "items",
    )


@router.get("/cadip/collections/{collection_id}/items/{session_id}")
@apikey_validator(station="cadip", access_type="read")
def get_cadip_collection_item_details(request: Request, collection_id, session_id):
    """
    Endpoint that retrieves a specific item from an ItemCollection, providing detailed information about a particular
    session.

    This endpoint processes a request to fetch a specific session from a CADIP station. After retrieving the data,
    it maps the session information from the original OData format to the STAC (SpatioTemporal Asset Catalog) format.
    The response is an Item that includes comprehensive metadata about the requested session, along with detailed
    descriptions of all associated assets.

    Response fully describes the assets, ensuring that all relevant information about the session and its resources is
    available in the final output.
    """
    selected_config = select_config(collection_id)

    query_params = create_session_search_params(selected_config)
    result = process_session_search(
        request,
        query_params["station"],
        query_params["SessionId"],
        query_params["Satellite"],
        query_params["PublicationDate"],
        query_params["top"],
    )
    return next(
        (item for item in result["features"] if item["id"] == session_id),
        HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Session {session_id} not found."),
    )


def process_session_search(  # pylint: disable=too-many-arguments, too-many-locals
    request,
    station: str,
    id: str,
    satellite,
    interval,
    limit,
    add_assets: Union[bool, str] = True,
):
    """Function to process and to retrieve a list of sessions from any CADIP station.

    A valid session search request must contain at least a value for either *id*, *platform*, or a time interval
    (*start_date* and *stop_date* correctly defined).

    Args:
        request (Request): The request object (unused).
        station (str): CADIP station identifier (e.g., MTI, SGS, MPU, INU).
        id (str, optional): Session identifier(s), comma-separated. Defaults to None.
        satellite (str, optional): Satellite identifier(s), comma-separated. Defaults to None.
        interval (str, optional): Time interval in ISO 8601 format. Defaults to None.
        limit (int, optional): Maximum number of products to return. Defaults to 1000.
        add_assets (str | bool, optional): Used to set how item assets are formatted.

    Returns:
        dict (dict): A STAC Feature Collection of the sessions.

    Raises:
        HTTPException (fastapi.exceptions): If search parameters are missing.
        HTTPException (fastapi.exceptions): If there is a JSON mapping error.
        HTTPException (fastapi.exceptions): If there is a value error during mapping.
    """
    session_id: Union[List[str], str, None] = [sid.strip() for sid in id.split(",")] if (id and "," in id) else id
    platform: Union[List[str], None] = satellite.split(",") if satellite else None
    time_interval = validate_inputs_format(interval, raise_errors=False) if interval else (None, None)
    limit = limit if limit else 1000

    if not (session_id or platform or (time_interval[0] and time_interval[1])):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing search parameters")

    try:
        products = init_cadip_provider(f"{station}_session").search(
            TimeRange(*time_interval),
            id=session_id,  # pylint: disable=redefined-builtin
            platform=platform,
            sessions_search=True,
            items_per_page=limit,
        )
        products = validate_products(products)
        sessions_products = from_session_expand_to_dag_serializer(products)
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
            match add_assets:
                case "collection":
                    return create_collection(products)
                case "items":
                    return create_stac_collection(products, feature_template, stac_mapper)
                case True:
                    cadip_sessions_collection = create_stac_collection(products, feature_template, stac_mapper)
                    return from_session_expand_to_assets_serializer(
                        cadip_sessions_collection,
                        sessions_products,
                        expanded_session_mapper,
                        request,
                    )
                case "_":
                    return create_collection(products)
    # except [OSError, FileNotFoundError] as exception:
    #     return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Error: {exception}")
    except json.JSONDecodeError as exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"JSON Map Error: {exception}",
        ) from exception
    except ValueError as exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unable to map OData to STAC.",
        ) from exception


######################################
# DEPRECATED CODE, WILL BE REMOVED !!!
######################################
@router.get("/cadip/{station}/cadu/search")
@apikey_validator(station="cadip", access_type="read")
def search_products(  # pylint: disable=too-many-locals, too-many-arguments
    request: Request,  # pylint: disable=unused-argument
    datetime: Annotated[str, Query(description='Time interval e.g "2024-01-01T00:00:00Z/2024-01-02T23:59:59Z"')] = "",
    station: str = FPath(description="CADIP station identifier (MTI, SGS, MPU, INU, etc)"),
    session_id: Annotated[str, Query(description="Session from which file belong")] = "",
    limit: Annotated[int, Query(description="Maximum number of products to return")] = 1000,
    sortby: Annotated[str, Query(description="Sort by +/-fieldName (ascending/descending)")] = "-created",
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
    return process_files_search(datetime, station, session_id, limit, sortby, deprecated=True)


@router.get("/cadip/{station}/session")
@apikey_validator(station="cadip", access_type="read")
def search_session(
    request: Request,  # pylint: disable=unused-argument
    station: str = FPath(description="CADIP station identifier (MTI, SGS, MPU, INU, etc)"),
    id: Annotated[
        Union[str, None],
        Query(
            description='Session identifier eg: "S1A_20200105072204051312" or '
            '"S1A_20200105072204051312, S1A_20220715090550123456"',
        ),
    ] = None,
    platform: Annotated[Union[str, None], Query(description='Satellite identifier eg: "S1A" or "S1A, S1B"')] = None,
    start_date: Annotated[Union[str, None], Query(description='Start time e.g. "2024-01-01T00:00:00Z"')] = None,
    stop_date: Annotated[Union[str, None], Query(description='Stop time e.g. "2024-01-01T00:00:00Z"')] = None,
):  # pylint: disable=too-many-arguments, too-many-locals
    """Endpoint to retrieve a list of sessions from any CADIP station.

    A valid session search request must contain at least a value for either *id*, *platform*, or a time interval
    (*start_date* and *stop_date* correctly defined).

    Args:
        request (Request): The request object (unused).
        station (str): CADIP station identifier (e.g., MTI, SGS, MPU, INU).
        id (str, optional): Session identifier(s), comma-separated. Defaults to None.
        platform (str, optional): Satellite identifier(s), comma-separated. Defaults to None.
        start_date (str, optional): Start time in ISO 8601 format. Defaults to None.
        stop_date (str, optional): Stop time in ISO 8601 format. Defaults to None.

    Returns:
        dict (dict): A STAC Feature Collection of the sessions.

    Raises:
        HTTPException (fastapi.exceptions): If search parameters are missing.
        HTTPException (fastapi.exceptions): If there is a JSON mapping error.
        HTTPException (fastapi.exceptions): If there is a value error during mapping.
    """
    return process_session_search(request, station, id, platform, start_date, stop_date)  # type: ignore


def process_files_search(  # pylint: disable=too-many-locals
    datetime: str,
    station: str,
    session_id: str,
    limit=None,
    sortby=None,
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
    start_date, stop_date = validate_inputs_format(datetime)
    session: Union[List[str], str, None] = (
        ([sid.strip() for sid in session_id.split(",")] if session_id and "," in session_id else session_id)
        if session_id
        else None
    )
    if limit < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pagination cannot be less 0")
    # Init dataretriever / get products / return
    try:
        products = init_cadip_provider(station).search(
            TimeRange(start_date, stop_date),
            id=session,
            items_per_page=limit,
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
        return sort_feature_collection(cadip_item_collection, sortby)

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
