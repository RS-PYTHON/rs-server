"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""
import json
import os.path as osp
from datetime import datetime
from pathlib import Path
from typing import List

from eodag import EODataAccessGateway, EOProduct
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["cadu"])

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "CADIP" / "library"


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
    if not station_to_server_url(station):
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Bad station identifier")
    if is_valid_format(start_date) and is_valid_format(stop_date):
        # prepare start_stop
        dag_client = init_eodag(station)
        products, number = dag_client.search(start=start_date, end=stop_date, provider=station)
        return JSONResponse(status_code=status.HTTP_200_OK, content={station: prepare_products(products)})
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Invalid request, invalid start/stop format")


def station_to_server_url(station: str) -> str | None:
    """Retrieve the configuration data (webserver address) for a CADU station based on its identifier.

    Parameters
    ----------
    station : str
        Identifier for the CADU station.

    Returns
    -------
    str or None
        A str containing the webserver address for the specified station,
        or None if the station identifier is not found.

    Example
    -------
    >>> station_to_server_url("station123")
    'https://station123.example.com'

    Notes
    -----
    - The station identifier is case-insensitive and is converted to uppercase for matching.
    - The function reads the station configuration data from a JSON file.
    - If the station identifier is not found in the configuration data, the function returns None.
    """
    try:
        with open(CONF_FOLDER / "stations_cfg.json") as jfile:
            stations_data = json.load(jfile)
            return stations_data.get(station.upper(), None)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # logger to be added.
        raise FileNotFoundError(f"Error reading JSON file: {e}")


def init_eodag(station: str) -> EODataAccessGateway:
    """Initialize an instance of the EODataAccessGateway for a specified CADU station.

    Parameters
    ----------
    station : str
        Identifier for the CADU station.

    Returns
    -------
    EODataAccessGateway
        An instance of the EODataAccessGateway configured for the specified station.

    Example
    -------
    >>> cadu_instance = init_eodag("station123")
    >>> isinstance(cadu_instance, EODataAccessGateway)
    True

    Notes
    -----
    - The function initializes an EODataAccessGateway instance using a configuration file.
    - The CADU station is set as the preferred provider for the EODataAccessGateway.
    - The returned instance is ready to be used for searching and accessing Earth observation data.
    """
    config_file_path = CONF_FOLDER / "cadip_ws_config.yaml"
    eodag = EODataAccessGateway(config_file_path.as_posix())
    eodag.set_preferred_provider(station)
    return eodag


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
    return [(product.properties["id"], product.properties["Name"]) for product in products] if products else []


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
