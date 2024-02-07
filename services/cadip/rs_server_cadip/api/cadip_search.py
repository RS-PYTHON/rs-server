"""Module for interacting with CADU system through a FastAPI APIRouter.

This module provides functionality to retrieve a list of products from the CADU system for a specified station.
It includes an API endpoint, utility functions, and initialization for accessing EODataAccessGateway.
"""
import json
import os.path as osp
import traceback
from pathlib import Path
from typing import Annotated

import sqlalchemy
from fastapi import APIRouter
from fastapi import Path as FPath
from fastapi import Query, status
from fastapi.responses import JSONResponse
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_download_status import CadipDownloadStatus
from rs_server_cadip.cadip_retriever import init_cadip_provider
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
async def list_cadip_handler(
    datetime: Annotated[str, Query(description="Time interval e.g. '2024-01-01T00:00:00Z/2024-01-02T23:59:59Z'")],
    station: str = FPath(description="CADIP station identifier (MTI, SGS, MPU, INU, etc)"),
    limit: Annotated[int, Query(description="Maximum number of products to return")] = 1000,
    sortby: Annotated[
        str,
        Query(
            description="Sorting criteria. +/-fieldName indicates ascending/descending order and field name. "
            "By default no sorting is applied.",
        ),
    ] = "+doNotSort",
) -> list[dict]:  # pylint: disable=too-many-locals
    """Endpoint to retrieve a list of products from the CADU system for a specified station.

    Notes:
        - The 'interval' parameter should be in ISO 8601 format.
        - The response includes a JSON representation of the list of products for the specified station.
        - In case of an invalid station identifier, a 400 Bad Request response is returned.
    \f
    Args:
        db (Database): The database connection object.

    Returns:
        JSONResponse: A JSON response containing the STAC Feature Collection or an error message.
        If the station identifier is invalid, a 400 Bad Request response is returned.
        If no products were found in the mentioned time range, output is an empty list.

    """
    start_date, stop_date = validate_inputs_format(datetime)
    if limit < 1:
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content="Pagination cannot be less 0")
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
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=sort_feature_collection(cadip_item_collection, sortby),
        )

    except CreateProviderFailed as exception:
        logger.error(f"Failed to create EODAG provider!\n{traceback.format_exc()}")
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=f"Bad station identifier: {exception}")

    except sqlalchemy.exc.OperationalError:
        logger.error("Failed to connect to database!")
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="Database connection error")
