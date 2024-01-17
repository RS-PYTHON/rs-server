"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""
import traceback
from contextlib import contextmanager
from datetime import datetime
from typing import List

import sqlalchemy
from eodag import EOProduct
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from rs_server_cadip.cadip_retriever import init_cadip_data_retriever
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.utils.logging import Logging

from rs_server.CADIP.models.cadu_download_status import (
    CaduDownloadStatus,
    EDownloadStatus,
)
from rs_server.db.database import get_db

router = APIRouter(tags=["Cadu products"])
logger = Logging.default(__name__)


@router.get("/cadip/{station}/cadu/list")
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
        GET /cadip/station123/cadu/list?start_date="1999-01-01T12:00:00.000Z"&stop_date="2033-02-20T12:00:00.000Z"
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
    if (not is_valid_format(start_date)) or (not is_valid_format(stop_date)):
        logger.error("Invalid start/stop in endpoint call!")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content="Invalid request, invalid start/stop format",
        )

    # Init dataretriever / get products / return
    try:
        data_retriever = init_cadip_data_retriever(station, None, None, None)
        products = data_retriever.search(start_date, stop_date)
        processed_products = prepare_products(products)

        logger.info("Succesfully listed and processed products from cadu station")
        return JSONResponse(status_code=status.HTTP_200_OK, content={station: processed_products})

    except CreateProviderFailed as exception:
        logger.error(f"Failed to create EODAG provider!\n{traceback.format_exc()}")
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=f"Bad station identifier: {exception}")

    except sqlalchemy.exc.OperationalError as exception:
        logger.error(f"Failed to connect to database!\n{traceback.format_exc()}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=f"Database connection error: {exception}",
        )

    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(traceback.format_exc())
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=str(exception))


def prepare_products(products: list[EOProduct]) -> List[tuple[str, str]] | None:
    """Prepare a list of products by extracting their ID and Name properties.

    Parameters
    ----------
    products : list
        A list of product objects, each containing properties.

    Returns
    -------
    list
        A list of tuples, where each tuple contains the ID and Name of a product.
        If the input products is empty, an empty list is returned.

    Example
    -------
    >>> products = [
    ...     EOProduct(properties={"id": 1, "Name": "Product A"}),
    ...     EOProduct(properties={"id": 2, "Name": "Product B"}),
    ...     EOProduct(properties={"id": 3, "Name": "Product C"}),
    ... ]
    >>> prepare_products(products)
    [(1, 'Product A'), (2, 'Product B'), (3, 'Product C')]
    """
    # TODO, move all this logic to dataretriever.provider::search after db moved.
    jsonify_state_products = []
    with contextmanager(get_db)() as db:
        try:
            for product in products:
                jsonify_state_products.append((product.properties["id"], product.properties["Name"]))

                if CaduDownloadStatus.get_if_exists(db, product.properties["Name"]) is not None:
                    logger.info(
                        "Product %s is already registered in database, skipping",
                        product.properties["Name"],
                    )
                    continue

                CaduDownloadStatus.create(
                    db,
                    cadu_id=product.properties["id"],
                    name=product.properties["Name"],
                    available_at_station=datetime.fromisoformat(product.properties["startTimeFromAscendingNode"]),
                    status=EDownloadStatus.NOT_STARTED,
                )

        except sqlalchemy.exc.OperationalError:
            logger.error("Failed to connect with DB during listing procedure")
            raise
    return jsonify_state_products


def is_valid_format(date: str) -> bool:
    """Check if a string adheres to the expected date format "YYYY-MM-DDTHH:MM:SS.sssZ".

    Parameters
    ----------
    date : str
        The string to be validated for the specified date format.

    Returns
    -------
    bool
        True if the input string adheres to the expected date format, otherwise False.

    Example
    -------
    >>> is_valid_format("2023-01-01T12:00:00.000Z")
    True

    >>> is_valid_format("2023-01-01 12:00:00")
    False
    """
    try:
        datetime.strptime(date, "%Y-%m-%dT%H:%M:%S.%fZ")
        return True
    except ValueError:
        return False
