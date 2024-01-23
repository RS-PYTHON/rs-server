"""Module used to download AUX files from ADGS station."""
import tempfile
import threading
from contextlib import contextmanager
from typing import Optional

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from rs_server_adgs.adgs_download_status import AdgsDownloadStatus
from rs_server_adgs.adgs_retriever import init_adgs_retriever
from rs_server_common.db.database import get_db
from rs_server_common.models.product_download_status import EDownloadStatus
from rs_server_common.utils.logging import Logging
from rs_server_common.utils.utils import (
    DWN_THREAD_START_TIMEOUT,
    EoDAGDownloadHandler,
    eodag_download,
    update_db,
)

router = APIRouter(tags=["AUX products"])

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

    with tempfile.TemporaryDirectory() as default_temp_path, contextmanager(get_db)() as db:
        eodag_download(
            argument,
            db,
            init_adgs_retriever,
            storage=None,
            download_monitor=None,
            default_path=default_temp_path,
        )


@router.get("/adgs/aux")
def download(name: str, local: Optional[str] = None, obs: Optional[str] = None, db=Depends(get_db)):
    """Initiate an asynchronous download process for an ADGS product using EODAG.

    This endpoint triggers the download of an ADGS product identified by the given
    name of the file. It starts the download process in a separate thread
    using the start_eodag_download function and updates the product's status in the database.

    Args:
        name (str): The name of the ADGS product.
        local (str, optional): The local path where the ADGS file will be downloaded.
        obs (str, optional): S3 storage path where the ADGS file will be uploaded
        db (Database): The database connection object.

    Returns:
        dict: A dictionary indicating whether the download process has started.

    Raises:
        None
    """
    try:
        db_product = AdgsDownloadStatus.get(db, name=name)
    except Exception as exception:  # pylint: disable=broad-exception-caught
        logger.error(exception)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"started": "false"},
        )

    # Reset status to not_started
    db_product.not_started(db)

    # start a thread to run the action in background
    thread_started = threading.Event()
    # fmt: off
    eodag_args = EoDAGDownloadHandler(
        AdgsDownloadStatus, thread_started, "ADGS", str(db_product.product_id),
        name, local, obs,
    )
    # fmt: on
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
