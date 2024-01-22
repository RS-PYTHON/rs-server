"""Module used to download CADU files."""
import os
import os.path as osp
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Event

from eodag import setup_logging
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from rs_server_cadip.cadip_retriever import init_cadip_data_retriever
from rs_server_cadip.cadu_download_status import CaduDownloadStatus, EDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.s3_storage_handler.s3_storage_handler import (
    PutFilesToS3Config,
    S3StorageHandler,
)
from rs_server_common.utils.logging import Logging

from rs_server.api_common.utils import (
    DWN_THREAD_START_TIMEOUT,
    EoDAGDownloadHandler,
    update_db,
)

router = APIRouter(tags=["Cadu products"])

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent.parent / "services" / "cadip" / "config"

logger = Logging.default(__name__)


def start_eodag_download(argument: EoDAGDownloadHandler):
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
    with tempfile.TemporaryDirectory() as default_temp_path, contextmanager(get_db)() as db:
        # Get the product download status
        db_product = CaduDownloadStatus.get(db, name=argument.name)

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
            local = default_temp_path if not argument.local else Path(argument.local)

            data_retriever = init_cadip_data_retriever(argument.station, None, None, local)

            # Update the status to IN_PROGRESS in the database
            db_product.in_progress(db)
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
                # otherwise the connection with s3 endpoint fails
                secrets = {
                    "s3endpoint": os.environ["S3_ENDPOINT"],
                    "accesskey": os.environ["S3_ACCESSKEY"],
                    "secretkey": os.environ["S3_SECRETKEY"],
                }
                s3_handler = S3StorageHandler(
                    secrets["accesskey"],
                    secrets["secretkey"],
                    secrets["s3endpoint"],
                    "sbg",
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


@router.get("/cadip/{station}/cadu")
def download(
    station: str,
    name: str,
    local: str = "",
    obs: str = "",
    db=Depends(get_db),
):  # pylint: disable=too-many-arguments
    """Initiate an asynchronous download process for a CADU product using EODAG.

    This endpoint triggers the download of a CADU product identified by the given
    name, and observation identifier. It starts the download process in a separate thread
    using the start_eodag_download function and updates the product's status in the database.

    Args:
        station (str): The EODAG station identifier.
        name (str): The name of the CADU product.
        local (str, optional): The local path where the CADU file will be downloaded.
        obs (str, optional): S3 storage path where the CADU file will be uploaded
        db (Database): The database connection object.

    Returns:
        dict: A dictionary indicating whether the download process has started.

    Raises:
        None
    """

    # Get the product download status from database
    try:
        db_product = CaduDownloadStatus.get(db, name=name)
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(exception)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"started": "false"},
        )

    # start a thread to run the action in background
    logger.debug(
        "%s : %s : %s: MAIN THREAD: Starting thread, local = %s",
        os.getpid(),
        threading.get_ident(),
        datetime.now(),
        locals(),
    )

    thread_started = Event()
    eodag_args = EoDAGDownloadHandler(thread_started, station, str(db_product.product_id), name, local, obs)
    # Big note / TODO here
    # Is there a mechanism to catch / capture return value from a function running inside a thread?
    # If start_eodag_download throws an error, there is no simple solution to return it with FastAPI
    thread = threading.Thread(
        target=start_eodag_download,
        args=(eodag_args,),
    )
    thread.start()

    # check the start of the thread
    if not thread_started.wait(timeout=DWN_THREAD_START_TIMEOUT):
        logger.error("Download thread did not start !")
        # Try n times to update the status to FAILED in the database
        update_db(db, db_product, EDownloadStatus.FAILED, "Download thread did not start !")
        return JSONResponse(status_code=status.HTTP_408_REQUEST_TIMEOUT, content={"started": "false"})

    return JSONResponse(status_code=status.HTTP_200_OK, content={"started": "true"})
