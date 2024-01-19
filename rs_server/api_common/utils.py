"""This module is used to share common functions between apis endpoints"""
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy
from rs_server_common.db.database import get_db
from fastapi import status
from fastapi.responses import JSONResponse
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_cadip.cadu_download_status import CaduDownloadStatus
from rs_server_common.utils.logging import Logging

from rs_server_common.models.product_download_status import EDownloadStatus

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
    """
    Validate the date format of start_date and stop_date.

    Parameters:
    - start_date (str): The start date to be validated.
    - stop_date (str): The stop date to be validated.

    Returns:
    tuple[bool, JSONResponse]: A tuple containing a boolean indicating the validity of the date format
    and a JSONResponse instance. If the date format is invalid, the boolean is False, and the JSONResponse
    contains a 400 Bad Request response with an appropriate error message. If the date format is valid,
    the boolean is True, and the JSONResponse is None.
    """
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


def write_search_products_to_db(db_handler_class, products) -> list:
    """
    Process a list of products by adding them to the database if not already present.

    This function iterates over a list of products. For each product, it checks whether the product
    is already registered in the database. If the product is not in the database, it is added with
    its relevant details. The function collects a list of product IDs and names for further processing.

    Parameters:
    - products (List[Product]): A list of product objects to be processed.
    - db_handler_class: The database handler class used for database operations.

    Returns:
    List[Tuple]: A list of tuples, each containing the 'id' and 'Name' properties of a product.

    Raises:
    - sqlalchemy.exc.OperationalError: If there's an issue connecting to the database.

    Note:
    - The function assumes that 'products' is a list of objects with a 'properties' attribute,
      which is a dictionary containing keys 'id', 'Name', and 'startTimeFromAscendingNode'.
    - 'get_db' is a context manager that provides a database session.
    - 'EDownloadStatus' is an enumeration representing download status.
    """
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
    return jsonify_state_products


def update_db(
    db,
    db_product: CaduDownloadStatus | AdgsDownloadStatus,
    estatus: EDownloadStatus,
    status_fail_message=None,
):
    """Update the database with the status of a product."""

    # Try n times to update the status.
    # Don't do it for NOT_STARTED and IN_PROGRESS (call directly db_product.not_started
    # or db_product.in_progress) because it will anyway be overwritten later by DONE or FAILED.

    # Init last exception to empty value.
    last_exception: Exception = Exception()

    for _ in range(3):
        try:
            if estatus == EDownloadStatus.FAILED:
                db_product.failed(db, status_fail_message)
            elif estatus == EDownloadStatus.DONE:
                db_product.done(db)

            # The database update worked, exit function
            return

        # The database update failed, wait n seconds and retry
        except sqlalchemy.exc.OperationalError as exception:
            logger.error(f"Error updating status in database:\n{exception}")
            last_exception = exception
            time.sleep(1)

    # If all attemps failed, raise the last Exception
    raise last_exception
