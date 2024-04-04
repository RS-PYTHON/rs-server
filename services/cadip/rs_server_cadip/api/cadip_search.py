"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""

import json
import os.path as osp
import traceback
from pathlib import Path
from typing import Annotated

import requests
import sqlalchemy
from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Query, Request, status
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_cadip.cadip_retriever import init_cadip_provider
from rs_server_common.authentication import apikey_validator
from rs_server_common.data_retrieval.provider import CreateProviderFailed, TimeRange
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    create_stac_collection,
    sort_feature_collection,
    validate_inputs_format,
    write_search_products_to_db,
)

router = APIRouter(tags=cadip_tags)
logger = Logging.default(__name__)
CADIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config"


@router.get("/cadip/{station}/cadu/search")
@apikey_validator(station="cadip", access_type="read")
def search_products(  # pylint: disable=too-many-locals
    request: Request,  # pylint: disable=unused-argument
    datetime: Annotated[str, Query(description="Time interval e.g. '2024-01-01T00:00:00Z/2024-01-02T23:59:59Z'")],
    station: str = FPath(description="CADIP station identifier (MTI, SGS, MPU, INU, etc)"),
    limit: Annotated[int, Query(description="Maximum number of products to return")] = 1000,
    sortby: Annotated[str, Query(description="Sort by +/-fieldName (ascending/descending)")] = "-datetime",
) -> list[dict] | dict:
    """Endpoint to retrieve a list of products from the CADU system for a specified station.

    Notes:
        - The 'interval' parameter should be in ISO 8601 format.
        - The response includes a JSON representation of the list of products for the specified station.
        - In case of an invalid station identifier, a 400 Bad Request response is returned.
    \f
    Args:
        db (Database): The database connection object.

    Returns:
        A list of (or a single) STAC Feature Collection or an error message.
        If the station identifier is invalid, a 400 Bad Request response is returned.
        If no products were found in the mentioned time range, output is an empty list.

    """

    start_date, stop_date = validate_inputs_format(datetime)
    if limit < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pagination cannot be less 0")
    # Init dataretriever / get products / return
    try:
        products = init_cadip_provider(station).search(TimeRange(start_date, stop_date), items_per_page=limit)
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


@router.get("/cadip/{station}/session")
@apikey_validator(station="cadip", access_type="read")
def search_session(
    request: Request,  # pylint: disable=unused-argument
    station,
    id=None,  # pylint: disable=redefined-builtin
    platform=None,
    start_date=None,
    stop_date=None,
):  # pylint: disable=too-many-arguments
    """Endpoint to retrieve list of sessions from any CADIP station.

    Args:
        station (str): CADIP station identifier (MTI, SGS, MPU, INU, etc)
        id (str, list-like-str): Session identifier
            (eg: "S1A_20170501121534062343" or "S1A_20170501121534062343, S1A_20240328185208053186")
        platform (str, list-like-str): Satellite identifier
            (eg: "S1A" or "S1A, S1B")
        start_date (str): Start date of the time interval
        stop_date (str): Stop date of the time interval

    """
    # Tbd - change list split with typing
    id = id.split(",") if id else None
    platform = platform.split(",") if platform else None
    start_date, stop_date = (
        validate_inputs_format(f"{start_date}/{stop_date}") if start_date and stop_date else None
    ), None
    try:
        products = init_cadip_provider(f"{station}_session").search(
            TimeRange(start_date, stop_date),
            id=id,  # pylint: disable=redefined-builtin
            platform=platform,
        )
        feature_template_path = CADIP_CONFIG / "cadip_session_ODataToSTAC_template.json"
        stac_mapper_path = CADIP_CONFIG / "cadip_sessions_stac_mapper.json"
        with (
            open(feature_template_path, encoding="utf-8") as template,
            open(stac_mapper_path, encoding="utf-8") as stac_map,
        ):
            feature_template = json.loads(template.read())
            stac_mapper = json.loads(stac_map.read())
            cadip_sessions_collection = create_stac_collection(products, feature_template, stac_mapper)
            return cadip_sessions_collection
    except [OSError, FileNotFoundError] as exception:
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Error: {exception}")
    except json.JSONDecodeError as exception:
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"JSON Map Error: {exception}")
    except ValueError:
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unable to map OData to STAC.")
