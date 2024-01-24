"""Module used to download CADU files."""
import os
import os.path as osp
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import Event

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from rs_server_cadip import cadip_tags
from rs_server_cadip.cadip_retriever import init_cadip_data_retriever
from rs_server_cadip.cadu_download_status import CaduDownloadStatus, EDownloadStatus
from rs_server_common.db.database import get_db
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    DWN_THREAD_START_TIMEOUT,
    EoDAGDownloadHandler,
    eodag_download,
    update_db,
)

router = APIRouter(tags=cadip_tags)

CONF_FOLDER = Path(osp.realpath(osp.dirname(__file__))).parent.parent.parent / "services" / "cadip" / "config"

logger = Logging.default(__name__)


def start_eodag_download(argument: EoDAGDownloadHandler):
    """Start the eodag download process.

    This function initiates the eodag download process using the provided arguments. It sets up
    the temporary directory where the files are to be downloaded and gets the database handler

    Args:
        argument (EoDAGDownloadHandler): An instance of EoDAGDownloadHandler containing
         the arguments used in the downloading process

    Returns:
        None

    """

    # Open a database sessions in this thread, because the session from the root thread may have closed.
    with tempfile.TemporaryDirectory() as default_temp_path, contextmanager(get_db)() as db:
        eodag_download(
            argument,
            db,
            init_cadip_data_retriever,
            storage=None,
            download_monitor=None,
            default_path=default_temp_path,
        )


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
    name of the file. It starts the download process in a separate thread
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

    # Reset status to not_started
    db_product.not_started(db)

    # start a thread to run the action in background
    logger.debug(
        "%s : %s : %s: MAIN THREAD: Starting thread, local = %s",
        os.getpid(),
        threading.get_ident(),
        datetime.now(),
        locals(),
    )

    thread_started = Event()
    # fmt: off
    # Skip this function call formatting to avoid the following error: pylint R0801: Similar lines in 2 files
    eodag_args = EoDAGDownloadHandler(
        CaduDownloadStatus, thread_started, station, str(db_product.product_id),
        name, local, obs,
    )
    # fmt: on
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
