"""Docstring will be here."""
import sqlalchemy
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from rs_server_adgs import adgs_tags
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_adgs.adgs_retriever import init_adgs_retriever
from rs_server_common.data_retrieval.provider import CreateProviderFailed
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import prepare_products, validate_inputs_format

logger = Logging.default(__name__)
router = APIRouter(tags=adgs_tags)


@router.get("/adgs/aux/search")
async def search_aux_handler(start_date: str, stop_date: str):
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
    is_valid, exception = validate_inputs_format(start_date, stop_date)
    if not is_valid:
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=f"Invalid start/stop format, {exception}")

    try:
        data_retriever = init_adgs_retriever("ADGS", None, None, None)
        products = data_retriever.search(start_date, stop_date)
        processed_products = prepare_products(AdgsDownloadStatus, products)
        logger.info("Succesfully listed and processed products from AUX station")
        return JSONResponse(status_code=status.HTTP_200_OK, content={"AUX": processed_products})
    except CreateProviderFailed:
        logger.error("Failed to create EODAG provider!")
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Bad station identifier")
    except sqlalchemy.exc.OperationalError:
        logger.error("Failed to connect to database!")
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="Database connection error")
