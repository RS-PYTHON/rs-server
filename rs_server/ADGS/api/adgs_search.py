"""Docstring will be here."""
from contextlib import contextmanager

from db.database import get_db
from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from rs_server_common.utils.logging import Logging

from rs_server.api_common.utils import (
    validate_inputs_format,
    write_search_products_to_db,
)
from services.adgs.rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from services.adgs.rs_server_adgs.adgs_retriever import init_adgs_retriever
from services.common.rs_server_common.data_retrieval.provider import (
    CreateProviderFailed,
)

logger = Logging.default(__name__)
router = APIRouter(tags=["AUX products"])


@router.get("/adgs/aux/search")
async def search_aux_handler(start_date: str, stop_date: str):
    """Docstring will be here."""
    is_valid, exception = validate_inputs_format(start_date, stop_date)
    if not is_valid:
        return exception

    try:
        data_retriever = init_adgs_retriever(None, None, None)
        products = data_retriever.search(start_date, stop_date)
        processed_products = prepare_products(products)
        logger.info("Succesfully listed and processed products from AUX station")
        return JSONResponse(status_code=status.HTTP_200_OK, content={"AUX": processed_products})
    except CreateProviderFailed:
        logger.error("Failed to create EODAG provider!")
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content="Bad station identifier")


def prepare_products(products):
    try:
        output = write_search_products_to_db(AdgsDownloadStatus, products)
    except Exception:
        return []
    return output
