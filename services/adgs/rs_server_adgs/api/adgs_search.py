"""Docstring will be here."""
import json
import os.path as osp
from datetime import datetime
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
    validate_inputs_format,
    write_search_products_to_db,
)

logger = Logging.default(__name__)
router = APIRouter(tags=adgs_tags)
CADIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config"


@router.get("/adgs/aux/search")
async def search_aux_handler(interval: str):
    """
    Searches for AUX products within a specified date range.

    This endpoint initiates a search for AUX products between the given start and stop dates.

    @param start_date: The start date of the search range.
    @param stop_date: The stop date of the search range.

    - Validates the input date formats, and if invalid, returns an appropriate JSONResponse.
    - Initializes the ADGS data retriever.
    - Performs a search for products within the specified date range.
    - Processes the retrieved products using 'prepare_products' function.
    - Logs a success message if the listing and processing of products are successful.

    @return: A JSONResponse with the search results. In case of errors:
             - Returns a 400 Bad Request response if there is an issue creating the EODAG provider.
             - Returns a 503 Service Unavailable response if there is an operational error connecting to the database.
    """
    try:
        start_date, stop_date = interval.split("/")
    except ValueError:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content="Missing start/stop",
        )
    is_valid, exception = validate_inputs_format(start_date, stop_date)
    if not is_valid:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=f"Invalid start/stop format, {exception}")

    try:
        time_range = TimeRange(datetime.fromisoformat(start_date), datetime.fromisoformat(stop_date))
        products = init_adgs_provider("ADGS").search(time_range)
        write_search_products_to_db(AdgsDownloadStatus, products)
        feature_template_path = CADIP_CONFIG / "ODataToSTAC_template.json"
        stac_mapper_path = CADIP_CONFIG / "adgs_stac_mapper.json"
        with (
            open(feature_template_path, encoding="utf-8") as template,
            open(stac_mapper_path, encoding="utf-8") as stac_map,
        ):
            feature_template = json.loads(template.read())
            stac_mapper = json.loads(stac_map.read())
            stac_feature_collection = create_stac_collection(products, feature_template, stac_mapper)
        logger.info("Succesfully listed and processed products from AUX station")
        return JSONResponse(status_code=status.HTTP_200_OK, content=stac_feature_collection)
    except CreateProviderFailed:
        logger.error("Failed to create EODAG provider!")
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Bad station identifier")
    except sqlalchemy.exc.OperationalError:
        logger.error("Failed to connect to database!")
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="Database connection error")
