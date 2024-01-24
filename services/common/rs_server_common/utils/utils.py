"""This module is used to share common functions between apis endpoints"""
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import sqlalchemy
from eodag import setup_logging
from fastapi import status
from fastapi.responses import JSONResponse
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import (
    EDownloadStatus,
    ProductDownloadStatus,
)
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    PutFilesToS3Config,
    S3StorageHandler,
)
from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)

# TODO: the value was set to 1.8s but it sometimes doesn't pass the CI in github.
DWN_THREAD_START_TIMEOUT = 5


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
    """Dataclass to store arguments needed for eodag download.

    Attributes:
        db_handler (ProductDownloadStatus): An instance used to access the database.
        thread_started (threading.Event): Event to signal the start of the download thread.
        station (str): Station identifier (needed only for CADIP).
        product_id (str): Identifier of the product to be downloaded.
        name (str): Filename of the file to be downloaded.
        local (str | None): Local path where the product will be stored
        obs (str | None): Path to the S3 storage where the file will be uploaded
    """

    db_handler: ProductDownloadStatus
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
    db_product: ProductDownloadStatus,
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


def prepare_products(db_handler, products) -> list:
    """Function used to write EOProducts to db and serialize them to JSON content."""
    try:
        output = write_search_products_to_db(db_handler, products)
    except Exception:  # pylint: disable=broad-exception-caught
        return []
    return output


def eodag_download(argument: EoDAGDownloadHandler, db, init_data_retriever, **kwargs):
    """Start the eodag download process.

    This function initiates the eodag download process using the provided arguments. It sets up
    the necessary configurations, starts the download thread, and updates the download status in the
    database based on the outcome of the download.

    Args:
        argument (EoDAGDownloadHandler): An instance of EoDAGDownloadHandler containing
         the arguments used in the downloading process
    NOTE: The local and obs parameters are optionals:
    - local (str | None): Local path where the product will be stored. If this
        parameter is not given, the local path where the file is stored will be set to a temporary one
    - obs (str | None): Path to S3 storage where the file will be uploaded, after a successfull download from CADIP
        server. If this parameter is not given, the file will not be uploaded to the s3 storage.

    Returns:
        None

    Raises:
        RuntimeError: If there is an issue connecting to the S3 storage during the download.
    """

    # Open a database sessions in this thread, because the session from the root thread may have closed.
    # Get the product download status

    db_product = argument.db_handler.get(db, name=argument.name)
    # init eodag object
    try:
        logger.debug(
            "%s : %s : %s: Thread started !",
            os.getpid(),
            threading.get_ident(),
            datetime.now(),
        )

        setup_logging(3, no_progress_bar=True)
        # tempfile to be used here

        # Update the status to IN_PROGRESS in the database
        db_product.in_progress(db)
        local = kwargs["default_path"] if not argument.local else Path(argument.local)
        data_retriever = init_data_retriever(argument.station, kwargs["storage"], kwargs["download_monitor"], local)
        # notify the main thread that the download will be started
        argument.thread_started.set()
        init = datetime.now()
        data_retriever.download(argument.product_id, argument.name)
        logger.info(
            "%s : %s : File: %s downloaded in %s",
            os.getpid(),
            threading.get_ident(),
            argument.name,
            datetime.now() - init,
        )
    except Exception as exception:  # pylint: disable=broad-exception-caught
        # Pylint disabled since error is logged here.
        logger.error(
            "%s : %s : %s: Exception caught: %s",
            os.getpid(),
            threading.get_ident(),
            datetime.now(),
            exception,
        )

        # Try n times to update the status to FAILED in the database
        update_db(db, db_product, EDownloadStatus.FAILED, repr(exception))
        return

    if argument.obs:
        try:
            # NOTE: The environment variables have to be set from outside
            # otherwise the connection with the s3 endpoint fails
            s3_handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],  # "sbg",
            )
            obs_array = argument.obs.split("/")
            s3_config = PutFilesToS3Config(
                [str(data_retriever.filename)],
                obs_array[2],
                "/".join(obs_array[3:]),
                0,
            )
            s3_handler.put_files_to_s3(s3_config)
        except RuntimeError:
            logger.error("Could not connect to the s3 storage")
            # Try n times to update the status to FAILED in the database
            update_db(
                db,
                db_product,
                EDownloadStatus.FAILED,
                "Could not connect to the s3 storage",
            )
            return
        finally:
            os.remove(data_retriever.filename)

    # Try n times to update the status to DONE in the database
    update_db(db, db_product, EDownloadStatus.DONE)
    logger.debug("Download finished succesfully for %s", db_product.name)
