"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""
import json
import os.path as osp
import traceback
from pathlib import Path

import sqlalchemy
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_retriever import init_cadip_provider
from rs_server_cadip.cadu_download_status import CaduDownloadStatus
from rs_server_common.data_retrieval.provider import CreateProviderFailed, TimeRange
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    create_stac_collection,
    validate_inputs_format,
    write_search_products_to_db,
)

router = APIRouter(tags=cadip_tags)
logger = Logging.default(__name__)
CADIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config"


@router.get("/cadip/{station}/cadu/search")
async def list_cadu_handler(station: str, interval: str):
    """Endpoint to retrieve a list of products from the CADU system for a specified station.

    Parameters
    ----------
    station : str
        Identifier for the CADIP station (MTI, SGS, MPU, INU, etc).
    start_date : str, optional
        Start date for time series filter (format: "YYYY-MM-DDThh:mm:sssZ").
    stop_date : str, optional
        Stop date for time series filter (format: "YYYY-MM-DDThh:mm:sssZ").

    Returns
    -------
    JSONResponse
        A JSON response containing the list of products (ID, Name) for the specified station.
        If the station identifier is invalid, a 400 Bad Request response is returned.
        If no products were found in the mentioned time range, output is an empty list.

    Example
    -------
    - Request:
        GET /cadip/station123/cadu/search?start_date="1999-01-01T12:00:00.000Z"&stop_date="2033-02-20T12:00:00.000Z"
    - Response:
        {
            "station123": [
                (1, 'Product A'),
                (2, 'Product B'),
                ...
            ]
        }

    Notes
    -----
    - If both start_date and stop_date are provided, products within the specified date range are retrieved.
    - The response includes a JSON representation of the list of products for the specified station.
    - In case of an invalid station identifier, a 400 Bad Request response is returned.
    """
    start_date, stop_date, err_code, err_text = validate_inputs_format(interval)
    if err_code and err_text:
        return JSONResponse(status_code=err_code, content=err_text)

    # Init dataretriever / get products / return
    try:
        products = init_cadip_provider(station).search(TimeRange(start_date, stop_date))
        write_search_products_to_db(CaduDownloadStatus, products)
        feature_template_path = CADIP_CONFIG / "ODataToSTAC_template.json"
        stac_mapper_path = CADIP_CONFIG / "cadip_stac_mapper.json"
        with (
            open(feature_template_path, encoding="utf-8") as template,
            open(stac_mapper_path, encoding="utf-8") as stac_map,
        ):
            feature_template = json.loads(template.read())
            stac_mapper = json.loads(stac_map.read())
            stac_feature_collection = create_stac_collection(products, feature_template, stac_mapper)
        logger.info("Succesfully listed and processed products from cadu station")
        return JSONResponse(status_code=status.HTTP_200_OK, content=stac_feature_collection)

    except CreateProviderFailed as exception:
        logger.error(f"Failed to create EODAG provider!\n{traceback.format_exc()}")
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=f"Bad station identifier: {exception}")

    except sqlalchemy.exc.OperationalError:
        logger.error("Failed to connect to database!")
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="Database connection error")
