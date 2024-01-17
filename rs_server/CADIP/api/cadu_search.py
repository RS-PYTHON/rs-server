"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""
import sqlalchemy
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from rs_server_common.utils.logging import Logging

from rs_server.api_common.utils import (
    validate_inputs_format,
    write_search_products_to_db,
)
from services.cadip.rs_server_cadip.cadip_retriever import init_cadip_data_retriever
from services.cadip.rs_server_cadip.cadu_download_status import CaduDownloadStatus
from services.common.rs_server_common.data_retrieval.provider import (
    CreateProviderFailed,
)

router = APIRouter(tags=["Cadu products"])
logger = Logging.default(__name__)


@router.get("/cadip/{station}/cadu/search")
async def list_cadu_handler(station: str, start_date: str, stop_date: str):
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
    is_valid, exception = validate_inputs_format(start_date, stop_date)
    if not is_valid:
        return exception

    # Init dataretriever / get products / return
    try:
        data_retriever = init_cadip_data_retriever(station, None, None, None)
        products = data_retriever.search(start_date, stop_date)
        processed_products = prepare_products(products)

        logger.info("Succesfully listed and processed products from cadu station")
        return JSONResponse(status_code=status.HTTP_200_OK, content={station: processed_products})

    except CreateProviderFailed:
        logger.error("Failed to create EODAG provider!")
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Bad station identifier")

    except sqlalchemy.exc.OperationalError:
        logger.error("Failed to connect to database!")
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="Database connection error")


def prepare_products(products):
    try:
        output = write_search_products_to_db(CaduDownloadStatus, products)
    except Exception:
        return []
    return output
