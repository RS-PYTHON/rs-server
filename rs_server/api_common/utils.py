"""This module is used to share common functions between apis endpoints"""
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy
from db.database import get_db
from fastapi import status
from fastapi.responses import JSONResponse
from rs_server_common.utils.logging import Logging

from services.common.models.product_download_status import EDownloadStatus

logger = Logging.default(__name__)


def is_valid_date_format(date: str) -> bool:
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
    >>> is_valid_date_format("2023-01-01T12:00:00.000Z")
    True

    >>> is_valid_date_format("2023-01-01 12:00:00")
    False
    """
    try:
        datetime.strptime(date, "%Y-%m-%dT%H:%M:%S.%fZ")
        return True
    except ValueError:
        return False


def validate_inputs_format(start_date, stop_date):
    """Docstring will be here."""
    if (not is_valid_date_format(start_date)) or (not is_valid_date_format(stop_date)):
        logger.error("Invalid start/stop in endpoint call!")
        return False, JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content="Invalid request, invalid start/stop format",
        )
    return True, None


@dataclass
class EoDAGDownloadHandler:
    """This dataclass is used to create the collection of arguments needed for eodag download."""

    thread_started: threading.Event
    station: str  # needed only for CADIP
    product_id: str
    name: str
    local: str | None
    obs: str | None


def write_search_products_to_db(db_handler_class, products):
    jsonify_state_products = []
    with contextmanager(get_db)() as db:
        try:
            for product in products:
                jsonify_state_products.append((product.properties["id"], product.properties["Name"]))

                if db_handler_class.get_if_exists(db, product.properties["Name"]) is not None:
                    logger.info(
                        "Product %s is already registered in database, skipping",
                        product.properties["Name"],
                    )
                    continue

                db_handler_class.create(
                    db,
                    product_id=product.properties["id"],
                    name=product.properties["Name"],
                    available_at_station=datetime.fromisoformat(product.properties["startTimeFromAscendingNode"]),
                    status=EDownloadStatus.NOT_STARTED,
                )

        except sqlalchemy.exc.OperationalError:
            logger.error("Failed to connect with DB during listing procedure")
            raise
