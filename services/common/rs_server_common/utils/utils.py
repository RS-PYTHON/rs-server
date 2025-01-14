# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""This module is used to share common functions between apis endpoints"""

import os
import shutil
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Union

import sqlalchemy
from eodag import EOProduct, setup_logging
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError, ValidatorFunctionWrapHandler
from rs_server_common.data_retrieval.provider import Provider
from rs_server_common.db.database import get_db
from rs_server_common.db.models.download_status import DownloadStatus, EDownloadStatus
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    PutFilesToS3Config,
    S3StorageHandler,
)
from rs_server_common.utils.logging import Logging
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

# pylint: disable=too-few-public-methods

logger = Logging.default(__name__)

# TODO: the value was set to 1.8s but it sometimes doesn't pass the CI in github.
DWN_THREAD_START_TIMEOUT = 5


def is_valid_date_format(date: str) -> bool:
    """Check if a string adheres to the expected date format "YYYY-MM-DDTHH:MM:SS[.sss]Z".

    Args:
        date (str): The string to be validated for the specified date format.

    Returns:
        bool: True if the input string adheres to the expected date format, otherwise False.

    """
    try:
        datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ")  # test without milliseconds
        return True
    except ValueError:
        try:
            datetime.strptime(date, "%Y-%m-%dT%H:%M:%S.%fZ")  # test with milliseconds
            return True
        except ValueError:
            pass
    return False


def validate_str_list(parameter: str, handler: ValidatorFunctionWrapHandler) -> Union[List, str]:
    """
    Validates and parses a parameter that can be either a string or a comma-separated list of strings.

    The function processes the input parameter to:
    - Strip whitespace from each item in a comma-separated list.
    - Return a single string if the list has only one item.
    - Return a list of strings if the input contains multiple valid items.

    Examples:
        - Input: 'S1A'
          Output: 'S1A' (str)

        - Input: 'S1A, S2B'
          Output: ['S1A', 'S2B'] (list of str)

          # Test case bgfx, when input contains ',' but not a validd value, output should not be ['S1A', '']
        - Input: 'S1A,'
          Output: 'S1A' (str)

        - Input: 'S1A, S2B, '
          Output: ['S1A', 'S2B'] (list of str)
    """
    try:
        if parameter:
            handler(parameter)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot validate: {parameter}",
        ) from exc

    if parameter and "," in parameter:
        items = [item.strip() for item in parameter.split(",") if item.strip()]
        return items if len(items) > 1 else items[0]
    return parameter


def validate_inputs_format(
    date_time: str,
    raise_errors: bool = True,
) -> Any:
    """
    Validate the format and content of a time interval string.

    This function checks whether the provided time interval string is in a valid format and
    whether the start and stop dates conform to the ISO 8601 standard. It supports a variety
    of interval formats, including open-ended intervals.

    Args:
        date_time (str): The time interval string to validate. Supported formats include:
            - "2024-01-01T00:00:00Z/2024-01-02T23:59:59Z" (closed interval)
            - "../2024-01-02T23:59:59Z" (open start interval)
            - "2024-01-01T00:00:00Z/.." (open end interval)
            - "2024-01-01T00:00:00Z" (fixed date)
        raise_errors (bool): If True, raises an exception for invalid input.
            If False, returns [None, None, None] for invalid input.

    Returns:
        List[Union[datetime, None]]: A list containing three elements:
            - fixed_date (datetime or None): The single fixed date if applicable.
            - start_date (datetime or None): The start date of the interval.
            - stop_date (datetime or None): The stop date of the interval.
            Returns [None, None, None] if the input is invalid or empty.

    Raises:
        HTTPException: If `raise_errors` is True and the input is invalid, an HTTP 400 or 422
        error is raised.

    Note:
        - The input interval should use the ISO 8601 format for dates and times.
        - If using an open-ended interval, one side of the interval can be omitted
          (e.g., "../2024-01-02T23:59:59Z").
    """
    fixed_date, start_date, stop_date = "", "", ""
    if not date_time:
        return None, None, None
    try:
        if "/" in date_time:
            # Open/Closed interval, ../2018-02-12T23:20:50Z or 2018-02-12T23:20:50Z/..
            start_date, stop_date = date_time.split("/")
        else:
            fixed_date = date_time
    except ValueError as exc:
        logger.error("Missing start or stop in endpoint call!")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing start/stop") from exc

    for date in [fixed_date, start_date, stop_date]:
        if date.strip("'\".") and not is_valid_date_format(date):
            logger.info("Invalid start/stop in endpoint call!")
            if raise_errors:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing start/stop")
            return None, None, None

    def to_dt(dates) -> List[Any]:
        """Converts a list of date strings to datetime objects or None if the conversion fails."""
        return [datetime.fromisoformat(date) if is_valid_date(date) else None for date in dates]

    def is_valid_date(date: str) -> bool:
        """Check if the string can be converted to a valid datetime."""
        try:
            datetime.fromisoformat(date)
            return True
        except ValueError:
            return False

    fixed_date_dt, start_date_dt, stop_date_dt = to_dt([fixed_date, start_date, stop_date])

    # if fixed_date_dt and "." not in fixed_date:
    #     # If miliseconds are not defined, don't set to .000Z create a timeinterval, to gather all products
    #     # from that milisecond
    #     start_date_dt = fixed_date_dt.replace(microsecond=0)  # type: ignore
    #     stop_date_dt = fixed_date_dt.replace(microsecond=999999)  # type: ignore
    #     fixed_date_dt = None
    #     return fixed_date_dt, start_date_dt, stop_date_dt
    # if stop_date_dt and "." not in stop_date:
    #     # If stop_date interval miliseconds value is not defined, set it to 999
    #     stop_date_dt = stop_date_dt.replace(microsecond=999999)  # type: ignore

    return fixed_date_dt, start_date_dt, stop_date_dt


@dataclass
class EoDAGDownloadHandler:
    """Dataclass to store arguments needed for eodag download.

    Attributes:
        db_handler (DownloadStatus): An instance used to access the database.
        thread_started (threading.Event): Event to signal the start of the download thread.
        station (str): Station identifier (needed only for CADIP).
        product_id (str): Identifier of the product to be downloaded.
        name (str): Filename of the file to be downloaded.
        local (str | None): Local path where the product will be stored
        obs (str | None): Path to the S3 storage where the file will be uploaded
    """

    db_handler: DownloadStatus
    thread_started: threading.Event
    station: str  # needed only for CADIP
    product_id: str
    name: str
    local: str | None
    obs: str | None


def write_search_products_to_db(db_handler_class: DownloadStatus, products: EOProduct) -> None:
    """
    Processes a list of products by adding them to the database if not already present.

    This function iterates over a list of products. For each product, it checks whether the product
    is already registered in the database. If the product is not in the database, it is added with
    its relevant details. The function collects a list of product IDs and names for further processing.

    Args:
        db_handler_class (DownloadStatus): The database handler class used for database operations.
        products (List[Product]): A list of product objects to be processed.

    Returns:
        products (List[Tuple[str, str]]): A list of tuples, each containing the 'id' and 'Name' properties of a product.

    Raises:
        sqlalchemy.exc.OperationalError: If there's an issue connecting to the database.

    Notes:
    The function assumes that 'products' is a list of objects with a 'properties' attribute,
    which is a dictionary containing keys 'id', 'Name', and 'startTimeFromAscendingNode'.

    'get_db' is a context manager that provides a database session.

    'EDownloadStatus' is an enumeration representing download status.
    """
    with contextmanager(get_db)() as db:
        try:
            for product in products:
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
                    available_at_station=datetime.fromisoformat(product.properties["StartPublicationDate"]),
                    status=EDownloadStatus.NOT_STARTED,
                )

        except sqlalchemy.exc.OperationalError:
            logger.error("Failed to connect with DB during listing procedure")
            raise


def update_db(
    db: sqlalchemy.orm.Session,
    db_product: DownloadStatus,
    estatus: EDownloadStatus,
    status_fail_message=None,
):
    """Update the download status of a product in the database.

    This function attempts to update the download status of a product in the database.
    It retries the update operation for a maximum of three times, waiting 1 second between attempts.

    Args:
        db (sqlalchemy.orm.Session): The database session.
        db_product (DownloadStatus): The product whose status needs to be updated.
        estatus (EDownloadStatus): The new download status.
        status_fail_message (Optional[str]): An optional message associated with the failure status.

    Raises:
        OperationalError (sqlalchemy.exc): If the database update operation fails after multiple attempts.

    Example:
        >>> update_db(db_session, product_instance, EDownloadStatus.DONE)

    Note:
        - This function is designed to update the download status in the database.
        - It retries the update operation for a maximum of three times.
        - If the update fails, an exception is raised, indicating an issue with the database.

    """
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


def eodag_download(
    argument: EoDAGDownloadHandler,
    db,
    init_provider: Callable[[str], Provider],
    **kwargs,
):  # pylint: disable=too-many-locals
    """Initiates the eodag download process.

    Args:
        argument (EoDAGDownloadHandler): An instance of EoDAGDownloadHandler containing the arguments used in the
    downloading process.
        db: The database connection object.
        init_provider (Callable[[str], Provider]): A function to initialize the provider for downloading.
        **kwargs: Additional keyword arguments.

    Note:
        The local and obs parameters are optional:
        - local (str | None): Local path where the product will be stored. If this
            parameter is not given, the local path where the file is stored will be set to a temporary one.
        - obs (str | None): Path to S3 storage where the file will be uploaded, after a successful download from CADIP
            server. If this parameter is not given, the file will not be uploaded to the S3 storage.

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
        local = kwargs["default_path"] if not argument.local else argument.local
        # notify the main thread that the download will be started
        # To be discussed: init_provider may fail, but in the same time it takes too much
        # when properly initialized, and the timeout for download endpoint return is overpassed
        argument.thread_started.set()
        provider = init_provider(argument.station)
        init = datetime.now()
        filename = Path(local) / argument.name
        provider.download(argument.product_id, filename)
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

    # EoDAG 3.0 update:
    # lone file (e.g. NetCDF or grib files) or zip file with a lone file products: a directory with the name of
    # the product title is created to place the file in
    file_dir = Path(local) / argument.name
    file_location = file_dir / argument.name

    if file_dir.is_dir():

        # If eodag changed the file extension, restore it
        files = list(file_dir.iterdir())
        if (len(files) == 1) and (files[0] != file_location) and (files[0].stem == file_location.stem):
            shutil.move(files[0], file_location)

        if file_location.is_file():
            temp_loc = Path(local) / f"{uuid.uuid4()}_{argument.name}"
            shutil.move(file_location, temp_loc)
            file_dir.rmdir()  # Remove the original directory
            shutil.move(temp_loc, file_dir)

    if argument.obs:
        try:
            # NOTE: The environment variables have to be set from outside
            # otherwise the connection with the s3 endpoint fails
            # TODO: the secrets should be set through env vars
            # pylint: disable=pointless-string-statement
            """
            secrets = {
                "s3endpoint": None,
                "accesskey": None,
                "secretkey": None,
            }
            S3StorageHandler.get_secrets_from_file(secrets, "/home/" + os.environ["USER"] + "/.s3cfg")
            os.environ["S3_ACCESSKEY"] = secrets["accesskey"]
            os.environ["S3_SECRETKEY"] = secrets["secretkey"]
            os.environ["S3_ENDPOINT"] = secrets["s3endpoint"]
            os.environ["S3_REGION"] = "sbg"
            """
            s3_handler = S3StorageHandler(
                os.environ["S3_ACCESSKEY"],
                os.environ["S3_SECRETKEY"],
                os.environ["S3_ENDPOINT"],
                os.environ["S3_REGION"],  # "sbg",
            )
            obs_array = argument.obs.split("/")  # s3://bucket/path/to
            s3_config = PutFilesToS3Config(
                [str(filename)],
                obs_array[2],
                "/".join(obs_array[3:]),
            )
            s3_handler.put_files_to_s3(s3_config)
        except (RuntimeError, KeyError) as e:
            logger.exception(f"Failed to connect to the s3 storage: {e}")
            # Try n times to update the status to FAILED in the database
            update_db(
                db,
                db_product,
                EDownloadStatus.FAILED,
                "Failed to connect to the s3 storage",
            )
            return
        except Exception as e:  # pylint: disable=broad-except
            logger.exception(f"General exception: {e}")
            return
        finally:
            os.remove(filename)

    # Try n times to update the status to DONE in the database
    update_db(db, db_product, EDownloadStatus.DONE)
    logger.debug("Download finished succesfully for %s", db_product.name)


def odata_to_stac(feature_template: dict, odata_dict: dict, odata_stac_mapper: dict) -> dict:
    """
    Maps OData values to a given STAC template.

    Args:
        feature_template (dict): The STAC feature template to be populated.
        odata_dict (dict): The dictionary containing OData values.
        odata_stac_mapper (dict): The mapping dictionary for converting OData keys to STAC properties.

    Returns:
        dict: The populated STAC feature template.

    Raises:
        ValueError: If the provided STAC feature template is invalid.
    """
    if not all(item in feature_template.keys() for item in ["properties", "id", "assets"]):
        raise ValueError("Invalid stac feature template")
    for stac_key, eodag_key in odata_stac_mapper.items():
        if eodag_key in odata_dict:
            if stac_key in feature_template["properties"]:
                feature_template["properties"][stac_key] = odata_dict[eodag_key]
            elif stac_key == "id":
                feature_template["id"] = odata_dict[eodag_key]
            elif stac_key in feature_template["assets"]["file"]:
                feature_template["assets"]["file"][stac_key] = odata_dict[eodag_key]
    # to pass pydantic validation, make sure we don't have a single timerange value
    check_and_fix_timerange(feature_template)
    return feature_template


def check_and_fix_timerange(item: dict):
    """This function ensures the item does not have a single timerange value"""
    properties = item.get("properties", {})

    start_dt = properties.get("start_datetime")
    end_dt = properties.get("end_datetime")
    dt = properties.get("datetime")

    if start_dt and not end_dt:
        properties["end_datetime"] = max(start_dt, dt) if dt else start_dt
        logger.warning(f"Forced end_datetime property in {item}")
    elif end_dt and not start_dt:
        properties.pop("end_datetime", None)
        logger.warning(f"Removed end_datetime property from {item}")


def extract_eo_product(eo_product: EOProduct, mapper: dict) -> dict:
    """This function is creating key:value pairs from an EOProduct properties"""
    eo_product.properties.update(
        {item.get("Name", None): item.get("Value", None) for item in eo_product.properties.get("attrs", [])},
    )
    return {key: value for key, value in eo_product.properties.items() if key in mapper.values()}


def validate_sort_input(sortby: str):
    """Used to transform stac sort parameter to odata type.
    -datetime = startTimeFromAscendingNode DESC.
    """
    sortby = sortby.strip("'\"").lower()
    return [(sortby[1:], "DESC" if sortby[0] == "-" else "ASC")]


class DontRaiseExceptions(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """
    In FastAPI we can raise HttpExceptions in the middle of the python code, instead of returning a JSONResponse.
    But that doesn't work well in some cases. So we catch all exceptions and return a JSONResponse instead.
    """

    async def dispatch(self, request: Request, call_next: Callable):
        """
        Middleware implementation.
        """

        try:
            return await call_next(request)  # Call the next middleware
        except Exception as exception:  # pylint: disable=broad-exception-caught

            # Print the error with the stacktrace in the log
            logger.error(traceback.format_exc())

            # Get the status code and content from the HTTPException
            if isinstance(exception, StarletteHTTPException):
                status_code = exception.status_code
                content = exception.detail

            # Else use a generic status code, and content = exception message
            else:
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
                content = repr(exception)

            return JSONResponse(status_code=status_code, content=content)
