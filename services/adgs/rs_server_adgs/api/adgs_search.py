"""Module for interacting with ADGS system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the ADGS stations.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""
import json
import os.path as osp
import traceback
from pathlib import Path
from typing import Annotated

import requests
import sqlalchemy
from fastapi import APIRouter, HTTPException, Query, Request, status
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_adgs.adgs_retriever import init_adgs_provider
from rs_server_common.authentication import apikey_validator
from rs_server_common.data_retrieval.provider import CreateProviderFailed, TimeRange
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    create_stac_collection,
    sort_feature_collection,
    validate_inputs_format,
    write_search_products_to_db,
)

logger = Logging.default(__name__)
router = APIRouter(tags=adgs_tags)
ADGS_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config"


@router.get("/adgs/aux/search")
# @apikey_validator(station="adgs",access_type="read")
def search_products(  # pylint: disable=too-many-locals
    request: Request,
    datetime: Annotated[str, Query(description="Time interval e.g. '2024-01-01T00:00:00Z/2024-01-02T23:59:59Z'")],
    limit: Annotated[int, Query(description="Maximum number of products to return")] = 1000,
    sortby: Annotated[str, Query(description="Sort by +/-fieldName (ascending/descending)")] = "-datetime",
) -> list[dict] | dict:
    """Endpoint to handle the search for products in the AUX station within a specified time interval.

    This function validates the input 'interval' format, performs a search for products using the ADGS provider,
    writes the search results to the database, and generates a STAC Feature Collection from the products.

    Note:
        - The 'interval' parameter should be in ISO 8601 format.
        - The function utilizes the ADGS provider for product search and EODAG for STAC Feature Collection creation.
        - Errors during the process will result in appropriate HTTP status codes and error messages.
    \f
    Args:
        db (Database): The database connection object.

    Returns:
        A list of (or a single) STAC Feature Collection or an error message.
        If no products were found in the mentioned time range, output is an empty list.

    """
    apikey_validator("adgs", "read", request)

    start_date, stop_date = validate_inputs_format(datetime)
    if limit < 1:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Pagination cannot be less 0")

    try:
        time_range = TimeRange(start_date, stop_date)
        products = init_adgs_provider("adgs").search(time_range, items_per_page=limit)
        write_search_products_to_db(AdgsDownloadStatus, products)
        feature_template_path = ADGS_CONFIG / "ODataToSTAC_template.json"
        stac_mapper_path = ADGS_CONFIG / "adgs_stac_mapper.json"
        with (
            open(feature_template_path, encoding="utf-8") as template,
            open(stac_mapper_path, encoding="utf-8") as stac_map,
        ):
            feature_template = json.loads(template.read())
            stac_mapper = json.loads(stac_map.read())
            adgs_item_collection = create_stac_collection(products, feature_template, stac_mapper)
        logger.info("Succesfully listed and processed products from AUX station")
        return sort_feature_collection(adgs_item_collection, sortby)

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
            detail=f"Station ADGS connection error: {exception}",
        ) from exception

    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error("General failure!")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exception,
        ) from exception
