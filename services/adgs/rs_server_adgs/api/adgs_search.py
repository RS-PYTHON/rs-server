"""Docstring will be here."""
import json
import os.path as osp
from pathlib import Path

import sqlalchemy
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_adgs.adgs_retriever import init_adgs_provider
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
async def search_aux_handler(
    datetime: str,
    limit: int = 1000,
    sortby: str = "+doNotSort",
):  # pylint: disable=too-many-locals
    """Endpoint to handle the search for products in the AUX station within a specified time interval.

    This function validates the input 'interval' format, performs a search for products using the ADGS provider,
    writes the search results to the database, and generates a STAC Feature Collection from the products.

    Args:
        datetime (str): A string representing the time interval (e.g., "2024-01-01T00:00:00Z/2024-01-02T23:59:59Z").
        limit (int): Maximum number of products to return.
        sortby (str): Sorting criteria. +/-fieldName indicates ascending/descending order and field name. Default no
        sorting is applied.

    Returns:
        JSONResponse: A JSON response containing the STAC Feature Collection or an error message.

    Raises:
        JSONResponse: If there is an error in validating the input interval format or connecting to the database.

    Example:
        >>> response = await search_aux_handler("2022-01-01T00:00:00/2022-01-02T00:00:00")
        >>> print(response)
        {"status_code": 200, "content": {"type": "FeatureCollection", "features": [...]}}

    Note:
        - The 'interval' parameter should be in ISO 8601 format.
        - The function utilizes the ADGS provider for product search and EODAG for STAC Feature Collection creation.
        - Errors during the process will result in appropriate HTTP status codes and error messages.

    """

    start_date, stop_date = validate_inputs_format(datetime)
    if limit < 1:
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content="Pagination cannot be less 0")

    try:
        time_range = TimeRange(start_date, stop_date)
        products = init_adgs_provider("ADGS").search(time_range, items_per_page=limit)
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
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=sort_feature_collection(adgs_item_collection, sortby),
        )
    except CreateProviderFailed:
        logger.error("Failed to create EODAG provider!")
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Bad station identifier")
    except sqlalchemy.exc.OperationalError:
        logger.error("Failed to connect to database!")
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="Database connection error")
