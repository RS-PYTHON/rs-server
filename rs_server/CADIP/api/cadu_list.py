"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""
from datetime import datetime
from typing import List

from eodag import EOProduct
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from services.cadip.rs_server_cadip.cadip_retriever import init_cadip_data_retriever
from services.common.rs_server_common.data_retrieval.provider import (
    CreateProviderFailed,
)

router = APIRouter()


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
        A JSON response containing the list of products (ID, Name, PublicationDate) for the specified station.
        If the station identifier is invalid, a 400 Bad Request response is returned.
        If no products were found in the mentioned time range, output is an empty list.

    Example
    -------
    - Request:
        GET /cadip/station123/cadu/list?start_date="1999-01-01T12:00:00.000Z"&stop_date="2033-02-20T12:00:00.000Z"
    - Response:
        {
            "station123": [
                (1, 'Product A', 'YYYY-MM DDThh:mm:ss.sssZ'),
                (2, 'Product B', 'YYYY-MM DDThh:mm:ss.sssZ'),
                ...
            ]
        }

    Notes
    -----
    - If both start_date and stop_date are provided, products within the specified date range are retrieved.
    - The response includes a JSON representation of the list of products for the specified station.
    - In case of an invalid station identifier, a 400 Bad Request response is returned.
    """
    if is_valid_format(start_date) and is_valid_format(stop_date):
        # Init dataretriever / get products / return
        try:
            data_retriever = init_cadip_data_retriever(station, None, None, None)
            products = data_retriever.search(start_date, stop_date)
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={station: prepare_products(products)},
            )
        except CreateProviderFailed:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content="Bad station identifier",
            )
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content="Invalid request, invalid start/stop format",
    )


def prepare_products(products: list[EOProduct]) -> List[tuple[str, str]] | None:
    """Prepare a list of products by extracting their ID, Name and PublicationDate properties.

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
    ...     EOProduct(properties={"id": 1, "Name": "Product A", "startTimeFromAscendingNode": "2021-02-16T12:00:00.000Z"}),
    ...     EOProduct(properties={"id": 2, "Name": "Product B", "startTimeFromAscendingNode": "2021-02-16T12:00:00.000Z"}),
    ...     EOProduct(properties={"id": 3, "Name": "Product C", "startTimeFromAscendingNode": "2021-02-16T12:00:00.000Z"}),
    ... ]
    >>> prepare_products(products)
    [(1, 'Product A', 'YYYY-MM DDThh:mm:ss.sssZ'), (2, 'Product B', 'YYYY-MM DDThh:mm:ss.sssZ'), (3, 'Product C', 'YYYY-MM DDThh:mm:ss.sssZ')]
    """

    return (
        [
            (
                product.properties["id"],
                product.properties["Name"],
                product.properties["startTimeFromAscendingNode"],
            )
            for product in products
        ]
        if products
        else []
    )


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
